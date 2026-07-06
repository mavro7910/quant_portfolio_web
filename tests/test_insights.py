from core.insights import _summarize


def test_negative_event_stack_is_high_risk():
    result = _summarize(
        "ABC",
        {
            "earnings_days_left": 2,
            "eps_surprise_pct": -15,
            "target_upside_pct": -8,
            "rec_key": "HOLD",
        },
        [
            {"sentiment": -0.5},
            {"sentiment": -0.4},
        ],
    )
    assert result["risk_level"] == "높음"
    assert len(result["reasons"]) >= 3


def test_positive_opinions_do_not_create_risk():
    result = _summarize(
        "ABC",
        {
            "earnings_days_left": 30,
            "eps_surprise_pct": 12,
            "target_upside_pct": 20,
            "rec_key": "BUY",
        },
        [{"sentiment": 0.5}],
    )
    assert result["risk_level"] == "보통"
    assert result["confirmation"] == "긍정 확인"
