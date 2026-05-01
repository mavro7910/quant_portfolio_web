# Quant Portfolio Manager — Streamlit 웹앱 버전

PyQt6 데스크톱 앱을 모바일/브라우저에서 실행 가능한 **Streamlit 웹앱**으로 변환한 버전입니다.  
`core/` 폴더의 전략 로직은 그대로 유지됩니다.

---

## 설치 및 실행

```bash
# 1. 의존성 설치 (PyQt6 불필요, streamlit + plotly로 대체)
pip install -r requirements.txt

# 2. 실행
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 로 자동 열립니다.  
같은 Wi-Fi의 스마트폰에서는 `http://<PC_IP>:8501` 로 접속하세요.

---

## 클라우드 배포 (무료, 모바일 접속 가능)

### Streamlit Community Cloud (가장 간단)
1. GitHub에 이 폴더를 push
2. [share.streamlit.io](https://share.streamlit.io) 접속 → Deploy
3. 생성된 URL을 모바일 브라우저에서 열기

### Replit
1. [replit.com](https://replit.com) → New Repl → Python
2. 파일 업로드 후 `pip install -r requirements.txt`
3. `streamlit run app.py --server.port 8080`

---

## 변경 사항 (PyQt6 → Streamlit)

| 기존 (PyQt6) | 변환 (Streamlit) |
|---|---|
| `QTabWidget` | `st.tabs()` |
| `QTableWidget` | `st.dataframe()` |
| `matplotlib` embed | `plotly` 인터랙티브 차트 |
| `QProgressBar` | `st.progress()` |
| `QSpinBox`, `QLineEdit` | `st.number_input()`, `st.text_input()` |
| threading signal/slot | `st.spinner()` + 동기 실행 |
| JSON 파일 저장 | JSON 파일 저장 + 업/다운로드 버튼 |

`core/` 폴더 (data.py, portfolio.py, strategy.py)는 수정 없이 그대로 재사용.

