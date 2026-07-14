-- -----------------------------------------------------------------------------
-- Phase 6: Gold Insights
-- -----------------------------------------------------------------------------
-- Creates the 4 required analytical views.
-- -----------------------------------------------------------------------------

-- 1. Top 10 merchants by spend (Before vs After)
-- The money shot: compares the fragmentation of raw descriptors vs the unified truth
CREATE OR REPLACE VIEW v_top_merchants_before_after AS
WITH raw_top AS (
    SELECT 
        raw_descriptor AS merchant_identity,
        SUM(amount_inr) AS total_spend,
        ROW_NUMBER() OVER (ORDER BY SUM(amount_inr) DESC) AS rank,
        'Before (Raw Descriptor)' AS state
    FROM fct_transactions
    WHERE status = 'APPROVED' AND NOT is_outlier
    GROUP BY raw_descriptor
    ORDER BY total_spend DESC
    LIMIT 10
),
clean_top AS (
    SELECT 
        m.merchant_name AS merchant_identity,
        SUM(f.amount_inr) AS total_spend,
        ROW_NUMBER() OVER (ORDER BY SUM(f.amount_inr) DESC) AS rank,
        'After (Resolved Identity)' AS state
    FROM fct_transactions f
    JOIN dim_merchant m ON f.merchant_id = m.merchant_id
    WHERE f.status = 'APPROVED' AND NOT f.is_outlier
    GROUP BY m.merchant_name
    ORDER BY total_spend DESC
    LIMIT 10
)
SELECT * FROM raw_top
UNION ALL
SELECT * FROM clean_top
ORDER BY state, rank;

-- 2. Category spend mix (Imputed vs Explicit)
-- Honesty as a feature: shows how much of our category insights rely on imputation
CREATE OR REPLACE VIEW v_category_spend_mix AS
SELECT 
    m.merchant_category,
    f.mcc_imputed_flag,
    COUNT(*) AS transaction_count,
    SUM(f.amount_inr) AS total_spend_inr
FROM fct_transactions f
JOIN dim_merchant m ON f.merchant_id = m.merchant_id
WHERE f.status = 'APPROVED' AND NOT f.is_outlier
GROUP BY m.merchant_category, f.mcc_imputed_flag
ORDER BY m.merchant_category, f.mcc_imputed_flag;

-- 3. Duplicate Exposure
-- The total ₹ value sitting in flagged near-duplicates (which we retained)
CREATE OR REPLACE VIEW v_duplicate_exposure AS
SELECT 
    COUNT(*) AS near_duplicate_txn_count,
    SUM(amount_inr) AS total_exposure_inr
FROM fct_transactions
WHERE is_near_duplicate = TRUE AND status = 'APPROVED';

-- 4. Data Health by Source
-- SLA/controls view: quality score by channel and month
CREATE OR REPLACE VIEW v_data_health_by_source AS
SELECT 
    f.channel,
    d.year,
    d.month,
    COUNT(*) AS total_txns,
    
    -- Quality dimensions (what % had issues?)
    SUM(CASE WHEN f.match_method = 'unresolved' THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pct_unresolved_merchants,
    SUM(CASE WHEN f.mcc_imputed_flag THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pct_imputed_mcc,
    SUM(CASE WHEN f.is_near_duplicate THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS pct_near_duplicates,
    
    -- Overall "health" score (100 = perfect, penalties for issues)
    -- This is a simple heuristic SLA metric for upstream feeds
    100.0 - (
        SUM(CASE WHEN f.match_method = 'unresolved' THEN 1 ELSE 0 END) * 0.5 + 
        SUM(CASE WHEN f.mcc_imputed_flag THEN 1 ELSE 0 END) * 0.2
    ) * 100.0 / COUNT(*) AS data_health_score
    
FROM fct_transactions f
JOIN dim_date d ON f.date_key = d.date_key
GROUP BY f.channel, d.year, d.month
ORDER BY d.year, d.month, f.channel;
