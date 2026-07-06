import numpy as np
import pandas as pd
import pytest

import core.strategy as strategy


def synthetic_prices(columns, periods=320):
    dates = pd.bdate_range("2024-01-02", periods=periods)
    values = {}
    for i, ticker in enumerate(columns):
        trend = 0.0003 + i * 0.00015
        cycle = np.sin(np.arange(periods) / (9 + i)) * 0.003
        values[ticker] = 100 * np.exp(np.cumsum(trend + cycle))
    return pd.DataFrame(values, index=dates)


def test_normalize_with_cap_enforces_cap_and_sum():
    raw = pd.Series({"A": 100.0, "B": 2.0, "C": 1.0, "D": 0.5, "E": 0.1})
    weights = strategy._normalize_with_cap(raw, 0.25)
    assert weights.sum() == pytest.approx(1.0)
    assert weights.max() <= 0.25 + 1e-12


def test_normalize_with_cap_rejects_impossible_portfolio():
    with pytest.raises(ValueError):
        strategy._normalize_with_cap(pd.Series({"A": 1.0, "B": 1.0}), 0.25)


def test_strategy_scores_are_auditable():
    prices = synthetic_prices(list("ABCDEF"))
    scores, is_bull = strategy.strategy_scores(prices, prices["F"])
    assert {
        "momentum_12_1", "momentum_rank",
        "continuity", "continuity_rank",
        "residual_vol", "low_residual_vol_rank",
        "alpha", "rank", "heat", "heat_state",
    } <= set(scores.columns)
    assert sorted(scores["rank"].tolist()) == list(range(1, 7))
    assert scores["heat"].between(0, 1).all()
    expected = (
        0.65 * scores["momentum_rank"]
        + 0.20 * scores["continuity_rank"]
        + 0.15 * scores["low_residual_vol_rank"]
    )
    assert np.allclose(scores["alpha"], expected)
    assert isinstance(is_bull, bool)


def test_strategy_scores_exclude_incomplete_formation_history():
    prices = synthetic_prices(list("ABCDEF"))
    prices["NEW"] = prices["A"]
    prices.loc[prices.index[:100], "NEW"] = np.nan
    scores, _ = strategy.strategy_scores(prices, prices["F"])
    assert "NEW" not in scores.index


def test_buy_plan_uses_independent_universe_and_shortfalls(monkeypatch):
    tickers = list("ABCDEF") + ["HELD"]
    prices = synthetic_prices(tickers)
    qqq = synthetic_prices(["QQQ"])["QQQ"]
    fx = pd.Series(1_400.0, index=prices.index)

    def fake_fetch(requested, extra=None, **kwargs):
        return {
            "prices": prices.reindex(columns=requested),
            "QQQ": qqq,
            "USDKRW=X": fx,
        }

    monkeypatch.setattr(strategy, "fetch_prices", fake_fetch)
    result = strategy.buy_recommendation(
        holdings={"HELD": 10.0, "A": 100.0},
        budget_krw=250_000,
        top_n=5,
        universe_tickers=list("ABCDEF"),
        locked_selection=["A", "B", "C", "D", "E"],
    )

    assert result["tickers"] == ["A", "B", "C", "D", "E"]
    assert "HELD" not in result["scores"].index
    assert result["weights"].sum() == pytest.approx(1.0)
    assert result["buy_krw"].sum() == pytest.approx(250_000)
    assert result["budget_krw"] == pytest.approx(250_000)
    assert result["buy_krw"]["A"] == pytest.approx(0.0)
    assert result["selection_locked"] is True


def test_backtest_signal_precedes_execution(monkeypatch):
    prices = synthetic_prices(list("ABCDE"), periods=420)
    qqq = synthetic_prices(["QQQ"], periods=420)["QQQ"]
    fx = pd.Series(1_400.0, index=prices.index)
    benchmark = synthetic_prices(["SPY"], periods=420)["SPY"]
    seen = []
    original = strategy.target_weights

    def fake_fetch(requested, extra=None, **kwargs):
        return {
            "prices": prices.reindex(columns=requested),
            "QQQ": qqq,
            "USDKRW=X": fx,
            "SPY": benchmark,
        }

    def recording_target(df, qqq_series, **kwargs):
        seen.append(df.index[-1])
        return original(df, qqq_series, **kwargs)

    monkeypatch.setattr(strategy, "fetch_prices", fake_fetch)
    monkeypatch.setattr(strategy, "target_weights", recording_target)
    sim_start = prices.index[300].strftime("%Y-%m-%d")
    result = strategy.run_backtest(
        list("ABCDE"),
        weekly_budget=100_000,
        benchmark_tickers=["SPY"],
        mcap_preset="factor",
        top_n=5,
        sim_start=sim_start,
        end=(prices.index[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
    )

    assert seen
    assert all(signal_date < execution_date for signal_date, execution_date in zip(seen, result.index))
    assert "QPM_Return" in result.columns
    assert "SPY_Return" in result.columns
