"""Merchant Resolution module (Phase 4).

Executes a 5-tier resolution cascade to identify the merchant from noisy
descriptor strings, utilizing regex normalization, exact matching, fuzzy
matching, and unsupervised clustering.
"""

import logging
import re
import pandas as pd
from rapidfuzz import process, fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import DBSCAN

from src.config import PROJECT_ROOT

log = logging.getLogger(__name__)


def _load_dictionary(cfg: dict) -> pd.DataFrame:
    """Load the merchant dictionary config."""
    path = PROJECT_ROOT / cfg["paths"]["merchant_dictionary"]
    df = pd.read_csv(path)
    # We want a mapping from upper-case alias to (merchant_id, canonical_name)
    df["alias"] = df["alias"].str.upper()
    return df


def _tier_0_normalize(descriptors: pd.Series) -> pd.Series:
    """Normalize and strip junk from descriptors (Tier 0)."""
    # 1. Uppercase and strip leading/trailing spaces
    s = descriptors.fillna("").astype(str).str.upper().str.strip()
    
    # 2. Strip unicode junk (keep ascii alphanumerics, spaces, basic punctuation)
    # The spec allows normal punctuation, but we want to strip invisible characters or weird emojis
    s = s.replace(r'[^\x00-\x7F]+', ' ', regex=True)
    
    # 3. Strip URL suffixes
    s = s.replace(r'\.(COM|IN|CO|NET)\b', ' ', regex=True)
    
    # 4. Strip aggregator prefixes
    s = s.replace(r'^(SQ|TST|PAYPAL|PP|SP|GOOGLE|APL)\s*\*+\s*', '', regex=True)
    
    # 5. Strip phone numbers (10 straight digits)
    s = s.replace(r'\b\d{10}\b', ' ', regex=True)
    
    # 6. Strip trailing state codes
    s = s.replace(r'\b(NY|CA|DL|HR|KA|MH)\s*$', ' ', regex=True)
    
    # 7. Strip trailing store nums
    s = s.replace(r'[#]?\s*\d{3,6}\s*$', ' ', regex=True)
    
    # 8. Collapse whitespace
    s = s.replace(r'\s+', ' ', regex=True).str.strip()
    
    return s


def resolve_merchants(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Run the 5-tier merchant resolution algorithm.
    
    Args:
        df: The input DataFrame.
        cfg: Pipeline configuration.
        
    Returns:
        DataFrame with new columns:
        - descriptor_clean
        - merchant_id
        - merchant_name
        - match_method
        - match_confidence
    """
    df = df.copy()
    dict_df = _load_dictionary(cfg)
    
    # Create mappings for quick lookup
    # Because an alias should map to exactly one merchant_id, we can just zip them.
    exact_lookup_id = dict(zip(dict_df["alias"], dict_df["merchant_id"]))
    exact_lookup_name = dict(zip(dict_df["alias"], dict_df["canonical_name"]))
    dictionary_aliases = dict_df["alias"].tolist()
    
    # Initialize output columns
    df["descriptor_clean"] = _tier_0_normalize(df["merchant_descriptor"])
    df["merchant_id"] = None
    df["merchant_name"] = None
    df["match_method"] = None
    df["match_confidence"] = 0.0
    
    # Helper to track what's left
    unresolved_mask = df["merchant_id"].isna() & (df["descriptor_clean"] != "")
    
    # -------------------------------------------------------------
    # TIER 1 — EXACT MATCH
    # -------------------------------------------------------------
    clean_series = df.loc[unresolved_mask, "descriptor_clean"]
    exact_matches = clean_series.map(exact_lookup_id)
    
    tier1_mask = exact_matches.notna()
    if tier1_mask.any():
        resolved_indices = clean_series[tier1_mask].index
        df.loc[resolved_indices, "merchant_id"] = exact_matches[tier1_mask]
        df.loc[resolved_indices, "merchant_name"] = clean_series[tier1_mask].map(exact_lookup_name)
        df.loc[resolved_indices, "match_method"] = "exact"
        df.loc[resolved_indices, "match_confidence"] = 1.00
        
    unresolved_mask = df["merchant_id"].isna() & (df["descriptor_clean"] != "")
    log.info("Tier 1 (Exact): Resolved %d rows. %d remaining.", tier1_mask.sum(), unresolved_mask.sum())
    
    # -------------------------------------------------------------
    # TIER 2 — FUZZY MATCH
    # -------------------------------------------------------------
    if unresolved_mask.any():
        threshold = cfg.get("fuzzy_threshold", 88)
        unique_unresolved = df.loc[unresolved_mask, "descriptor_clean"].unique()
        
        fuzzy_id_map = {}
        fuzzy_name_map = {}
        fuzzy_score_map = {}
        
        for desc in unique_unresolved:
            # We use QRatio/WRatio for scoring
            match = process.extractOne(desc, dictionary_aliases, scorer=fuzz.token_set_ratio)
            if match:
                best_alias, score, _ = match
                if score >= threshold:
                    fuzzy_id_map[desc] = exact_lookup_id[best_alias]
                    fuzzy_name_map[desc] = exact_lookup_name[best_alias]
                    fuzzy_score_map[desc] = score / 100.0
                    
        # Apply fuzzy matches
        clean_series = df.loc[unresolved_mask, "descriptor_clean"]
        fuzzy_ids = clean_series.map(fuzzy_id_map)
        
        tier2_mask = fuzzy_ids.notna()
        if tier2_mask.any():
            resolved_indices = clean_series[tier2_mask].index
            df.loc[resolved_indices, "merchant_id"] = fuzzy_ids[tier2_mask]
            df.loc[resolved_indices, "merchant_name"] = clean_series[tier2_mask].map(fuzzy_name_map)
            df.loc[resolved_indices, "match_method"] = "fuzzy"
            df.loc[resolved_indices, "match_confidence"] = clean_series[tier2_mask].map(fuzzy_score_map)
            
    unresolved_mask = df["merchant_id"].isna() & (df["descriptor_clean"] != "")
    log.info("Tier 2 (Fuzzy): Resolved %d rows. %d remaining.", tier2_mask.sum() if 'tier2_mask' in locals() else 0, unresolved_mask.sum())
    
    # -------------------------------------------------------------
    # TIER 3 — CLUSTER
    # -------------------------------------------------------------
    if unresolved_mask.sum() >= 3:  # Need at least 3 for DBSCAN default min_samples
        unique_unresolved = df.loc[unresolved_mask, "descriptor_clean"].unique()
        
        if len(unique_unresolved) >= 3:
            eps = cfg.get("dbscan_eps", 0.35)
            
            vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2,4))
            X = vectorizer.fit_transform(unique_unresolved)
            
            clustering = DBSCAN(eps=eps, metric='cosine', min_samples=3)
            labels = clustering.fit_predict(X)
            
            cluster_id_map = {}
            cluster_name_map = {}
            
            # Map unique strings to their cluster labels
            for desc, label in zip(unique_unresolved, labels):
                if label != -1:  # -1 is noise/singleton
                    cluster_id = f"CLUSTER_{label}"
                    cluster_id_map[desc] = cluster_id
                    
            # Identify the representative name for each cluster
            # (Most frequent member across the dataset, not just unique strings)
            # Actually, to find the most frequent member of the cluster in the DATASET:
            if cluster_id_map:
                cluster_series = df.loc[unresolved_mask, "descriptor_clean"].map(cluster_id_map)
                grouped = df.loc[unresolved_mask].groupby(cluster_series)["descriptor_clean"]
                for c_id, group in grouped:
                    # Representative is the mode (most common string) in that cluster
                    rep = group.mode().iloc[0]
                    cluster_name_map[c_id] = rep
                    
                # Apply clustering matches
                clean_series = df.loc[unresolved_mask, "descriptor_clean"]
                tier3_ids = clean_series.map(cluster_id_map)
                tier3_mask = tier3_ids.notna()
                
                if tier3_mask.any():
                    resolved_indices = clean_series[tier3_mask].index
                    df.loc[resolved_indices, "merchant_id"] = tier3_ids[tier3_mask]
                    df.loc[resolved_indices, "merchant_name"] = tier3_ids[tier3_mask].map(cluster_name_map)
                    df.loc[resolved_indices, "match_method"] = "cluster"
                    df.loc[resolved_indices, "match_confidence"] = 0.50
                    
    unresolved_mask = df["merchant_id"].isna() & (df["descriptor_clean"] != "")
    log.info("Tier 3 (Cluster): Resolved %d rows. %d remaining.", tier3_mask.sum() if 'tier3_mask' in locals() and 'tier3_mask' in vars() else 0, unresolved_mask.sum())
    
    # -------------------------------------------------------------
    # TIER 4 — UNRESOLVED
    # -------------------------------------------------------------
    if unresolved_mask.any():
        df.loc[unresolved_mask, "match_method"] = "unresolved"
        df.loc[unresolved_mask, "match_confidence"] = 0.00
        # For singletons, we can just use their own clean descriptor as name, and no ID.
        df.loc[unresolved_mask, "merchant_name"] = df.loc[unresolved_mask, "descriptor_clean"]
        
    log.info("Tier 4 (Unresolved): %d rows.", unresolved_mask.sum())
    
    return df
