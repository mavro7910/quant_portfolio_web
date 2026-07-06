# QPM Alpha

QPM Alpha는 적립식 투자자를 위한 웹 기반 포트폴리오 관리 애플리케이션입니다.  
보유 종목의 평가금액, 주간 투자 배분, AI 기반 뉴스 인사이트, 월간 리밸런싱, 백테스트를 하나의 화면 흐름에서 제공합니다.

---

## Overview

QPM Alpha는 자동 미국 대형주 유니버스에서 월간 투자 종목을 선정하고,
사용자가 입력한 금액을 현재 부족 비중에 따라 매주 배분합니다.

주요 목표는 다음과 같습니다.

- 포트폴리오 현황을 빠르게 파악
- 데이터 기반 주간 매수 금액 산출
- 뉴스와 애널리스트 데이터를 활용한 AI 시그널 확인
- 과거 성과와 벤치마크 비교
- 리밸런싱과 매도 점검을 직관적으로 지원

---

## Key Features

| 영역 | 설명 |
|---|---|
| 포트폴리오 관리 | 보유 종목, 수량, 평가금액, 원화/달러 총액 확인 |
| 기업 로고 표시 | 종목 카드와 주요 표에서 기업 로고 표시 |
| 데이터 업데이트 | 시세 갱신, 종목명 조회, 자동 갱신 설정 |
| AI 시그널 | 보유 종목의 뉴스와 애널리스트 데이터를 AI가 요약 |
| 이번 주 투자 | Academic Momentum 순위와 부족 비중 기반 주간 금액 계산 |
| 리밸런싱 | 현재 비중과 목표 비중 차이를 계산해 추가 매수/매도 금액 제시 |
| 백테스트 | QPM Alpha 전략과 벤치마크의 과거 성과 비교 |
| 테마 저장 | 라이트/다크 모드 설정을 사용자별로 저장 |
| 모바일 최적화 | 작은 화면에서도 평가금액, 버튼, 차트가 읽히도록 조정 |

---

## Product Flow

```mermaid
flowchart TD
    A["Google 로그인"] --> B["사용자 포트폴리오 로드"]
    B --> C["보유 종목 / 설정 / 테마 복원"]
    C --> D["시세·환율·종목명·로고 갱신"]
    D --> E["포트폴리오 현황 확인"]
    E --> F["이번 주 투자"]
    E --> G["AI 인사이트"]
    E --> I["월간 리밸런싱"]
    F --> J["백테스트"]
```

---

## Tabs

| 탭 | 제공 기능 |
|---|---|
| 포트폴리오 | 총 평가금액, 보유 종목 리스트, 종목 추가/삭제, 수량 편집, 캡처 이미지 기반 업데이트 |
| 이번 주 투자 | 자동 Top 100 순위, 부족 비중 기반 추천 금액, 과열·API 위험 |
| 월간 리밸런싱 | 월간 고정 Top N과 허용밴드 기반 매수·매도 |
| AI 인사이트 | 종목별 AI 요약, 뉴스, 애널리스트 데이터, 상승/하락 필터 |
| 백테스트 | 평가금액/누적수익률 차트, XIRR, MDD, 변동성, Sharpe |
| 설정 | 기본 주간 배분금액, Top N, 벤치마크, API 키, 데이터 가져오기/내보내기 |

---

## Investment Logic

Academic Momentum v1은 보유종목과 투자 유니버스를 분리합니다. NYSE·Nasdaq 시가총액
상위 100개 보통주와 ADR을 자동 구성하고 ETF·우선주·중복 클래스를 제외합니다.

### Factor Inputs

| 팩터 | 설명 |
|---|---|
| 12-1 모멘텀 | 최근 1개월을 제외한 12개월 수익률의 횡단면 순위 |
| 수익경로 지속성 | 형성기간 중 모멘텀 방향과 같은 일간 수익률의 비율 |
| 낮은 잔차변동성 | 최근 126일 QQQ 회귀 잔차의 변동성이 낮을수록 높은 순위 |

### Weight Calculation

```text
score = 0.65 * percentile_rank(momentum_12_to_1)
      + 0.20 * percentile_rank(return_path_continuity)
      + 0.15 * percentile_rank(low_residual_volatility)

selected = top_n(score)
target_weight = 1 / top_n
```

Top N은 월간 고정하고, 주간 신규 자금은 `목표 평가금액 - 현재 평가금액`이
큰 종목부터 배분합니다. ±3% 기본 리밸런싱 허용밴드로 불필요한 매매를 줄입니다.
단기 과열도와 Finnhub·Marketaux·yfinance 인사이트는 표시하고 기록하지만,
전향 검증 전에는 팩터 비중을 변경하지 않습니다.

팩터 선택은 Jegadeesh·Titman의 횡단면 모멘텀, Da·Gurun·Warachka의
Frog-in-the-Pan, Blitz·Huij·Martens의 잔차 모멘텀과 Ang et al.의
고유변동성 연구를 바탕으로 합니다.

백테스트는 전일 종가까지 신호를 계산하고 다음 거래일 종가로 체결합니다.
입출금을 제거한 시간가중 수익률로 MDD·변동성·Sharpe를 계산합니다.

---

## Data Storage

| 항목 | 저장 방식 |
|---|---|
| 포트폴리오 | Supabase 우선, 로컬 실행 시 JSON fallback |
| 사용자 설정 | 포트폴리오 데이터와 함께 저장 |
| 다크모드 | 사용자 설정으로 저장 |
| API 키 | 암호화 후 저장 |
| AI 시그널 캐시 | 사용자와 날짜 기준으로 저장 |
| 전략 관측 기록 | 최근 52회 선정·비중·과열·API 위험을 저장 |

---

## Local Setup

```bash
git clone https://github.com/mavro7910/quant_portfolio_web.git
cd quant_portfolio_web
pip install -r requirements.txt
streamlit run app.py
```

Supabase 설정이 없으면 로컬 JSON 파일에 포트폴리오가 저장됩니다.

### Optional `.streamlit/secrets.toml`

```toml
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_KEY = "eyJhbGci..."
ES = "random_string_32chars_or_more"

[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "random_string_32chars_or_more"

[auth.google]
client_id = "xxxx.apps.googleusercontent.com"
client_secret = "GOCSPX-xxxx"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

---

## Supabase Schema

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
    uid         text,
    cache_date text,
    data       jsonb not null,
    updated_at timestamp with time zone default now(),
    primary key (uid, cache_date)
);
```

---

## Project Structure

```text
quant_portfolio_web/
├── app.py
├── requirements.txt
├── assets/
│   └── icon.png
├── core/
│   ├── data.py
│   ├── portfolio.py
│   ├── secrets_store.py
│   ├── strategy.py
│   ├── universe.py
│   └── insights.py
├── tabs/
│   ├── tab_portfolio.py
│   ├── tab_ai_signal.py
│   ├── tab_buyrec.py
│   ├── tab_backtest.py
│   ├── tab_rebalance.py
│   └── tab_settings.py
└── utils/
    ├── ai_client.py
    ├── plotly_theme.py
    ├── styles.py
    └── ui.py
```

---

## Dependencies

| Package | Version |
|---|---|
| `streamlit` | `1.56.0` |
| `yfinance` | `>=1.2.0` |
| `pandas` | `>=2.2.0,<3.0` |
| `numpy` | `>=1.26.0,<2.1` |
| `plotly` | `>=5.22.0` |
| `scipy` | `>=1.13.0` |
| `Pillow` | `>=10.3.0` |
| `requests` | `>=2.32.0` |
| `supabase` | `>=2.0.0` |
| `authlib` | `1.6.11` |
| `google-generativeai` | `>=0.8.0` |
| `cryptography` | `>=42.0.0` |

---

## Update History

### Current

- Academic Momentum(12-1 + 지속성 + 낮은 잔차변동성) 전략
- 자동 NYSE·Nasdaq 시가총액 Top 100 유니버스와 ADR 지원
- 월간 Top N 고정, 부족 비중 기반 주간 적립, 리밸런싱 허용밴드
- API 이벤트 위험의 전향 검증 기록
- 전일 신호/다음 거래일 체결과 현금흐름 조정 위험지표
- UI를 단일 페이지 앱 흐름에 맞게 재정리
- 라이트/다크 모드 지원 및 사용자별 테마 저장
- 모바일 포트폴리오 카드에서 평가금액 표시 개선
- 기업 로고를 포트폴리오, AI 시그널, 매수 추천, 매도 신호, 리밸런싱에 적용
- 보유 종목 리스트를 평가금액 기준으로 정렬
- 포트폴리오 더보기/접기 버튼 중앙 정렬
- 데이터 업데이트 컨트롤을 포트폴리오 탭에 직접 노출
- 매도 신호 요약 카드와 히트맵 디자인 개선
- 백테스트 차트 레이블 위치 개선
- README를 제품 소개 형식으로 재작성

### Previous

- Google OAuth 로그인 지원
- Supabase 기반 포트폴리오 저장
- Gemini 기반 AI 시그널
- 캡처 이미지 기반 포트폴리오 업데이트
- XIRR 기반 백테스트 성과 요약
- 매도 신호 및 리밸런싱 탭 추가

---

## Disclaimer

이 애플리케이션은 정보 제공 및 교육 목적의 도구입니다. 특정 종목의 매수 또는 매도를 권유하지 않습니다. 모든 투자 판단과 책임은 사용자에게 있으며, 과거 성과가 미래 수익을 보장하지 않습니다.

---

MIT License
