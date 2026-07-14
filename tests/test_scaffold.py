def test_scaffold_exists():
    """Verify the repo structure exists. Replaced by real tests in later phases."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "config" / "pipeline.yaml").exists()
    assert (root / "config" / "merchant_dictionary.csv").exists()
    assert (root / "config" / "city_canonical.csv").exists()
    assert (root / "config" / "mcc_map.csv").exists()
    assert (root / "config" / "fx_rates.csv").exists()
