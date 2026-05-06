"""
utils/ai_client.py

AI 시그널 분석 — 뉴스 + 애널리스트 데이터 기반
- 퀀트 컨텍스트 제거 (별도 탭에서 담당)
- 뉴스 본문 품질 강화 (Marketaux snippet 400자)
- 애널리스트 데이터 다중 소스 수집
- 스마트 캐시 유지
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import streamlit as st


# ─────────────────────────────────────────────
# API 키 관리
# ─────────────────────────────────────────────

def get_api_key() -> str | None:
    return st.session_state.get("gemini_api_key") or None

def set_api_key(key: str):
    st.session_state["gemini_api_key"] = key.strip()

def clear_api_key():
    st.session_state.pop("gemini_api_key", None)

def has_api_key() -> bool:
    k = get_api_key()
    return bool(k and len(k) > 10)

def get_finnhub_key() -> str | None:
    return st.session_state.get("finnhub_api_key") or None

def set_finnhub_key(key: str):
    st.session_state["finnhub_api_key"] = key.strip()

def clear_finnhub_key():
    st.session_state.pop("finnhub_api_key", None)

def has_finnhub_key() -> bool:
    k = get_finnhub_key()
    return bool(k and len(k) > 5)

def get_marketaux_key() -> str | None:
    return st.session_state.get("marketaux_api_key") or None

def set_marketaux_key(key: str):
    st.session_state["marketaux_api_key"] = key.strip()

def clear_marketaux_key():
    st.session_state.pop("marketaux_api_key", None)

def has_marketaux_key() -> bool:
    k = get_marketaux_key()
    return bool(k and len(k) > 5)


# ─────────────────────────────────────────────
# 키 검증
# ─────────────────────────────────────────────

def validate_api_key(api_key: str) -> tuple[bool, str | None]:
    key = api_key.strip()
    if not key.startswith("AIza"):
        return False, "Gemini 키는 'AIza'로 시작해야 합니다."
    if len(key) < 35:
        return False, "키가 너무 짧습니다."
    return True, None

def validate_finnhub_key(api_key: str) -> tuple[bool, str | None]:
    key = api_key.strip()
    if len(key) < 10:
        return False, "키가 너무 짧습니다."
    return True, None

def validate_marketaux_key(api_key: str) -> tuple[bool, str | None]:
    key = api_key.strip()
    if len(key) < 10:
        return False, "키가 너무 짧습니다."
    return True, None


# ─────────────────────────────────────────────
# 애널리스트 데이터 수집
# ─────────────────────────────────────────────

def fetch_analyst_data(tickers: list[str]) -> dict[str, dict]:
    """
    투자의견, 목표주가, 어닝 일정, EPS 서프라이즈 수집.
    info → analyst_price_targets → recommendations_summary 순으로 fallback.
    """
    import yfinance as yf
    import pandas as pd

    result = {}
    for t in tickers:
        try:
            tk   = yf.Ticker(t)
            data = {}

            # ── ① info ──────────────────────────────────────────
            try:
                info = tk.info or {}
                data["rec_key"]     = (info.get("recommendationKey") or "").upper() or None
                data["rec_mean"]    = info.get("recommendationMean")
                data["n_analysts"]  = info.get("numberOfAnalystOpinions")
                data["target_mean"] = info.get("targetMeanPrice")
                data["target_high"] = info.get("targetHighPrice")
                data["target_low"]  = info.get("targetLowPrice")
                data["current_price"] = (
                    info.get("currentPrice")
                    or info.get("regularMarketPrice")
                    or info.get("previousClose")
                )
            except Exception:
                pass

            # ── ② fast_info 현재가 보완 ─────────────────────────
            if not data.get("current_price"):
                try:
                    fi = tk.fast_info
                    data["current_price"] = (
                        getattr(fi, "last_price", None)
                        or getattr(fi, "regular_market_price", None)
                        or getattr(fi, "previous_close", None)
                    )
                except Exception:
                    pass

            # ── ③ analyst_price_targets 목표주가 보완 ────────────
            if not data.get("target_mean"):
                try:
                    apt = tk.analyst_price_targets
                    if apt is not None:
                        if isinstance(apt, pd.DataFrame) and not apt.empty:
                            cols_lower = [c.lower() for c in apt.columns]
                            row = apt.iloc[-1]
                            for key, candidates in [
                                ("target_mean", ["mean"]),
                                ("target_high", ["high"]),
                                ("target_low",  ["low"]),
                            ]:
                                for c in candidates:
                                    if c in cols_lower:
                                        val = row[apt.columns[cols_lower.index(c)]]
                                        if val and float(val) > 0:
                                            data[key] = float(val)
                                        break
                        elif isinstance(apt, pd.Series):
                            for key, candidates in [
                                ("target_mean", ["mean", "targetMeanPrice"]),
                                ("target_high", ["high", "targetHighPrice"]),
                                ("target_low",  ["low",  "targetLowPrice"]),
                            ]:
                                for c in candidates:
                                    val = apt.get(c)
                                    if val and float(val) > 0:
                                        data[key] = float(val)
                                        break
                except Exception:
                    pass

            # ── ④ recommendations_summary 투자의견 보완 ──────────
            if not data.get("rec_key"):
                try:
                    rs = tk.recommendations_summary
                    if rs is not None and not rs.empty:
                        row = rs.iloc[0]
                        strong_buy  = int(row.get("strongBuy",  0) or 0)
                        buy         = int(row.get("buy",        0) or 0)
                        hold        = int(row.get("hold",       0) or 0)
                        sell        = int(row.get("sell",       0) or 0)
                        strong_sell = int(row.get("strongSell", 0) or 0)
                        total = strong_buy + buy + hold + sell + strong_sell
                        if total > 0:
                            data["n_analysts"] = total
                            if strong_buy / total > 0.4:
                                data["rec_key"] = "STRONG_BUY"
                            elif (strong_buy + buy) / total > 0.5:
                                data["rec_key"] = "BUY"
                            elif (sell + strong_sell) / total > 0.4:
                                data["rec_key"] = "SELL"
                            else:
                                data["rec_key"] = "HOLD"
                except Exception:
                    pass

            # ── ⑤ 상승여력 계산 ─────────────────────────────────
            curr  = data.get("current_price")
            tmean = data.get("target_mean")
            if curr and tmean and float(curr) > 0:
                data["target_upside_pct"] = round((float(tmean) / float(curr) - 1) * 100, 1)

            # ── ⑥ 어닝 발표일 ───────────────────────────────────
            try:
                cal = tk.calendar
                ed  = None
                if cal is not None:
                    if isinstance(cal, dict):
                        ed = cal.get("Earnings Date")
                        if isinstance(ed, list) and ed:
                            ed = ed[0]
                    elif isinstance(cal, pd.DataFrame) and not cal.empty:
                        if "Earnings Date" in cal.index:
                            ed = cal.loc["Earnings Date"].iloc[0]
                        elif "Earnings Date" in cal.columns:
                            ed = cal["Earnings Date"].iloc[0]

                if ed is not None:
                    ed_ts     = pd.Timestamp(ed)
                    ed_date   = ed_ts.date()
                    from datetime import date as date_cls
                    today_d   = date_cls.today()
                    days_left = (ed_date - today_d).days
                    if -30 <= days_left <= 90:
                        data["earnings_date"]      = ed_date.isoformat()
                        data["earnings_days_left"] = days_left
            except Exception:
                pass

            # ── ⑦ EPS 서프라이즈 ────────────────────────────────
            try:
                ed_df = tk.earnings_dates
                if ed_df is not None and not ed_df.empty:
                    now_ts = pd.Timestamp.now(tz="UTC")
                    try:
                        past = ed_df[ed_df.index < now_ts]
                    except TypeError:
                        past = ed_df[ed_df.index < pd.Timestamp.now()]
                    surp_col = next((c for c in past.columns if "surprise" in c.lower()), None)
                    if surp_col:
                        clean = past.dropna(subset=[surp_col])
                        if not clean.empty:
                            data["eps_surprise_pct"] = round(float(clean[surp_col].iloc[0]), 1)
            except Exception:
                pass

            # earnings_history fallback
            if data.get("eps_surprise_pct") is None:
                try:
                    eh = tk.earnings_history
                    if eh is not None and not eh.empty:
                        surp_col = next((c for c in eh.columns if "surprise" in c.lower() or "percent" in c.lower()), None)
                        if surp_col is None and {"epsDifference", "epsEstimate"}.issubset(eh.columns):
                            row = eh.dropna(subset=["epsDifference", "epsEstimate"]).iloc[0]
                            est = float(row["epsEstimate"])
                            if est != 0:
                                data["eps_surprise_pct"] = round(float(row["epsDifference"]) / abs(est) * 100, 1)
                        elif surp_col:
                            clean = eh.dropna(subset=[surp_col])
                            if not clean.empty:
                                val = float(clean[surp_col].iloc[0])
                                if abs(val) < 5:
                                    val = round(val * 100, 1)
                                data["eps_surprise_pct"] = round(val, 1)
                except Exception:
                    pass

            result[t] = {
                "rec_key":            data.get("rec_key"),
                "rec_mean":           round(data["rec_mean"], 1) if data.get("rec_mean") else None,
                "n_analysts":         int(data["n_analysts"]) if data.get("n_analysts") else None,
                "current_price":      round(float(data["current_price"]), 2) if data.get("current_price") else None,
                "target_mean":        round(float(data["target_mean"]), 2) if data.get("target_mean") else None,
                "target_high":        round(float(data["target_high"]), 2) if data.get("target_high") else None,
                "target_low":         round(float(data["target_low"]), 2) if data.get("target_low") else None,
                "target_upside_pct":  data.get("target_upside_pct"),
                "earnings_date":      data.get("earnings_date"),
                "earnings_days_left": data.get("earnings_days_left"),
                "eps_surprise_pct":   data.get("eps_surprise_pct"),
            }

        except Exception:
            result[t] = {}

    return result


# ─────────────────────────────────────────────
# 뉴스 수집
# ─────────────────────────────────────────────

def _fetch_finnhub(ticker: str, finnhub_key: str) -> tuple[list[dict], float | None]:
    import requests
    headers    = {"X-Finnhub-Token": finnhub_key}
    articles   = []
    change_pct = None

    try:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker}, headers=headers, timeout=5,
        )
        d    = r.json()
        curr = d.get("c", 0)
        prev = d.get("pc", 0)
        if prev and prev > 0:
            change_pct = round((curr - prev) / prev * 100, 2)
    except Exception:
        pass

    try:
        today     = date.today()
        from_date = (today - timedelta(days=3)).isoformat()
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": from_date, "to": today.isoformat()},
            headers=headers, timeout=5,
        )
        for item in r.json()[:3]:
            headline = item.get("headline", "")
            summary  = item.get("summary", "")
            source   = item.get("source", "")
            if headline:
                articles.append({
                    "title":      headline,
                    "snippet":    summary[:400] if summary else "",
                    "highlights": [],
                    "source":     source,
                    "sentiment":  None,
                })
    except Exception:
        pass

    return articles, change_pct


def _fetch_marketaux(ticker: str, marketaux_key: str) -> list[dict]:
    import requests
    articles = []

    try:
        r = requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={
                "symbols":         ticker,
                "filter_entities": "true",
                "language":        "en",
                "limit":           3,
                "published_after": (date.today() - timedelta(days=3)).isoformat(),
                "api_token":       marketaux_key,
            },
            timeout=8,
        )
        if r.status_code != 200:
            return []

        for art in r.json().get("data", [])[:3]:
            title   = art.get("title", "")
            desc    = art.get("description", "")
            snippet = art.get("snippet", "")
            source  = art.get("source", "")

            sentiment       = None
            highlight_texts = []
            for ent in art.get("entities", []):
                if ent.get("symbol", "").upper() == ticker.upper():
                    sentiment = ent.get("sentiment_score")
                    for h in ent.get("highlights", [])[:2]:
                        txt = h.get("highlight", "").strip()
                        if txt:
                            highlight_texts.append(txt)
                    break

            # 본문: snippet 우선, 없으면 description
            body = snippet[:400] if snippet else (desc[:300] if desc else "")

            if title:
                articles.append({
                    "title":      title,
                    "snippet":    body,
                    "highlights": highlight_texts,
                    "source":     source,
                    "sentiment":  round(sentiment, 2) if sentiment is not None else None,
                })
    except Exception:
        pass

    return articles


def _fetch_yfinance_fallback(ticker: str) -> tuple[list[dict], float | None]:
    try:
        import yfinance as yf
        tk       = yf.Ticker(ticker)
        articles = []
        for item in (tk.news or [])[:3]:
            title = (
                item.get("title")
                or item.get("content", {}).get("title")
                or item.get("content", {}).get("summary", "")
            )
            title = str(title).strip()
            if title and len(title) > 5:
                articles.append({
                    "title": title, "snippet": "",
                    "highlights": [], "source": "", "sentiment": None,
                })

        change_pct = None
        hist = tk.history(period="5d")
        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
            curr = float(hist["Close"].iloc[-1])
            if prev > 0:
                change_pct = round((curr - prev) / prev * 100, 2)

        return articles, change_pct
    except Exception:
        return [], None


def fetch_ticker_data(
    ticker: str,
    finnhub_key: str | None,
    marketaux_key: str | None,
) -> tuple[list[dict], float | None]:
    finnhub_articles:   list[dict] = []
    marketaux_articles: list[dict] = []
    change_pct: float | None = None

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {}
        if finnhub_key:
            futures["finnhub"]   = ex.submit(_fetch_finnhub,   ticker, finnhub_key)
        if marketaux_key:
            futures["marketaux"] = ex.submit(_fetch_marketaux, ticker, marketaux_key)

        for name, fut in futures.items():
            try:
                if name == "finnhub":
                    finnhub_articles, change_pct = fut.result()
                else:
                    marketaux_articles = fut.result()
            except Exception:
                pass

    if not finnhub_articles and not marketaux_articles:
        return _fetch_yfinance_fallback(ticker)

    # Marketaux 우선, Finnhub 보완 (제목 중복 제거)
    seen:   set[str]   = set()
    merged: list[dict] = []
    for art in marketaux_articles + finnhub_articles:
        key = art["title"][:40].lower()
        if key not in seen:
            seen.add(key)
            merged.append(art)

    return merged[:4], change_pct


# ─────────────────────────────────────────────
# 프롬프트 빌더
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = """당신은 미국 주식 포트폴리오 분석 AI입니다.

[분석 기준]
- 뉴스와 애널리스트 데이터를 근거로 판단합니다
- 뉴스가 없으면 애널리스트 데이터만으로 판단하고, 뉴스 내용을 추측하거나 창작하지 마세요
- 애널리스트 데이터도 없으면 "정보 부족으로 판단 유보"라고 명시하세요
- 상충하는 신호(예: 강력매수인데 현재가가 목표가 상회, 어닝 임박인데 직전 EPS 미스)가 있으면 반드시 언급하세요
- 액션은 구체적 조건과 함께 제시하세요. "비중 유지" 단독 사용 금지
- JSON 배열만 응답하세요. 코드블록, 설명 텍스트 절대 없이"""


def _format_news_block(articles: list[dict]) -> str:
    if not articles:
        return "없음"
    lines = []
    for art in articles[:3]:
        title      = art.get("title", "")
        snippet    = art.get("snippet", "")
        source     = art.get("source", "")
        highlights = art.get("highlights", [])
        senti      = art.get("sentiment")

        line = f"[{source}] {title}" if source else title
        if snippet:
            line += f"\n    본문: {snippet[:400]}"
        if highlights:
            line += f"\n    핵심구절: {' / '.join(highlights[:2])}"
        if senti is not None:
            label = "긍정" if senti > 0.2 else "부정" if senti < -0.2 else "중립"
            line += f"\n    감성: {label}({senti:+.2f})"
        lines.append(line)
    return "\n".join(lines)


def _analyst_conflict(ana: dict) -> str:
    """애널리스트 데이터 내 상충 신호 사전 감지."""
    signals = []
    rec = ana.get("rec_key", "")
    up  = ana.get("target_upside_pct")
    ed  = ana.get("earnings_days_left")
    eps = ana.get("eps_surprise_pct")

    if rec and "BUY" in rec and up is not None and up < -5:
        signals.append(f"⚠️ {rec} 의견이나 현재가가 목표주가를 {abs(up):.1f}% 상회 — 주가 선반영 또는 목표가 미업데이트 가능성")
    if ed is not None and 0 <= ed <= 7:
        signals.append(f"🔔 실적 발표 D-{ed} — 발표 전후 변동성 확대 구간, 포지션 주의")
    if eps is not None and eps < -10:
        signals.append(f"⚠️ 직전 EPS {eps:+.1f}% 미스 — 실적 신뢰도 하락, 이번 어닝 리스크 존재")
    if eps is not None and eps > 20 and ed is not None and ed > 0:
        signals.append(f"✅ 직전 EPS {eps:+.1f}% 서프라이즈 — 이번 어닝 기대감 유효")
    if rec and "SELL" in rec and up is not None and up > 5:
        signals.append(f"⚠️ 매도 의견이나 목표가 상승여력 {up:.1f}% — 애널리스트 간 의견 분화 가능성")

    return "\n  ".join(signals) if signals else "없음"


def _build_batch_prompt(
    holdings: dict,
    data_map: dict,
    analyst_ctx: dict,
) -> str:
    items = []
    for ticker, shares in holdings.items():
        articles, change_pct = data_map.get(ticker, ([], None))
        ana = analyst_ctx.get(ticker, {})

        change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"

        # 애널리스트 블록
        ana_parts = []
        if ana.get("rec_key"):
            n_str = f" ({ana['n_analysts']}명)" if ana.get("n_analysts") else ""
            ana_parts.append(f"투자의견:{ana['rec_key']}{n_str}")
        if ana.get("target_mean") and ana.get("current_price"):
            up = ana.get("target_upside_pct")
            up_str = f"({up:+.1f}%)" if up is not None else ""
            ana_parts.append(f"목표주가:${ana['target_mean']}{up_str} / 현재가:${ana['current_price']}")
        if ana.get("target_high") and ana.get("target_low"):
            ana_parts.append(f"목표가범위:${ana['target_low']}~${ana['target_high']}")
        if ana.get("earnings_days_left") is not None:
            d = ana["earnings_days_left"]
            label = f"D+{abs(d)}발표완료" if d < 0 else f"D-{d}발표예정"
            ana_parts.append(f"어닝:{label}({ana.get('earnings_date','')})")
        if ana.get("eps_surprise_pct") is not None:
            ana_parts.append(f"직전EPS서프라이즈:{ana['eps_surprise_pct']:+.1f}%")
        ana_str = "\n  ".join(ana_parts) if ana_parts else "없음"

        conflict  = _analyst_conflict(ana)
        news_str  = _format_news_block(articles)
        news_note = "" if articles else "\n  (뉴스 없음 — 뉴스 기반 언급 금지, 애널리스트 데이터만으로 판단)"

        items.append(
            f"[{ticker}] {shares:.1f}주 | 전일대비:{change_str}\n"
            f"  애널리스트:\n  {ana_str}\n"
            f"  사전감지신호:{conflict}\n"
            f"  뉴스:{news_note}\n  {news_str}"
        )

    tickers_list = list(holdings.keys())
    return (
        f"포트폴리오 {len(holdings)}개 종목 분석:\n\n"
        + "\n\n".join(items)
        + f"""

JSON 배열로만 응답 (코드블록 없이):
[{{"ticker":"종목","signal":"up/down/neutral","reason":"핵심판단40자이내","bullets":["뉴스해석","애널리스트해석(상충신호포함)","조건부액션"],"tags":["태그1","태그2"],"related":[{{"ticker":"관련기업","reason":"연관이유"}}]}}]

rules:
- 한국어
- signal: 뉴스+애널리스트 종합. 상충 신호 있으면 neutral
- reason: 40자 이내, 가장 핵심적인 판단 한 문장
- bullets 정확히 3개:
  ①뉴스해석: 뉴스 본문 내용 기반 해석. 뉴스 없으면 "최근 유의미한 뉴스 없음"
  ②애널리스트: 투자의견·목표가·어닝·EPS 종합 해석. 사전감지신호 반드시 반영
  ③조건부액션: "~확인되면 비중확대 / ~시 일부 축소" 형식. 조건 없는 단순 유지 금지
- related: 직접 연관된 실제 기업 1~2개 (공급사/경쟁사/파트너), 없으면[]
- 반드시 {len(holdings)}개 전부 포함: {', '.join(tickers_list)}"""
    )


# ─────────────────────────────────────────────
# Gemini 호출
# ─────────────────────────────────────────────

def _gemini_batch(
    holdings: dict,
    data_map: dict,
    analyst_ctx: dict,
    api_key: str,
) -> dict[str, dict]:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=_SYSTEM_PROMPT,
    )
    response = model.generate_content(
        _build_batch_prompt(holdings, data_map, analyst_ctx)
    )
    raw = response.text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    results_list = json.loads(raw)
    result_map   = {}
    for item in results_list:
        ticker = item.get("ticker", "")
        if not ticker:
            continue
        _, change_pct = data_map.get(ticker, ([], None))
        if change_pct is not None:
            item["signal"] = "up" if change_pct > 0 else ("down" if change_pct < 0 else "neutral")
        item.setdefault("signal", "neutral")
        item.setdefault("reason", "분석 정보 없음")
        item.setdefault("bullets", ["정보 없음"] * 3)
        item.setdefault("tags", [])
        item.setdefault("related", [])
        while len(item["bullets"]) < 3:
            item["bullets"].append("추가 정보 없음")
        item["bullets"] = item["bullets"][:3]
        result_map[ticker] = item

    return result_map


def _gemini_single(
    ticker: str,
    shares: float,
    articles: list[dict],
    change_pct: float | None,
    analyst_ctx: dict,
    api_key: str,
) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=_SYSTEM_PROMPT,
    )
    change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"
    news_str   = _format_news_block(articles)
    ana        = analyst_ctx.get(ticker, {})

    ana_parts = []
    if ana.get("rec_key"):
        ana_parts.append(f"투자의견:{ana['rec_key']}")
    if ana.get("target_upside_pct") is not None:
        ana_parts.append(f"목표가괴리:{ana['target_upside_pct']:+.1f}%")
    if ana.get("earnings_days_left") is not None:
        d = ana["earnings_days_left"]
        ana_parts.append(f"어닝:{'D+'+str(abs(d))+'완료' if d<0 else 'D-'+str(d)+'예정'}")
    if ana.get("eps_surprise_pct") is not None:
        ana_parts.append(f"직전EPS:{ana['eps_surprise_pct']:+.1f}%")
    ana_str  = " | ".join(ana_parts) if ana_parts else "없음"
    conflict = _analyst_conflict(ana)
    news_note = "" if articles else " (뉴스 없음 — 추측 금지)"

    prompt = (
        f"종목:{ticker} ({shares:.1f}주) | 전일대비:{change_str}\n"
        f"애널리스트: {ana_str}\n"
        f"사전감지신호: {conflict}\n"
        f"뉴스:{news_note}\n{news_str}\n\n"
        f'JSON:{{"signal":"up/down/neutral","reason":"40자이내","bullets":["뉴스해석","애널리스트해석(상충포함)","조건부액션"],"tags":["태그1"],"related":[]}}'
    )

    response = model.generate_content(prompt)
    raw = response.text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    result = json.loads(raw)

    if change_pct is not None:
        result["signal"] = "up" if change_pct > 0 else ("down" if change_pct < 0 else "neutral")
    result.setdefault("signal", "neutral")
    result.setdefault("reason", "분석 정보 없음")
    result.setdefault("bullets", ["정보 없음"] * 3)
    result.setdefault("tags", [])
    result.setdefault("related", [])
    while len(result["bullets"]) < 3:
        result["bullets"].append("추가 정보 없음")
    result["bullets"] = result["bullets"][:3]
    return result


# ─────────────────────────────────────────────
# 스마트 캐시
# ─────────────────────────────────────────────

REANALYZE_THRESHOLD = 0.5


def _needs_reanalysis(
    ticker: str,
    change_pct: float | None,
    cached_results: list[dict],
) -> bool:
    if change_pct is None:
        return True
    if abs(change_pct) >= REANALYZE_THRESHOLD:
        return True
    return ticker not in {r["ticker"] for r in cached_results}


# ─────────────────────────────────────────────
# 메인 분석
# ─────────────────────────────────────────────

def analyze_portfolio_signals(
    holdings: dict[str, float],
    api_key: str,
    finnhub_key: str | None = None,
    marketaux_key: str | None = None,
    progress_callback=None,
    portfolio=None,
    cached_results: list[dict] | None = None,
) -> list[dict]:
    holdings = {t: s for t, s in holdings.items() if s > 0}
    tickers  = list(holdings.keys())
    total    = len(tickers)

    from datetime import datetime
    today    = date.today().isoformat()
    now_time = datetime.now().strftime("%H:%M")

    # ── 1단계: 뉴스+시세 병렬 수집 ─────────────────────────────
    if progress_callback:
        progress_callback(0, total, "데이터 수집 중", None)

    data_map: dict[str, tuple[list[dict], float | None]] = {}
    with ThreadPoolExecutor(max_workers=min(10, total)) as executor:
        futures = {
            executor.submit(fetch_ticker_data, t, finnhub_key, marketaux_key): t
            for t in tickers
        }
        for future in as_completed(futures):
            t = futures[future]
            try:
                data_map[t] = future.result()
            except Exception:
                data_map[t] = ([], None)

    # ── 2단계: 애널리스트 데이터 수집 ───────────────────────────
    if progress_callback:
        progress_callback(0, total, "애널리스트 데이터 수집 중", None)

    analyst_ctx = fetch_analyst_data(tickers)

    # ── 3단계: 스마트 캐시 분리 ─────────────────────────────────
    cached_map: dict[str, dict] = {}
    if cached_results:
        for r in cached_results:
            cached_map[r["ticker"]] = r

    reanalyze_tickers: list[str] = []
    keep_tickers:      list[str] = []

    for t in tickers:
        _, change_pct = data_map.get(t, ([], None))
        if _needs_reanalysis(t, change_pct, cached_results or []):
            reanalyze_tickers.append(t)
        else:
            keep_tickers.append(t)

    # ── 4단계: Gemini 배치 분석 ─────────────────────────────────
    signal_map: dict[str, dict] = {}

    for t in keep_tickers:
        if t in cached_map:
            signal_map[t] = cached_map[t].get("signal", {})

    if reanalyze_tickers:
        if progress_callback:
            progress_callback(1, total, "AI 분석 중", None)

        re_holdings = {t: holdings[t]     for t in reanalyze_tickers}
        re_data     = {t: data_map[t]     for t in reanalyze_tickers}
        re_analyst  = {t: analyst_ctx.get(t, {}) for t in reanalyze_tickers}

        try:
            batch_result = _gemini_batch(re_holdings, re_data, re_analyst, api_key)
            signal_map.update(batch_result)
        except Exception:
            if progress_callback:
                progress_callback(1, total, "배치 실패, 순차 분석 중...", None)
            for i, t in enumerate(reanalyze_tickers):
                articles, change_pct = re_data.get(t, ([], None))
                try:
                    signal_map[t] = _gemini_single(
                        t, holdings[t], articles, change_pct, re_analyst, api_key
                    )
                except Exception as e2:
                    signal_map[t] = {"_error": str(e2)}
                if progress_callback:
                    progress_callback(i + 1, len(reanalyze_tickers), t, None)

    # ── 5단계: 결과 조합 ─────────────────────────────────────────
    results = []
    for ticker in tickers:
        articles, change_pct = data_map.get(ticker, ([], None))
        headlines = [a["title"] for a in articles if a.get("title")]

        if ticker in keep_tickers and ticker in cached_map:
            old = cached_map[ticker].copy()
            old["change_pct"]   = change_pct
            old["reused_cache"] = True
            results.append(old)
        else:
            ana  = analyst_ctx.get(ticker, {})
            item = {
                "ticker":        ticker,
                "shares":        holdings[ticker],
                "change_pct":    change_pct,
                "headlines":     headlines,
                "articles":      articles,
                "signal":        signal_map.get(ticker, {"_error": "분석 결과 없음"}),
                "logo_url":      portfolio.get_logo(ticker) if portfolio else None,
                "analyzed_date": today,
                "analyzed_time": now_time,
                "reused_cache":  False,
                "analyst": {
                    "rec_key":            ana.get("rec_key"),
                    "rec_mean":           ana.get("rec_mean"),
                    "n_analysts":         ana.get("n_analysts"),
                    "current_price":      ana.get("current_price"),
                    "target_mean":        ana.get("target_mean"),
                    "target_high":        ana.get("target_high"),
                    "target_low":         ana.get("target_low"),
                    "target_upside_pct":  ana.get("target_upside_pct"),
                    "earnings_date":      ana.get("earnings_date"),
                    "earnings_days_left": ana.get("earnings_days_left"),
                    "eps_surprise_pct":   ana.get("eps_surprise_pct"),
                },
            }
            results.append(item)

        if progress_callback:
            progress_callback(tickers.index(ticker) + 1, total, ticker, results[-1])

    return results