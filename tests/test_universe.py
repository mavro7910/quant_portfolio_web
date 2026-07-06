from core import universe


def test_quote_filter_excludes_preferred_and_duplicate_berkshire_class():
    assert universe._valid_quote({"symbol": "TSM", "quoteType": "EQUITY"})
    assert not universe._valid_quote({"symbol": "JPM-PC", "quoteType": "EQUITY"})
    assert not universe._valid_quote({"symbol": "BRK-A", "quoteType": "EQUITY"})
    assert not universe._valid_quote({"symbol": "SPY", "quoteType": "ETF"})


def test_fallback_is_exactly_100_and_unique():
    assert len(universe.FALLBACK_TOP100) == 100
    assert len(set(universe.FALLBACK_TOP100)) == 100

