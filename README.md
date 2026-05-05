# 📊 Quant Portfolio Manager

> **팩터 가중 모멘텀 전략 기반의 주간 적립식 퀀트 포트폴리오 매니저**  
> 기관 펀드매니저가 실제로 사용하는 계량 투자 방법론을 개인 투자자도 쉽게 활용할 수 있도록 구현했습니다.

---

## 목차

1. [이 앱이 하는 일](#이-앱이-하는-일)
2. [전략 철학](#전략-철학)
3. [알고리즘 상세](#알고리즘-상세)
4. [인증 & 데이터 저장](#인증--데이터-저장)
5. [백테스트 주의사항](#백테스트-주의사항)
6. [탭 기능 안내](#탭-기능-안내)
7. [프로젝트 구조](#프로젝트-구조)
8. [로컬 실행](#로컬-실행)
9. [배포](#배포)
10. [Dependencies](#dependencies)
11. [Changelog](#changelog)

---

## 이 앱이 하는 일

매주 정해진 금액(예: 50만 원)을 포트폴리오 종목들에 **어떻게 나눠서 살지** 자동으로 계산해 줍니다.

단순 균등 배분이 아니라, 아래 두 가지 질문에 답하면서 비중을 결정합니다.

> "지금 이 종목이 시장에서 얼마나 잘 달리고 있나?" (모멘텀)  
> "지금 이 종목이 얼마나 출렁거리고 있나?" (변동성)

Bull/Bear 국면에 따라 두 질문의 비중을 다르게 섞어 최종 매수 금액을 결정합니다.

**AI 시그널 탭**에서는 보유 종목의 최신 뉴스를 Gemini AI가 분석해 시그널(상승/하락/중립)과 핵심 이유를 카드 형태로 보여줍니다.

---

## 전략 철학

### 💡 DCA의 한계

매월 정액을 투자하는 분할 매수 전략은 훌륭한 습관이지만, 어떤 종목을 얼마나 살지를 무작위로 결정하면 수익률 차이가 크게 납니다. 이 앱은 DCA의 규칙성은 유지하면서 매수 배분을 데이터 기반으로 최적화합니다.

### 💡 모멘텀 팩터

수십 년간의 실증 연구(Jegadeesh & Titman, 1993; Asness et al., 2013)에서 반복 확인된 사실입니다.

> 최근  6 ~ 12 개월간 잘 오른 종목은, 향후 3 ~ 6 개월도 계속 오르는 경향이 있다.

단순 추세 추종이 아니라, 기업 펀더멘털 개선이 주가에 반영되는 속도 차이(정보 확산 지연)를 이용하는 전략입니다.

### 💡 Low Volatility 팩터

반직관적이지만, 덜 출렁이는 종목이 장기적으로 더 좋은 위험조정수익률(Sharpe Ratio)을 냅니다. 특히 하락장에서 낙폭이 작아 원금 보전에 유리합니다.

### 💡 두 팩터를 섞는 이유

모멘텀은 강세장에서 강하지만 급락장에서 크게 손실이 납니다(Momentum Crash). Low Volatility는 하락장 방어에 탁월하지만 강세장에서는 시장에 뒤처집니다. 두 팩터는 서로의 약점을 보완하며, 시장 국면에 따라 비율을 동적으로 조절하면 단독 팩터보다 안정적인 수익 곡선을 만들 수 있습니다.

---

## 알고리즘 상세

### Step 1: 시장 국면 판단

**Indicator: QQQ 200일 이동평균선**

```
QQQ > 200MA  →  Bull Market
QQQ < 200MA  →  Bear Market
```

### Step 2: 모멘텀 점수 산출

4개 기간을 동시에 측정한 뒤 가중 평균합니다.

| 기간 | Trading Days | 가중치 |
|------|-------------|--------|
| 단기 | 21일 (1개월) | 10% |
| 중단기 | 63일 (3개월) | 20% |
| 중기 | 126일 (6개월) | 30% |
| 장기 | 252일 (12개월) | 40% |

수익률 자체가 아닌 **Rank**를 사용해 종목 간 공정한 비교를 보장하고 outlier 영향을 최소화합니다.

### Step 3: Low Volatility 점수 산출

60일 일간 수익률 표준편차의 역수를 rank화합니다. 덜 출렁일수록 높은 점수를 부여합니다.

### Step 4: Factor Tilt & 비중 결정

| 국면 | 모멘텀 | Low Volatility |
|------|--------|---------------|
| 🐂 Bull | 70% | 30% |
| 🐻 Bear | 40% | 60% |

종목당 최대 비중 **25% 캡**을 적용해 single-stock risk를 방지합니다.

### Step 5: 매수 금액 계산

```
매수 금액 = 목표 비중 × 주간 예산
```

---

## 인증 & 데이터 저장

### Google Login (OIDC)

Streamlit 공식 Google OAuth를 사용합니다. 별도 회원가입 없이 Google 계정으로 로그인하면 됩니다.

```
앱 접속  →  Google 로그인  →  이메일 기반 포트폴리오 자동 로드
```

### 데이터 저장

포트폴리오와 설정값은 **Supabase**에 저장됩니다. Streamlit Cloud 재시작 시에도 데이터가 유지됩니다.

```
로그인 이메일  →  SHA-256 해시(16자)  →  Supabase portfolios 테이블
```

### API Key 보안

Gemini / Finnhub API 키는 암호화되어 Supabase에 저장됩니다. 관리자도 원문을 확인할 수 없습니다.

---

## 백테스트 주의사항

### ⚠️ 1. Survivorship Bias

현재 보유 종목(살아남은 종목)만으로 과거를 시뮬레이션합니다. 실제 성과보다 과대평가될 수 있습니다.

### ⚠️ 2. 시총 근사 오차

`현재 발행주수 × 과거 주가`로 시총을 근사합니다. 자사주 매입·유상증자 등으로 인한 오차가 일부 잔존합니다.

### ⚠️ 3. CAGR 대신 XIRR 사용

적립식 투자에서 CAGR은 모든 돈을 첫날 한 번에 넣었다고 가정해 수익률을 과대평가합니다. 각 투자 시점을 정확히 반영한 **XIRR**을 사용합니다.

---

## 탭 기능 안내

| 탭 | 기능 | 활용 시점 |
|----|------|----------|
| 📋 포트폴리오 | 종목 추가/삭제, 수량 인라인 편집, 실시간 시세 및 원화 평가금액 | 매주 현황 확인 및 수량 업데이트 |
| 📡 AI 시그널 | 보유 종목 뉴스 AI 분석 (Gemini + Finnhub), 상승/하락/중립 카드 UI | 투자 결정 전 뉴스 흐름 파악 |
| 🧮 매수 추천 | 팩터 알고리즘 기반 이번 주 매수 금액 추천, 목표 비중 파이차트 | 매주 투자 실행 전 |
| 📈 백테스트 | 동일 전략 과거 시뮬레이션, XIRR 기준 성과 요약 | 전략 신뢰도 확인 |
| 🚨 매도 신호 | 최근 1달 일별 랭킹 분석 — Top N 미진입 종목 자동 분류, heatmap | 정기 포트폴리오 점검 |
| ⚖️ 리밸런싱 | 현재 비중 vs 목표 비중 비교, 종목별 매도/매수 수량 및 금액 | 분기·반기 리밸런싱 |
| ⚙️ 설정 | 주간 투자금, 벤치마크, API 키 관리, 데이터 export/import | 초기 설정 또는 파라미터 변경 |

---

## 프로젝트 구조

```
quant_portfolio_web/
├── app.py                      # 진입점 — 탭 구성 및 라우팅
├── requirements.txt
├── assets/
│   └── icon.png
├── core/
│   ├── data.py                 # 시세/환율 수집 (yfinance wrapper)
│   ├── portfolio.py            # 포트폴리오 저장/로드 (Supabase / local JSON fallback)
│   ├── secrets_store.py        # API 키 암호화 저장/로드 (Supabase)
│   └── strategy.py             # Factor 전략, 매수 추천, 백테스트, XIRR
├── tabs/
│   ├── tab_portfolio.py
│   ├── tab_ai_signal.py
│   ├── tab_buyrec.py
│   ├── tab_backtest.py
│   ├── tab_sell_signal.py
│   ├── tab_rebalance.py
│   └── tab_settings.py
└── utils/
    ├── ai_client.py            # Gemini API + Finnhub data fetcher
    └── styles.py               # Global CSS
```

---

## 로컬 실행

```bash
git clone https://github.com/mavro7910/quant_portfolio_web.git
cd quant_portfolio_web
pip install -r requirements.txt
```

`.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "eyJhbGci..."
ES = "random_string_32chars_or_more"

[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "random_string_32chars_or_more"

[auth.google]
client_id     = "xxxx.apps.googleusercontent.com"
client_secret = "GOCSPX-xxxx"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

```bash
streamlit run app.py
```

**Secret 생성:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

> Google Cloud Console → OAuth 클라이언트 → Authorized redirect URIs에 `http://localhost:8501/oauth2callback` 추가 필요

---

## Supabase 테이블

```sql
create table portfolios (
    uid        text primary key,
    data       jsonb not null,
    updated_at timestamp with time zone default now()
);

create table user_secrets (
    uid        text primary key,
    s          text not null,
    updated_at timestamp with time zone default now()
);

create table signal_cache (
    uid        text,
    cache_date text,
    data       jsonb not null,
    updated_at timestamp with time zone default now(),
    primary key (uid, cache_date)
);
```

---

## 배포

### Streamlit Community Cloud (무료)

1. GitHub에 push
2. [share.streamlit.io](https://share.streamlit.io) → **New app** → `app.py` → **Deploy**
3. **Settings → Secrets**:

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "eyJhbGci..."
ES = "random_string_32chars_or_more"

[auth]
redirect_uri = "https://YOUR_APP.streamlit.app/oauth2callback"
cookie_secret = "random_string_32chars_or_more"

[auth.google]
client_id     = "xxxx.apps.googleusercontent.com"
client_secret = "GOCSPX-xxxx"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

4. Google Cloud Console → Authorized redirect URIs에 `https://YOUR_APP.streamlit.app/oauth2callback` 추가

---

## Dependencies

| Package | Version | 용도 |
|---------|---------|------|
| `streamlit` | ≥ 1.45.0 | Web framework |
| `authlib` | ≥ 1.3.2 | Google OAuth OIDC |
| `yfinance` | ≥ 1.2.0 | 시세/환율/뉴스 |
| `pandas` | ≥ 2.2.0, < 3.0 | 데이터 처리 |
| `numpy` | ≥ 1.26.0, < 2.1 | 수치 계산 |
| `plotly` | ≥ 5.22.0 | 차트 |
| `scipy` | ≥ 1.13.0 | XIRR (brentq) |
| `Pillow` | ≥ 10.3.0 | 앱 아이콘 |
| `requests` | ≥ 2.32.0 | HTTP |
| `supabase` | ≥ 2.0.0 | DB |
| `google-generativeai` | ≥ 0.8.0 | Gemini API |
| `cryptography` | ≥ 42.0.0 | API 키 암호화 |

---

## Changelog

### v2.0.0

- **[신규]** 프로젝트 구조 리팩토링 — `app.py` 단일 파일 → `tabs/` + `utils/` 모듈 분리
  - `app.py` ~1,100줄 → ~160줄
  - 탭별 독립 파일 (`tabs/tab_*.py`)
  - CSS 분리 (`utils/styles.py`)
- **[신규]** `📡 AI 시그널` 탭
  - 보유 종목(수량 > 0) 뉴스를 Gemini AI로 분석
  - Finnhub API로 뉴스 + 가격변동 수집 (yfinance fallback)
  - 상승/하락/중립 카드 UI (HTML component)
  - 분석 결과 Supabase `signal_cache`에 날짜별 저장, 재접속 시 자동 로드
  - 병렬 데이터 수집 + Gemini 종목별 순차 분석
  - 가격변동 기반 signal 자동 보정 (±0.5% 기준)
- **[신규]** `core/secrets_store.py` — API 키 암호화 저장/로드
  - Supabase `user_secrets` 테이블에 암호화 blob으로 저장
- **[신규]** Supabase 연동 강화 — 포트폴리오, API 키, signal cache 모두 Supabase 저장
- **[개선]** `core/portfolio.py` — `settings` 프로퍼티 추가 (top_n, use_mcap 등)
- **[개선]** 설정 탭 — Gemini / Finnhub 키 통합 입력 UI

### v1.7.0

- **[신규]** Google OAuth(OIDC) 전환 — 멀티 디바이스 지원, iOS 홈 화면 지원
- **[변경]** 저장 경로: `portfolio_{uid}.json` → `portfolio_{email_hash}.json`

### v1.6.0

- **[신규]** 매도 신호 탭 — 21 거래일 일별 랭킹 분석, heatmap, 진입률 bar chart
- **[개선]** 성과 지표 CAGR → XIRR 교체

### v1.4.0

- **[신규]** 리밸런싱 탭
- **[신규]** 포트폴리오 탭 인라인 수량 편집 (`st.data_editor`)

### v1.3.0

- **[개선]** 백테스트 예산 배분 — 부족분 채우기 → Factor 비중 단순 비례 배분

### v1.2.0

- **[BUG FIX]** 백테스트 시총 look-ahead bias 개선
- **[개선]** XIRR 계산 함수 추가

### v1.1.0

- **[BUG FIX]** yfinance MultiIndex 컬럼 버그 등 다수 안정성 개선

---

## References

- Jegadeesh, N. & Titman, S. (1993). *Returns to Buying Winners and Selling Losers.* Journal of Finance.
- Asness, C., Moskowitz, T., & Pedersen, L. (2013). *Value and Momentum Everywhere.* Journal of Finance.
- Baker, M. & Haugen, R. (2012). *Low Risk Stocks Outperform within All Observable Markets.* SSRN.
- Antonacci, G. (2014). *Dual Momentum Investing.* McGraw-Hill.

---

## 면책 고지

이 앱은 정보 제공 및 교육 목적으로 제작되었습니다. 특정 종목이나 투자에 대한 매수/매도를 권유하지 않습니다. 모든 투자 결정은 본인의 판단과 책임 하에 이루어져야 하며, 과거 백테스트 성과가 미래 수익을 보장하지 않습니다.

---

MIT License
