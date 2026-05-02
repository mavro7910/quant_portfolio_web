# 📊 Quant Portfolio Manager — Streamlit 웹앱

팩터 가중 모멘텀 전략 기반의 **적립식 퀀트 포트폴리오 매니저**입니다.  
PyQt6 데스크톱 앱을 모바일/브라우저에서 실행 가능한 Streamlit 웹앱으로 변환한 버전이며,  
`core/` 폴더의 전략 로직(data, portfolio, strategy)은 그대로 유지됩니다.

-----

## 주요 기능

|탭      |설명                             |
|-------|-------------------------------|
|📋 포트폴리오|보유 종목 추가/삭제, 실시간 시세 조회         |
|🧮 매수 추천|팩터 가중 모멘텀 기반 주간 매수 금액 추천       |
|📈 백테스트 |주간 적립식 전략 vs 벤치마크 성과 비교        |
|⚙️ 설정   |주간 투자금, 벤치마크 설정, JSON 내보내기/불러오기|

-----

## 프로젝트 구조

```
quant_portfolio_web/
├── app.py                  # Streamlit 메인 앱
├── requirements.txt        # ← 루트에 위치해야 Streamlit Cloud가 인식
├── core/
│   ├── __init__.py
│   ├── data.py             # 시세/환율 데이터 수집
│   ├── portfolio.py        # 포트폴리오 JSON 저장/로드
│   └── strategy.py         # 팩터 전략, 매수 추천, 백테스트
└── data/
    └── portfolio.json      # 보유 종목 저장 (자동 생성)
```

-----

## 설치 및 로컬 실행

```bash
# 1. 저장소 클론
git clone https://github.com/mavro7910/quant_portfolio_web.git
cd quant_portfolio_web

# 2. 의존성 설치 (PyQt6 불필요)
pip install -r requirements.txt

# 3. 실행
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 로 자동 열립니다.  
같은 Wi-Fi의 스마트폰에서는 `http://<PC_IP>:8501` 로 접속하세요.

-----

## 클라우드 배포 (무료)

### ✅ Streamlit Community Cloud (권장)

1. 이 레포를 GitHub에 push
1. [share.streamlit.io](https://share.streamlit.io) 접속 후 로그인
1. **New app** → 레포/브랜치/`app.py` 선택 → **Deploy**
1. 생성된 `https://yourapp.streamlit.app` URL을 모바일에서 바로 열기

> **참고:** `requirements.txt`는 반드시 **프로젝트 루트**에 있어야 Streamlit Cloud가 자동으로 인식합니다.  
> `core/requirements.txt` 위치에서는 자동 설치가 되지 않습니다.

> **참고:** 일정 시간 접속이 없으면 앱이 sleep 상태로 전환됩니다. 첫 접속 시 약 30~60초 재시작 시간이 걸릴 수 있습니다.

-----

## 의존성

|패키지        |버전             |용도                          |
|-----------|---------------|----------------------------|
|`streamlit`|≥ 1.45.0       |웹 프레임워크                     |
|`yfinance` |≥ 1.2.0        |Yahoo Finance 시세/환율 조회      |
|`pandas`   |≥ 2.2.0, < 3.0 |데이터 처리                      |
|`numpy`    |≥ 1.26.0, < 2.1|수치 계산                       |
|`plotly`   |≥ 5.22.0       |인터랙티브 차트                    |
|`Pillow`   |≥ 10.3.0       |이미지 처리 (Streamlit 내부 의존)    |
|`requests` |≥ 2.32.0       |HTTP 요청 (yfinance 의존, 보안 패치)|

-----

## 전략 개요

- **시장 국면 판단**: QQQ 200일 이동평균 기준 강세/약세장 분류
- **팩터 결합 (Tilt 방식)**:
  - 강세장: 모멘텀 70% + 저변동성 30%
  - 약세장: 모멘텀 40% + 저변동성 60%
- **모멘텀**: 21/63/126/252일 다중 기간 순위 가중 평균
- **리밸런싱**: 주간 적립식 (부족분 비율 배분)
- **종목당 최대 비중**: 25%

-----

## PyQt6 → Streamlit 변환 대응표

|기존 (PyQt6)             |변환 (Streamlit)                        |
|-----------------------|--------------------------------------|
|`QTabWidget`           |`st.tabs()`                           |
|`QTableWidget`         |`st.dataframe()`                      |
|`matplotlib` embed     |`plotly` 인터랙티브 차트                     |
|`QProgressBar`         |`st.progress()` + `st.empty()`        |
|`QSpinBox`, `QLineEdit`|`st.number_input()`, `st.text_input()`|
|threading signal/slot  |`st.spinner()` + 동기 실행                |
|JSON 파일 저장             |JSON 저장 + 업/다운로드 버튼                   |

-----

## 주요 수정 이력

### v1.1.0

- **[BUG FIX]** `strategy.py`: 백테스트 루프마다 시총 API 재호출 → 1회 캐싱으로 속도 대폭 개선
- **[BUG FIX]** `strategy.py`: `cp=0/NaN` 종목 나눗셈 방지, `IndexError` 방어 처리
- **[BUG FIX]** `data.py`: yfinance 1.x MultiIndex 컬럼 빈 문자열 버그 대응
- **[BUG FIX]** `data.py`: 연휴 연속 시 시세 없음 방지 (`period=”10d“`)
- **[BUG FIX]** `portfolio.py`: Streamlit Cloud 읽기전용 파일시스템 대응 (경로 폴백)
- **[BUG FIX]** `app.py`: 종목 추가/삭제 시 세션 캐시 자동 무효화
- **[BUG FIX]** `app.py`: `buy_krw.sum()` dict/Series 타입 안전 처리
- **[개선]** 환율 fallback 값 현실화 및 `data.py`/`strategy.py` 통일
- **[개선]** `requirements.txt` 최신 버전 반영 및 루트 위치로 이동

-----

## 라이선스

MIT License