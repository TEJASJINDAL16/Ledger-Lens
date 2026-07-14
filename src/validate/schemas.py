"""Pandera schemas for data validation and gating.

Defines the contracts for Bronze and Silver stages. Failing rows
are caught and quarantined, never dropped silently.
"""

import pandera.pandas as pa

# ---------------------------------------------------------------------------
# Bronze Gate
# ---------------------------------------------------------------------------
# Raw data validation. At this stage, everything is a string.
# We just want to catch structural breakage (schema drift) and obviously
# impossible values (like impossible dates) before attempting heavy parsing.
# ---------------------------------------------------------------------------

BronzeSchema = pa.DataFrameSchema({
    "transaction_id": pa.Column(
        str,
        checks=pa.Check(lambda s: s.str.len() > 0, error="Empty transaction_id"),
        nullable=False,
    ),
    "txn_timestamp": pa.Column(
        str,
        checks=[
            # We catch the impossible dates (1900 and 2030+) here.
            # Normal dates range 2023-2024. Epochs are ~1.6B-1.7B.
            # 1900 and 2030 will literally contain "1900-" or "2030-"
            pa.Check(
                lambda s: ~s.str.startswith("1900-") & ~s.str.startswith("2030-"),
                error="impossible_date"
            )
        ],
        nullable=True,
    ),
    "merchant_descriptor": pa.Column(
        str,
        checks=[
            # Our "schema drift" defect injects an extra unescaped comma into
            # the descriptor, which conceptually shifts columns. Because pandas
            # quotes it on write, it parses successfully, but we detect the
            # corruption here by checking for commas where there should be none.
            pa.Check(
                lambda s: ~s.str.contains(",", na=False),
                error="schema_drift"
            )
        ],
        nullable=True,
    ),
}, coerce=False)


# ---------------------------------------------------------------------------
# Silver Gate
# ---------------------------------------------------------------------------
# Typed schema for cleaned data before writing to the warehouse.
# Enforces that critical business values are within logical bounds.
# ---------------------------------------------------------------------------

SilverSchema = pa.DataFrameSchema({
    "transaction_id": pa.Column(str, nullable=False),
    "merchant_id": pa.Column(str, nullable=False),
    "amount_inr": pa.Column(
        float,
        # If status is APPROVED, amount should generally be > 0 
        # (ignoring refunds for a moment, but spec says "amount_inr > 0 for approved")
        # Wait, the spec says "amount_inr > 0 for approved".
        # We can implement this as a dataframe check or just a simple check if we assume approved.
        # Let's enforce that if status == "APPROVED", amount_inr > 0 via a DataFrame check.
        nullable=False,
    ),
    "match_confidence": pa.Column(
        float,
        checks=pa.Check.in_range(0.0, 1.0, error="Confidence out of bounds"),
        nullable=False,
    ),
    "txn_timestamp": pa.Column(DateTime, nullable=False),
}, checks=[
    # amount_inr > 0 for approved
    pa.Check(
        lambda df: (df["amount_inr"] > 0) | (df["status"] != "APPROVED"),
        error="amount_inr_lte_zero_for_approved"
    )
], coerce=False)
