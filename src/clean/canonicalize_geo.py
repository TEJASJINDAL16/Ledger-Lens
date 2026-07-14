"""Geo canonicalization module.

Cleans up exploded city variants (e.g., 'Gurugram', 'GGN', 'gurgaon') by
performing an exact lookup against config/city_canonical.csv, followed by 
a fuzzy fallback matching for remaining variants.
"""

import logging
import pandas as pd
from rapidfuzz import process, fuzz

from src.config import PROJECT_ROOT

log = logging.getLogger(__name__)


def _load_canonical_cities(cfg: dict) -> list[str]:
    """Load canonical city names."""
    path = PROJECT_ROOT / cfg["paths"]["city_canonical"]
    df = pd.read_csv(path)
    return df["canonical_city"].unique().tolist()


def canonicalize_geo(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Canonicalize the 'city' column.
    
    Args:
        df: The DataFrame.
        cfg: Pipeline configuration.
        
    Returns:
        DataFrame with new column 'city_canonical'.
    """
    df = df.copy()
    
    # Extract canonical cities
    canonical_cities = _load_canonical_cities(cfg)
    # create a fast lookup for exact matches (case-insensitive)
    exact_lookup = {c.lower(): c for c in canonical_cities}
    
    # 1. Clean up original city strings
    raw_cities = df["city"].fillna("").astype(str)
    # Upper-case for fuzzy matching, lower-case for exact lookup
    cleaned_lower = raw_cities.str.lower().str.strip()
    
    # 2. Exact Matches First (Fast)
    # map returns NaN if not found
    exact_matches = cleaned_lower.map(exact_lookup)
    
    # 3. Fuzzy Fallback (Slow, only on unique unmapped strings to save time)
    unmapped_mask = exact_matches.isna() & (cleaned_lower != "")
    unique_unmapped = cleaned_lower[unmapped_mask].unique()
    
    log.info("Canonicalizing geo: found %d exact matches. Attempting fuzzy matching on %d unique variants...", 
             (~unmapped_mask).sum(), len(unique_unmapped))
             
    fuzzy_lookup = {}
    threshold = 80  # Good threshold for city names
    
    for city_variant in unique_unmapped:
        # Extract best match from canonical list using RapidFuzz
        # We pass canonical_cities (original case) but match against city_variant.lower()
        # process.extractOne uses scorer=fuzz.WRatio by default, which is good.
        # We'll use fuzz.QRatio for speed and simplicity.
        match = process.extractOne(
            city_variant, 
            canonical_cities, 
            processor=lambda x: x.lower() if isinstance(x, str) else x,
            scorer=fuzz.QRatio
        )
        
        if match:
            best_city, score, _ = match
            if score >= threshold:
                fuzzy_lookup[city_variant] = best_city
            
    # Apply fuzzy matches
    fuzzy_matches = cleaned_lower.map(fuzzy_lookup)
    
    # 4. Combine results
    # Priority: Exact -> Fuzzy -> Original (if no match)
    final_city = exact_matches.combine_first(fuzzy_matches).combine_first(raw_cities)
    
    df["city_canonical"] = final_city
    
    return df
