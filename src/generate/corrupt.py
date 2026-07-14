"""Inject realistic defects into clean transaction data.

Applies 14 defect classes from the spec at configured injection rates,
plus 12 merchant descriptor corruption transforms. Every injected defect
is logged to defect_log.csv so the scorecard can compute true recall.

Input:  data/truth/transactions_truth.parquet, config/pipeline.yaml
Output: data/raw/transactions_raw.csv, data/raw/defect_log.csv
"""

import csv
import logging
import pathlib
import uuid

import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT, load_config, setup_logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Descriptor corruption transforms (Section 5.2)
# Each takes (name, city, rng) and returns a corrupted string.
# ---------------------------------------------------------------------------

def _aggregator_prefix(name: str, city: str, rng: np.random.Generator) -> str:
    """Prepend a payment aggregator tag like SQ *, TST*, PAYPAL *."""
    prefixes = ["SQ *", "TST* ", "PAYPAL *", "PP*", "SP * ", "GOOGLE *", "APL*"]
    return rng.choice(prefixes) + name


def _truncate(name: str, city: str, rng: np.random.Generator) -> str:
    """Hard truncation at a random length between 12 and 20 chars."""
    n = int(rng.integers(12, 21))
    return name[:n]


def _uppercase(name: str, city: str, rng: np.random.Generator) -> str:
    return name.upper()


def _lowercase(name: str, city: str, rng: np.random.Generator) -> str:
    return name.lower()


def _remove_vowels_long_words(name: str, city: str, rng: np.random.Generator) -> str:
    """Strip vowels from words longer than 5 characters."""
    words = name.split()
    result = []
    for w in words:
        if len(w) > 5:
            w = "".join(c for c in w if c.lower() not in "aeiou")
        result.append(w)
    return " ".join(result)


def _append_store_num(name: str, city: str, rng: np.random.Generator) -> str:
    num = int(rng.integers(100, 10000))
    sep = rng.choice(["#", " #", "  #"])
    return f"{name}{sep}{num:04d}"


def _append_phone(name: str, city: str, rng: np.random.Generator) -> str:
    digits = "".join(str(int(rng.integers(0, 10))) for _ in range(10))
    return f"{name} {digits}"


def _append_city(name: str, city: str, rng: np.random.Generator) -> str:
    sep = rng.choice([" ", " - ", "  "])
    return f"{name}{sep}{city}"


def _append_state_code(name: str, city: str, rng: np.random.Generator) -> str:
    codes = ["NY", "CA", "DL", "HR", "KA", "MH", "TN", "GJ", "RJ"]
    return f"{name} {rng.choice(codes)}"


def _collapse_spaces(name: str, city: str, rng: np.random.Generator) -> str:
    return name.replace(" ", "")


def _url_form(name: str, city: str, rng: np.random.Generator) -> str:
    clean = name.replace(" ", "").upper()
    suffix = rng.choice([".COM", ".IN", ".CO.IN", ".NET"])
    return f"{clean}{suffix}"


def _inject_unicode_junk(name: str, city: str, rng: np.random.Generator) -> str:
    """Insert zero-width or non-breaking chars at a random position."""
    junk_chars = ["\u200b", "\u00a0", "\ufeff", "\u200e", "\u200f"]
    if len(name) == 0:
        return name
    pos = int(rng.integers(0, len(name)))
    char = rng.choice(junk_chars)
    return name[:pos] + char + name[pos:]


# All 12 transforms, equally weighted for random selection
_DESCRIPTOR_TRANSFORMS = [
    _aggregator_prefix,
    _truncate,
    _uppercase,
    _lowercase,
    _remove_vowels_long_words,
    _append_store_num,
    _append_phone,
    _append_city,
    _append_state_code,
    _collapse_spaces,
    _url_form,
    _inject_unicode_junk,
]


# ---------------------------------------------------------------------------
# Amount string formatting
# ---------------------------------------------------------------------------

def _format_amount_string(amount: float, currency: str, rng: np.random.Generator,
                          use_parens: bool) -> str:
    """Convert a clean float to a realistically dirty amount string.

    Randomly adds currency symbols, thousands separators, whitespace, and
    optionally parenthesized-negative notation.
    """
    abs_amount = abs(amount)
    is_negative = amount < 0

    if use_parens and (is_negative or rng.random() < 0.5):
        # Parenthesized negative notation: (1,240.00)
        formatted = f"{abs_amount:,.2f}"
        symbol = "₹" if currency == "INR" else "$"
        style = int(rng.integers(0, 3))
        if style == 0:
            return f"({formatted})"
        elif style == 1:
            return f"({symbol}{formatted})"
        else:
            return f"({symbol} {formatted})"

    # Pick a random dirty format
    style = int(rng.integers(0, 8))
    symbol = "₹" if currency == "INR" else "$"

    if style == 0:
        return f"{symbol}{abs_amount:,.2f}"                  # ₹1,240.00
    elif style == 1:
        return f"{abs_amount:,.2f}"                          # 1,240.00
    elif style == 2:
        return f"{symbol} {abs_amount:,.2f} "                # ₹ 1,240.00 (with spaces)
    elif style == 3:
        return f"{abs_amount:.2f}"                           # 1240.00 (no commas)
    elif style == 4:
        return f" {abs_amount:,.2f} "                        # leading/trailing spaces
    elif style == 5:
        return f"{int(abs_amount)}"                          # 1240 (no decimals)
    elif style == 6:
        neg = "-" if is_negative else ""
        return f"{neg}{abs_amount:,.2f}"                     # -1,240.00
    else:
        return f" {symbol}{abs_amount:,.2f}"                 # leading space + symbol


# ---------------------------------------------------------------------------
# City variant injection
# ---------------------------------------------------------------------------

def _load_city_variants() -> dict[str, list[str]]:
    """Load canonical city -> [variant, variant, ...] mapping."""
    city_path = PROJECT_ROOT / "config" / "city_canonical.csv"
    df = pd.read_csv(city_path)
    variants: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        canonical = row["canonical_city"]
        variant = row["variant"]
        variants.setdefault(canonical, []).append(variant)
    return variants


# ---------------------------------------------------------------------------
# Core corruption engine
# ---------------------------------------------------------------------------

def corrupt_dataset(df_truth: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Apply all 14 defect classes and descriptor transforms to the truth data.

    Returns the corrupted DataFrame (all columns as strings, ready for CSV)
    and the defect log as a list of dicts.
    """
    rng = np.random.default_rng(cfg["seed"])
    rates = cfg["defect_rates"]
    defect_log: list[dict] = []
    n = len(df_truth)

    # Work on a copy — the truth stays untouched
    df = df_truth.copy()

    # We'll build the raw columns progressively
    log.info("Starting corruption of %d truth rows", n)

    # -----------------------------------------------------------------------
    # STEP 1: Near-duplicates (defect #12) — create new rows BEFORE corruption
    # Same account/merchant/amount, timestamp shifted by ≤ window seconds
    # -----------------------------------------------------------------------
    near_dup_count = round(n * rates["near_duplicates"])
    near_dup_indices = rng.choice(n, size=near_dup_count, replace=False)
    near_dups = df.iloc[near_dup_indices].copy()
    # Shift timestamp by 1–120 seconds
    window = cfg["near_dup_window_seconds"]
    shifts = pd.to_timedelta(rng.integers(1, window + 1, size=near_dup_count), unit="s")
    near_dups["txn_timestamp"] = near_dups["txn_timestamp"].values + shifts.values
    # Assign new transaction IDs
    hi = rng.integers(0, 2**63, size=near_dup_count, dtype=np.int64).astype(np.uint64)
    lo = rng.integers(0, 2**63, size=near_dup_count, dtype=np.int64).astype(np.uint64)
    new_ids = [str(uuid.UUID(int=int((int(h) << 64) | int(l)), version=4))
               for h, l in zip(hi, lo)]
    near_dups["transaction_id"] = new_ids
    for i, tid in enumerate(new_ids):
        orig_tid = df.iloc[near_dup_indices[i]]["transaction_id"]
        defect_log.append({
            "transaction_id": tid,
            "defect_type": "near_duplicate",
            "defect_detail": f"original={orig_tid}",
        })
    log.info("Injected %d near-duplicate rows", near_dup_count)

    # -----------------------------------------------------------------------
    # STEP 2: Extreme outliers (defect #13) — multiply amount by 100
    # Applied BEFORE string formatting so the numeric value is extreme
    # -----------------------------------------------------------------------
    outlier_count = round(n * rates["extreme_outliers"])
    outlier_indices = rng.choice(n, size=outlier_count, replace=False)
    original_amounts = df.iloc[outlier_indices]["amount"].values.copy()
    df.iloc[outlier_indices, df.columns.get_loc("amount")] = original_amounts * 100
    # Also update amount_inr
    original_inr = df.iloc[outlier_indices]["amount_inr"].values.copy()
    df.iloc[outlier_indices, df.columns.get_loc("amount_inr")] = original_inr * 100
    for idx, orig_amt in zip(outlier_indices, original_amounts):
        defect_log.append({
            "transaction_id": df.iloc[idx]["transaction_id"],
            "defect_type": "extreme_outlier",
            "defect_detail": f"original_amount={orig_amt:.2f}",
        })
    log.info("Injected %d extreme outliers (100x amount)", outlier_count)

    # Append near-dups to main DataFrame
    df = pd.concat([df, near_dups], ignore_index=True)
    n_total = len(df)
    log.info("Row count after near-dups: %d (was %d)", n_total, n)

    # -----------------------------------------------------------------------
    # STEP 3: Merchant descriptor corruption (defect #7) — 100% of rows
    # Apply 1–3 random transforms from the 12-transform list
    # -----------------------------------------------------------------------
    min_transforms = cfg["corruption_transforms_min"]
    max_transforms = cfg["corruption_transforms_max"]

    # Extract arrays to avoid df.iloc overhead in the hot loop
    names_arr = df["merchant_name"].values.astype(str)
    cities_arr = df["city"].values.astype(str)
    txn_ids_arr = df["transaction_id"].values.astype(str)

    descriptors = []
    for i in range(n_total):
        name = names_arr[i].upper()
        city = cities_arr[i]
        num_t = int(rng.integers(min_transforms, max_transforms + 1))
        chosen = rng.choice(len(_DESCRIPTOR_TRANSFORMS), size=num_t, replace=False)
        for t_idx in chosen:
            name = _DESCRIPTOR_TRANSFORMS[t_idx](name, city, rng)
        descriptors.append(name)
        defect_log.append({
            "transaction_id": txn_ids_arr[i],
            "defect_type": "descriptor_corruption",
            "defect_detail": ",".join(str(_DESCRIPTOR_TRANSFORMS[t].__name__) for t in chosen),
        })
    log.info("Corrupted %d merchant descriptors", n_total)

    # -----------------------------------------------------------------------
    # STEP 4: Date format chaos (defect #1) — 100% of rows
    # Convert datetime to one of 5 string formats + epoch ints
    # -----------------------------------------------------------------------
    date_formats = cfg["date_formats"]
    timestamps_arr = df["txn_timestamp"].values  # numpy datetime64 array

    formatted_dates = []
    for i in range(n_total):
        ts = pd.Timestamp(timestamps_arr[i])
        if pd.isna(ts):
            formatted_dates.append("")
            continue
        fmt_choice = int(rng.integers(0, len(date_formats) + 1))  # +1 for epoch
        if fmt_choice < len(date_formats):
            formatted_dates.append(ts.strftime(date_formats[fmt_choice]))
        else:
            formatted_dates.append(str(int(ts.timestamp())))
        defect_log.append({
            "transaction_id": txn_ids_arr[i],
            "defect_type": "date_format_chaos",
            "defect_detail": date_formats[fmt_choice] if fmt_choice < len(date_formats) else "epoch",
        })
    log.info("Formatted %d dates across %d formats + epoch", n_total, len(date_formats))

    # -----------------------------------------------------------------------
    # STEP 5: Impossible dates (defect #2) — 0.1% of rows
    # -----------------------------------------------------------------------
    impossible_count = round(n_total * rates["impossible_dates"])
    impossible_indices = rng.choice(n_total, size=impossible_count, replace=False)
    for idx in impossible_indices:
        if rng.random() < 0.5:
            formatted_dates[idx] = f"2030-{int(rng.integers(1,13)):02d}-{int(rng.integers(1,29)):02d} 12:00:00"
        else:
            formatted_dates[idx] = f"1900-01-{int(rng.integers(1,29)):02d} 08:00:00"
        defect_log.append({
            "transaction_id": txn_ids_arr[idx],
            "defect_type": "impossible_date",
            "defect_detail": formatted_dates[idx],
        })
    log.info("Injected %d impossible dates", impossible_count)

    # -----------------------------------------------------------------------
    # STEP 6: Amount string formatting (defect #3) — 100%
    # + Negative-in-parentheses (defect #4) — 2%
    # -----------------------------------------------------------------------
    amounts_arr = df["amount"].values.astype(float)
    currencies_arr = df["currency"].values.astype(str)

    paren_count = round(n_total * rates["paren_negatives"])
    paren_indices = set(rng.choice(n_total, size=paren_count, replace=False).tolist())
    formatted_amounts = []
    for i in range(n_total):
        use_parens = i in paren_indices
        formatted_amounts.append(_format_amount_string(amounts_arr[i], currencies_arr[i], rng, use_parens))
        if use_parens:
            defect_log.append({
                "transaction_id": txn_ids_arr[i],
                "defect_type": "paren_negative",
                "defect_detail": formatted_amounts[-1],
            })
    log.info("Formatted %d amounts (%d with paren negatives)", n_total, paren_count)

    # -----------------------------------------------------------------------
    # STEP 7: Missing currency (defect #6) — 15%
    # -----------------------------------------------------------------------
    currency_values = currencies_arr.copy().astype(object)
    missing_curr_count = round(n_total * rates["missing_currency"])
    missing_curr_indices = rng.choice(n_total, size=missing_curr_count, replace=False)
    for idx in missing_curr_indices:
        original_curr = currency_values[idx]
        currency_values[idx] = ""
        defect_log.append({
            "transaction_id": txn_ids_arr[idx],
            "defect_type": "missing_currency",
            "defect_detail": str(original_curr),
        })
    log.info("Blanked currency on %d rows", missing_curr_count)

    # -----------------------------------------------------------------------
    # STEP 8: Missing MCC (defect #8) — 25%
    # Replace with empty, "0000", or "NA"
    # -----------------------------------------------------------------------
    mcc_values = df["mcc"].astype(str).values.copy().astype(object)
    missing_mcc_count = round(n_total * rates["missing_mcc"])
    missing_mcc_indices = rng.choice(n_total, size=missing_mcc_count, replace=False)
    mcc_sentinels = ["", "0000", "NA", "N/A"]
    for idx in missing_mcc_indices:
        mcc_values[idx] = rng.choice(mcc_sentinels)
        defect_log.append({
            "transaction_id": txn_ids_arr[idx],
            "defect_type": "missing_mcc",
            "defect_detail": f"replaced_with={mcc_values[idx]}",
        })
    log.info("Corrupted MCC on %d rows", missing_mcc_count)

    # -----------------------------------------------------------------------
    # STEP 9: City variant explosion (defect #9) — 100%
    # Replace canonical city with a random known variant
    # -----------------------------------------------------------------------
    city_variants = _load_city_variants()
    city_values = []
    for i in range(n_total):
        canonical = cities_arr[i]
        variants = city_variants.get(canonical, [canonical])
        city_values.append(rng.choice(variants))
    log.info("Exploded city variants for %d rows", n_total)

    # -----------------------------------------------------------------------
    # STEP 10: Sentinel nulls (defect #10) — 8% of rows
    # Scatter sentinel values across random columns
    # -----------------------------------------------------------------------
    sentinel_list = cfg["sentinel_values"]
    sentinel_target_cols = ["account_id", "mcc", "city", "country", "channel", "status"]
    sentinel_count = round(n_total * rates["sentinel_nulls"])
    sentinel_row_indices = rng.choice(n_total, size=sentinel_count, replace=False)
    # Build mutable arrays for the sentinel target columns
    account_values = df["account_id"].values.copy().astype(object)
    country_values = df["country"].values.copy().astype(object)
    channel_values = df["channel"].values.copy().astype(object)
    status_values = df["status"].values.copy().astype(object)

    for idx in sentinel_row_indices:
        num_cols = int(rng.integers(1, 3))
        cols = rng.choice(sentinel_target_cols, size=num_cols, replace=False)
        sentinel = rng.choice(sentinel_list)
        for col in cols:
            if col == "account_id":
                account_values[idx] = sentinel
            elif col == "mcc":
                mcc_values[idx] = sentinel
            elif col == "city":
                city_values[idx] = sentinel
            elif col == "country":
                country_values[idx] = sentinel
            elif col == "channel":
                channel_values[idx] = sentinel
            elif col == "status":
                status_values[idx] = sentinel
        defect_log.append({
            "transaction_id": txn_ids_arr[idx],
            "defect_type": "sentinel_null",
            "defect_detail": f"cols={','.join(cols)},value={sentinel}",
        })
    log.info("Injected sentinel nulls on %d rows", sentinel_count)

    # -----------------------------------------------------------------------
    # STEP 11: Channel and country casing drift
    # Spec mentions "e-comm" vs "ONLINE" and "IN"/"India"/"IND"/"in"
    # -----------------------------------------------------------------------
    country_drift = {"IN": ["IN", "India", "IND", "in", "india"],
                     "US": ["US", "USA", "us"]}
    channel_drift = {"POS": ["POS", "pos", "Pos"],
                     "ONLINE": ["ONLINE", "online", "e-comm", "E-COMM", "ecomm"],
                     "ATM": ["ATM", "atm", "Atm"]}
    for i in range(n_total):
        c = country_values[i]
        if c in country_drift:
            country_values[i] = rng.choice(country_drift[c])
        ch = channel_values[i]
        if ch in channel_drift:
            channel_values[i] = rng.choice(channel_drift[ch])
        a = account_values[i]
        if isinstance(a, str) and a.startswith("ACC-"):
            drift = int(rng.integers(0, 4))
            if drift == 1:
                account_values[i] = a.lower()
            elif drift == 2:
                account_values[i] = a + " "
            elif drift == 3:
                account_values[i] = " " + a
    log.info("Applied casing drift to country/channel/account_id")

    # -----------------------------------------------------------------------
    # Assemble the raw DataFrame (all columns as strings for CSV)
    # -----------------------------------------------------------------------
    raw = pd.DataFrame({
        "transaction_id": df["transaction_id"].values,
        "account_id": account_values,
        "txn_timestamp": formatted_dates,
        "amount": formatted_amounts,
        "currency": currency_values,
        "merchant_descriptor": descriptors,
        "mcc": mcc_values,
        "city": city_values,
        "country": country_values,
        "channel": channel_values,
        "status": status_values,
    })

    # -----------------------------------------------------------------------
    # STEP 12: Exact duplicates (defect #11) — 1.0%
    # Duplicate entire corrupted rows (same transaction_id and all)
    # -----------------------------------------------------------------------
    exact_dup_count = round(len(df_truth) * rates["exact_duplicates"])
    exact_dup_indices = rng.choice(len(raw), size=exact_dup_count, replace=False)
    exact_dups = raw.iloc[exact_dup_indices].copy()
    for idx in exact_dup_indices:
        defect_log.append({
            "transaction_id": raw.iloc[idx]["transaction_id"],
            "defect_type": "exact_duplicate",
            "defect_detail": "",
        })
    raw = pd.concat([raw, exact_dups], ignore_index=True)
    log.info("Injected %d exact duplicate rows, total rows now: %d", exact_dup_count, len(raw))

    # -----------------------------------------------------------------------
    # STEP 13: Schema drift (defect #14) — 0.05%
    # Insert an extra comma in the middle of a field, shifting columns
    # -----------------------------------------------------------------------
    drift_count = round(len(raw) * rates["schema_drift"])
    drift_count = max(drift_count, 1)  # at least one for testing
    drift_indices = rng.choice(len(raw), size=drift_count, replace=False)
    for idx in drift_indices:
        # Corrupt the merchant_descriptor field by inserting an extra comma
        desc = str(raw.at[idx, "merchant_descriptor"])
        if len(desc) > 3:
            split_pos = int(rng.integers(2, len(desc) - 1))
            raw.at[idx, "merchant_descriptor"] = desc[:split_pos] + "," + desc[split_pos:]
        defect_log.append({
            "transaction_id": raw.at[idx, "transaction_id"],
            "defect_type": "schema_drift",
            "defect_detail": f"extra_comma_in_descriptor",
        })
    log.info("Injected schema drift on %d rows", drift_count)

    # Shuffle row order so duplicates are not adjacent
    raw = raw.sample(frac=1, random_state=cfg["seed"]).reset_index(drop=True)

    return raw, defect_log


def main() -> None:
    cfg = load_config()
    setup_logging(str(PROJECT_ROOT / cfg["paths"]["log_dir"]))
    log.info("Starting data corruption")

    # Load truth data
    truth_path = PROJECT_ROOT / cfg["paths"]["truth_parquet"]
    df_truth = pd.read_parquet(truth_path)
    log.info("Loaded %d truth rows from %s", len(df_truth), truth_path)

    # Corrupt
    raw, defect_log = corrupt_dataset(df_truth, cfg)

    # Write raw CSV
    raw_path = PROJECT_ROOT / cfg["paths"]["raw_csv"]
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw.to_csv(raw_path, index=False)
    log.info("Wrote %d raw rows to %s", len(raw), raw_path)

    # Write defect log
    log_path = PROJECT_ROOT / cfg["paths"]["defect_log"]
    with open(log_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["transaction_id", "defect_type", "defect_detail"])
        writer.writeheader()
        writer.writerows(defect_log)
    log.info("Wrote %d defect log entries to %s", len(defect_log), log_path)

    # Report defect counts
    from collections import Counter
    counts = Counter(d["defect_type"] for d in defect_log)
    log.info("Defect counts:")
    for defect_type, count in sorted(counts.items()):
        rate = count / len(raw) * 100
        log.info("  %-25s %6d  (%.2f%%)", defect_type, count, rate)


if __name__ == "__main__":
    main()
