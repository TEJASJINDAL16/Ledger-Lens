"""Tests for the Merchant Resolver module."""

import pandas as pd
import pytest

from src.resolve.merchant_resolver import _tier_0_normalize


def test_tier_0_normalize_regexes():
    """Verify that Tier 0 normalization strips exactly what it should."""
    raw_descriptors = [
        "SQ *BLUE BOTL COF 4471 NY",      # Square prefix, truncation, store#, state
        "TST* BLUE BOTTLE - GURGAON",     # Toast prefix
        "PAYPAL *BLUEBOTTLE",             # PayPal prefix
        "BLUE BOTTLE COFFEE  #0231",      # Store number
        "BLUEBOTTLECOFFEE.COM",           # URL form
        "blue bottle coffee gurgaon",     # Lowercase
        "BLUE BOTTLE COFFEE 8001234567",  # Phone number
        "UBER EATS",                      # Normal
    ]
    
    series = pd.Series(raw_descriptors)
    cleaned = _tier_0_normalize(series)
    
    # Expected after normalization (all caps, prefixes/suffixes stripped)
    # Note: "4471 NY" gets stripped by store# and state codes, but wait:
    # "4471" is stripped by store_num (\d{3,6}), "NY" stripped by state code.
    # Actually, if we string replace, order matters. Let's see how our regex evaluates.
    
    # SQ *BLUE BOTL COF 4471 NY
    # - SQ * stripped
    # - NY stripped at end -> BLUE BOTL COF 4471
    # - 4471 stripped at end -> BLUE BOTL COF
    assert cleaned.iloc[0] == "BLUE BOTL COF"
    
    # TST* BLUE BOTTLE - GURGAON
    # - TST* stripped -> BLUE BOTTLE - GURGAON
    assert cleaned.iloc[1] == "BLUE BOTTLE - GURGAON"
    
    # PAYPAL *BLUEBOTTLE
    assert cleaned.iloc[2] == "BLUEBOTTLE"
    
    # BLUE BOTTLE COFFEE  #0231
    assert cleaned.iloc[3] == "BLUE BOTTLE COFFEE"
    
    # BLUEBOTTLECOFFEE.COM
    assert cleaned.iloc[4] == "BLUEBOTTLECOFFEE"
    
    # blue bottle coffee gurgaon -> uppercase
    assert cleaned.iloc[5] == "BLUE BOTTLE COFFEE GURGAON"
    
    # BLUE BOTTLE COFFEE 8001234567 -> 10 digit phone stripped
    assert cleaned.iloc[6] == "BLUE BOTTLE COFFEE"
    
    # UBER EATS
    assert cleaned.iloc[7] == "UBER EATS"
