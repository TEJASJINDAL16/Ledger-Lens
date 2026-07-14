-- -----------------------------------------------------------------------------
-- Phase 6: Gold Dimensions
-- -----------------------------------------------------------------------------
-- Creates the dimension tables for the Star Schema.
-- Input: stg_transactions (view of silver.parquet)
-- -----------------------------------------------------------------------------

-- 1. Date Dimension
CREATE OR REPLACE TABLE dim_date AS
SELECT
    DISTINCT CAST(txn_timestamp AS DATE) AS date_key,
    EXTRACT(YEAR FROM txn_timestamp) AS year,
    EXTRACT(MONTH FROM txn_timestamp) AS month,
    EXTRACT(DAY FROM txn_timestamp) AS day,
    EXTRACT(DOW FROM txn_timestamp) AS day_of_week
FROM stg_transactions
WHERE txn_timestamp IS NOT NULL;

-- 2. Account Dimension
CREATE OR REPLACE TABLE dim_account AS
SELECT
    DISTINCT account_id
FROM stg_transactions
WHERE account_id IS NOT NULL;

-- 3. Merchant Dimension
-- We enrich the merchant dimension with the category from the MCC map
CREATE OR REPLACE TABLE dim_merchant AS
WITH unique_merchants AS (
    SELECT DISTINCT
        merchant_id,
        merchant_name,
        mcc
    FROM stg_transactions
    WHERE merchant_id IS NOT NULL
)
SELECT 
    m.merchant_id,
    m.merchant_name,
    m.mcc,
    COALESCE(map.category, 'Unclassified') AS merchant_category,
    COALESCE(map.category_group, 'Unclassified') AS category_group
FROM unique_merchants m
LEFT JOIN read_csv_auto('config/mcc_map.csv') map 
    ON CAST(m.mcc AS VARCHAR) = CAST(map.mcc AS VARCHAR);
