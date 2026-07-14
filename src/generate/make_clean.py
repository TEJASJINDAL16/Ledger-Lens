"""Generate clean ground-truth transaction data.

Produces a realistic synthetic dataset of card transactions with proper
types, canonical merchant names, and valid dates/amounts. This truth file
is never read by the pipeline — it exists solely to score the pipeline's
output against known-good values.

Input:  config/pipeline.yaml, config/merchant_dictionary.csv
Output: data/truth/transactions_truth.parquet
"""

import csv
import logging
import pathlib
import uuid

import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT, load_config, setup_logging

log = logging.getLogger(__name__)

# Transaction frequency weights by category — daily-use merchants dominate
_CATEGORY_FREQUENCY = {
    "Food Delivery": 5,
    "Ride Sharing": 4,
    "Online Marketplace": 4,
    "Grocery": 4,
    "Coffee Shop": 3,
    "Quick Service Restaurant": 3,
    "Fuel": 3,
    "Telecom": 3,
    "Streaming": 2,
    "Apparel": 2,
    "Electronics": 2,
    "Pharmacy": 2,
    "Restaurant": 2,
    "Beauty & Personal Care": 2,
    "Entertainment": 2,
    "DTH / Telecom": 2,
    "Fitness": 1,
    "Home Services": 1,
    "Eyewear": 1,
    "Home Furnishing": 1,
    "Sporting Goods": 1,
    "Airlines": 1,
    "Railways": 1,
    "Travel Agency": 1,
    "Jewellery": 1,
    "Healthcare": 1,
}

# Hour-of-day distributions per category group (mixture-of-gaussians parameters)
_HOUR_PROFILES = {
    "Food & Beverage": {"means": [8.5, 12.5, 20.0], "stds": [1.0, 1.5, 1.5], "weights": [0.2, 0.3, 0.5]},
    "Transportation": {"means": [8.5, 18.0], "stds": [1.5, 2.0], "weights": [0.45, 0.55]},
    "Retail":         {"means": [14.0, 19.0], "stds": [3.0, 2.0], "weights": [0.5, 0.5]},
    "Travel":         {"means": [11.0, 20.0], "stds": [3.0, 2.0], "weights": [0.6, 0.4]},
    "Entertainment":  {"means": [19.0], "stds": [2.5], "weights": [1.0]},
    "Utilities":      {"means": [14.0], "stds": [5.0], "weights": [1.0]},
    "Healthcare":     {"means": [11.0], "stds": [2.5], "weights": [1.0]},
    "Services":       {"means": [13.0], "stds": [3.0], "weights": [1.0]},
    "Unclassified":   {"means": [14.0], "stds": [5.0], "weights": [1.0]},
}


def _load_merchants(cfg: dict) -> pd.DataFrame:
    """Load merchant dictionary and deduplicate to one row per merchant_id."""
    dict_path = PROJECT_ROOT / cfg["paths"]["merchant_dictionary"]
    df = pd.read_csv(dict_path)
    # Keep one canonical row per merchant — first alias row has the right metadata
    merchants = df.drop_duplicates(subset=["merchant_id"]).reset_index(drop=True)
    return merchants[["merchant_id", "canonical_name", "mcc", "category"]]


def _load_mcc_map(cfg: dict) -> dict[str, str]:
    """Map MCC code to category_group for hour-of-day profile lookup."""
    mcc_path = PROJECT_ROOT / cfg["paths"]["mcc_map"]
    df = pd.read_csv(mcc_path, dtype=str)
    return dict(zip(df["mcc"], df["category_group"]))


def _load_cities() -> list[str]:
    """Return the list of canonical city names."""
    city_path = PROJECT_ROOT / "config" / "city_canonical.csv"
    df = pd.read_csv(city_path)
    return df["canonical_city"].unique().tolist()


def _build_merchant_weights(merchants: pd.DataFrame) -> np.ndarray:
    """Assign sampling weights to merchants based on category frequency."""
    weights = np.array([
        _CATEGORY_FREQUENCY.get(cat, 2) for cat in merchants["category"]
    ], dtype=float)
    return weights / weights.sum()


def _sample_hours(rng: np.random.Generator, category_groups: np.ndarray, n: int) -> np.ndarray:
    """Sample realistic hours from category-specific mixture-of-gaussian profiles."""
    hours = np.zeros(n, dtype=float)
    for group_name, profile in _HOUR_PROFILES.items():
        mask = category_groups == group_name
        count = mask.sum()
        if count == 0:
            continue
        means = profile["means"]
        stds = profile["stds"]
        weights = np.array(profile["weights"])
        # Pick which component each sample comes from
        components = rng.choice(len(means), size=count, p=weights)
        for i, (mu, sigma) in enumerate(zip(means, stds)):
            comp_mask = components == i
            hours[np.where(mask)[0][comp_mask]] = rng.normal(mu, sigma, size=comp_mask.sum())
    # Clip to valid range and round to integer for combining with dates
    return np.clip(hours, 0, 23).astype(int)


def _load_fx_rates(cfg: dict) -> dict[str, float]:
    """Load FX rates as currency -> rate_to_inr."""
    fx_path = PROJECT_ROOT / cfg["paths"]["fx_rates"]
    df = pd.read_csv(fx_path)
    return dict(zip(df["currency"], df["rate_to_inr"]))


def generate_transactions(cfg: dict) -> pd.DataFrame:
    """Build the full clean transaction dataset.

    Returns a DataFrame with canonical merchant names, proper types, and
    realistic distributions. The row count is adjusted down from num_rows
    to leave room for duplicates that corrupt.py will inject.
    """
    rng = np.random.default_rng(cfg["seed"])

    # Account for duplicates that corrupt.py will add
    near_dup_rate = cfg["defect_rates"]["near_duplicates"]
    exact_dup_rate = cfg["defect_rates"]["exact_duplicates"]
    base_count = round(cfg["num_rows"] / (1 + near_dup_rate + exact_dup_rate))
    log.info("Generating %d base transactions (target raw total: %d)", base_count, cfg["num_rows"])

    merchants = _load_merchants(cfg)
    mcc_to_group = _load_mcc_map(cfg)
    cities = _load_cities()
    fx_rates = _load_fx_rates(cfg)
    amount_dists = cfg["amount_distributions"]

    num_merchants = len(merchants)
    num_accounts = cfg["num_accounts"]
    log.info("Using %d merchants across %d accounts", num_merchants, num_accounts)

    # --- Account IDs ---
    account_ids = [f"ACC-{i:06d}" for i in range(1, num_accounts + 1)]

    # --- Merchant assignment (weighted by category frequency) ---
    merchant_weights = _build_merchant_weights(merchants)
    merchant_indices = rng.choice(num_merchants, size=base_count, p=merchant_weights)
    merchant_rows = merchants.iloc[merchant_indices].reset_index(drop=True)

    # --- Category groups for hour profiles ---
    mccs_str = merchant_rows["mcc"].astype(str)
    category_groups = np.array([mcc_to_group.get(m, "Retail") for m in mccs_str])

    # --- Timestamps: uniform dates over 18 months + category-aware hours ---
    months = cfg["time_span_months"]
    end_date = pd.Timestamp("2024-12-31")
    start_date = end_date - pd.DateOffset(months=months)
    # Uniform random seconds within the date range
    total_seconds = int((end_date - start_date).total_seconds())
    random_offsets = rng.integers(0, total_seconds, size=base_count)
    base_timestamps = start_date + pd.to_timedelta(random_offsets, unit="s")
    # Override hours with category-realistic distribution
    sampled_hours = _sample_hours(rng, category_groups, base_count)
    timestamps = base_timestamps.normalize() + pd.to_timedelta(sampled_hours, unit="h")
    # Add random minutes and seconds for realism
    timestamps += pd.to_timedelta(rng.integers(0, 60, size=base_count), unit="m")
    timestamps += pd.to_timedelta(rng.integers(0, 60, size=base_count), unit="s")

    # --- Amounts: lognormal per category ---
    amounts = np.zeros(base_count, dtype=float)
    for category, dist_params in amount_dists.items():
        mask = merchant_rows["category"].values == category
        count = mask.sum()
        if count == 0:
            continue
        raw = rng.lognormal(dist_params["mu"], dist_params["sigma"], size=count)
        # Round to 2 decimal places for currency realism
        amounts[mask] = np.round(raw, 2)

    # Handle any categories not in amount_distributions (shouldn't happen but safe)
    zero_mask = amounts == 0
    if zero_mask.any():
        amounts[zero_mask] = np.round(rng.lognormal(6.5, 0.8, size=zero_mask.sum()), 2)

    # --- Currency: 88% INR, 12% USD ---
    usd_rate = cfg["defect_rates"]["usd_currency"]
    is_usd = rng.random(base_count) < usd_rate
    currencies = np.where(is_usd, "USD", "INR")
    # Scale USD amounts down from INR-range lognormal
    usd_to_inr = fx_rates["USD"]
    amounts[is_usd] = np.round(amounts[is_usd] / usd_to_inr, 2)

    # --- Compute amount_inr for ground truth ---
    amount_inr = amounts.copy()
    amount_inr[is_usd] = np.round(amounts[is_usd] * usd_to_inr, 2)

    # --- City and country ---
    city_weights = np.array([5, 5, 5, 5, 4, 4, 3, 3, 2, 2, 2, 1, 2, 1, 1, 1], dtype=float)
    city_weights = city_weights[:len(cities)]
    city_weights /= city_weights.sum()
    city_indices = rng.choice(len(cities), size=base_count, p=city_weights)
    city_values = np.array(cities)[city_indices]
    # USD transactions are from US cities conceptually, but we keep Indian cities
    # and use country to distinguish — matches the spec's setup
    countries = np.where(is_usd, "US", "IN")

    # --- Channel: POS / ONLINE / ATM ---
    # Online-first categories lean toward ONLINE; physical stores lean POS
    online_heavy = {"Online Marketplace", "Streaming", "Food Delivery", "Travel Agency",
                    "DTH / Telecom", "Telecom", "Beauty & Personal Care"}
    channels = []
    for cat in merchant_rows["category"].values:
        if cat in online_heavy:
            ch = rng.choice(["ONLINE", "POS", "ATM"], p=[0.75, 0.20, 0.05])
        else:
            ch = rng.choice(["ONLINE", "POS", "ATM"], p=[0.30, 0.60, 0.10])
        channels.append(ch)
    channels = np.array(channels)

    # --- Status: APPROVED ~95%, DECLINED ~4%, REVERSED ~1% ---
    statuses = rng.choice(
        ["APPROVED", "DECLINED", "REVERSED"],
        size=base_count,
        p=[0.95, 0.04, 0.01],
    )

    # --- Transaction IDs ---
    # Generate deterministic UUIDs from two 64-bit halves
    hi = rng.integers(0, 2**63, size=base_count, dtype=np.int64).astype(np.uint64)
    lo = rng.integers(0, 2**63, size=base_count, dtype=np.int64).astype(np.uint64)
    txn_ids = [str(uuid.UUID(int=int((int(h) << 64) | int(l)), version=4)) for h, l in zip(hi, lo)]

    # --- Account assignment ---
    acct_indices = rng.integers(0, num_accounts, size=base_count)
    acct_values = np.array(account_ids)[acct_indices]

    # --- Assemble DataFrame ---
    df = pd.DataFrame({
        "transaction_id": txn_ids,
        "account_id": acct_values,
        "txn_timestamp": timestamps,
        "amount": amounts,
        "currency": currencies,
        "merchant_id": merchant_rows["merchant_id"].values,
        "merchant_name": merchant_rows["canonical_name"].values,
        "mcc": merchant_rows["mcc"].astype(str).values,
        "merchant_category": merchant_rows["category"].values,
        "city": city_values,
        "country": countries,
        "channel": channels,
        "status": statuses,
        "amount_inr": amount_inr,
    })

    log.info("Generated %d transactions across %d unique accounts, %d unique merchants",
             len(df), df["account_id"].nunique(), df["merchant_id"].nunique())
    log.info("Currency split: INR=%d (%.1f%%), USD=%d (%.1f%%)",
             (~is_usd).sum(), (~is_usd).mean() * 100,
             is_usd.sum(), is_usd.mean() * 100)
    log.info("Amount stats (INR-equiv): mean=%.2f, median=%.2f, max=%.2f",
             amount_inr.mean(), np.median(amount_inr), amount_inr.max())

    return df


def main() -> None:
    cfg = load_config()
    setup_logging(str(PROJECT_ROOT / cfg["paths"]["log_dir"]))
    log.info("Starting clean data generation")

    df = generate_transactions(cfg)

    output_path = PROJECT_ROOT / cfg["paths"]["truth_parquet"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    log.info("Wrote %d rows to %s", len(df), output_path)


if __name__ == "__main__":
    main()
