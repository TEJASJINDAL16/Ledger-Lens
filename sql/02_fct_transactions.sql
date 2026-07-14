-- -----------------------------------------------------------------------------
-- Phase 6: Gold Fact Table
-- -----------------------------------------------------------------------------
-- Creates the central fact table for the Star Schema.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TABLE fct_transactions AS
SELECT
    transaction_id,
    account_id,
    merchant_id,
    CAST(txn_timestamp AS DATE) AS date_key,
    txn_timestamp,
    
    amount_inr,
    amount_original,
    currency_original,
    
    merchant_descriptor AS raw_descriptor,
    descriptor_clean,
    
    channel,
    status,
    city_canonical,
    country,
    
    match_method,
    match_confidence,
    mcc_imputed_flag,
    is_near_duplicate,
    is_outlier
FROM stg_transactions;
