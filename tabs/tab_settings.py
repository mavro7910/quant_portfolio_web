"""tabs/tab_settings.py — 설정 탭 (API 키 관리 포함)"""

import json
import streamlit as st

from core.portfolio import Portfolio
from core.secrets_store import load_api_key, save_api_key, delete_api_key
from utils.ai_client import set_api_key, get_api_key, has_api_key, clear_api_key, validate_api_key


def render(portfolio: Portfolio, user_email: str, user_name: str, file_key: str):

    # ── 투자 설정 ──────────────────────────────────────────────────
    st.markdown('<div class="section-label">투자 설정</div>', unsafe_allow_html=True)

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        new_budget = st.number_input(
            "주간 투자 금액 (KRW)", min_value=10_000, max_value=100_000_000,
            value=portfolio.weekly_budget, step=10_000,
        )
    with col_s2:
        new_bm = st.text_input(
            "벤치마크 티커 (쉼표 구분)",
            value=", ".join(portfolio.benchmarks),
            placeholder="QQQM, XLK, SPY",
        )

    col_s3, col_s4 = st.columns(2)
    with col_s3:
        _max_n_cfg   = len(portfolio.tickers()) if portfolio.tickers() else 20
        _saved_n_cfg = portfolio.get_setting("top_n", 10)
        new_top_n = st.number_input(
            "기본 추천 종목 수 (Top N)",
            min_value=1,
            max_value=_max_n_cfg,
            value=min(_saved_n_cfg, _max_n_cfg),
            step=1,
        )
    with col_s4:
        new_use_mcap = st.checkbox(
            "시가총액 가중 기본값",
            value=portfolio.get_setting("use_mcap", True),
        )

    if st.button("💾 설정 저장", key="btn_save_settings"):
        portfolio.weekly_budget = new_budget
        bms = [b.strip().upper() for b in new_bm.split(",") if b.strip()]
        if not bms:
            st.error("벤치마크를 하나 이상 입력하세요.")
        else:
            portfolio.benchmarks = bms
            portfolio.set_setting("top_n", int(new_top_n))
            portfolio.set_setting("use_mcap", new_use_mcap)
            portfolio.save()
            st.success("✅ 설정이 저장되었습니다!")

    # ── 계정 정보 ──────────────────────────────────────────────────
    st.markdown('<div class="section-label">계정 정보</div>', unsafe_allow_html=True)
    st.markdown(f"""
<div class="info-banner">
    👤 <b>로그인 계정:</b> {user_name} ({user_email})<br>
    💾 <b>데이터 저장 경로:</b> <code>portfolio_{file_key}.json</code>
</div>
""", unsafe_allow_html=True)

    # ── Gemini API 키 ──────────────────────────────────────────────
    st.markdown('<div class="section-label">🤖 AI 시그널 — Gemini API 키</div>', unsafe_allow_html=True)

    # 세션에 키 없으면 Supabase에서 자동 로드
    if not has_api_key():
        stored_key, err = load_api_key(file_key)
        if stored_key:
            set_api_key(stored_key)
        elif err:
            st.warning(f"키 자동 로드 실패: {err}")

    # 현재 키 상태 표시
    if has_api_key():
        masked = "●●●●●●●●" + get_api_key()[-4:]
        col_status, col_del = st.columns([4, 1])
        with col_status:
            st.markdown(
                f'<div class="success-banner">✅ API 키 등록됨 &nbsp; <code>{masked}</code></div>',
                unsafe_allow_html=True,
            )
        with col_del:
            st.markdown('<div style="height:0.4rem"></div>', unsafe_allow_html=True)
            if st.button("🗑️ 삭제", key="btn_del_key"):
                clear_api_key()
                ok, err = delete_api_key(file_key)
                if not ok:
                    st.warning(f"Supabase 삭제 실패: {err}")
                st.rerun()
    else:
        # 키 입력 폼
        new_key = st.text_input(
            "Gemini API 키 입력",
            type="password",
            placeholder="AIza...",
            help="Google AI Studio (aistudio.google.com) 에서 무료 발급",
        )

        if st.button("✅ 검증 후 저장", key="btn_save_key"):
            if not new_key.strip():
                st.error("API 키를 입력하세요.")
            else:
                with st.spinner("키 검증 중..."):
                    valid, err = validate_api_key(new_key.strip())
                if valid:
                    set_api_key(new_key.strip())
                    ok, save_err = save_api_key(file_key, new_key.strip())
                    if ok:
                        st.success("✅ 키 검증 완료, 암호화 저장되었습니다.")
                    else:
                        st.warning(f"✅ 키는 유효하지만 저장 실패 (세션 중 유지): {save_err}")
                    st.rerun()
                else:
                    st.error(f"❌ 유효하지 않은 키: {err}")

        st.markdown(
            '<div class="info-banner">'
            '🔒 <b>보안 안내</b><br>'
            '· 키 검증 후 AES-256으로 암호화되어 저장됩니다<br>'
            '· 관리자도 평문 키를 직접 볼 수 없습니다<br>'
            '· <a href="https://aistudio.google.com/app/apikey" target="_blank" '
            'style="color:#90caf9">Google AI Studio</a>에서 무료로 발급하세요'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── JSON 내보내기/불러오기 ──────────────────────────────────────
    st.markdown('<div class="section-label">포트폴리오 JSON 내보내기</div>', unsafe_allow_html=True)
    json_str = json.dumps(portfolio._data, ensure_ascii=False, indent=2)
    st.download_button(
        "⬇️ portfolio.json 다운로드",
        data=json_str, file_name="portfolio.json", mime="application/json",
    )

    st.markdown('<div class="section-label">포트폴리오 JSON 불러오기</div>', unsafe_allow_html=True)
    uploaded      = st.file_uploader("portfolio.json 업로드", type=["json"], key="json_uploader")
    last_uploaded = st.session_state.get("_last_uploaded_name")

    if uploaded is not None and uploaded.name != last_uploaded:
        try:
            raw_bytes = uploaded.read()
            if not raw_bytes:
                st.error("업로드된 파일이 비어 있습니다.")
            else:
                data = json.loads(raw_bytes.decode("utf-8"))
                if not isinstance(data, dict) or "holdings" not in data:
                    st.error("올바른 portfolio.json 형식이 아닙니다.")
                else:
                    portfolio._data = data
                    portfolio.save()
                    for k in ("prices_data", "buy_result", "bt_result"):
                        st.session_state.pop(k, None)
                    st.session_state["_last_uploaded_name"] = uploaded.name
                    st.success("✅ 포트폴리오를 불러왔습니다!")
        except Exception as e:
            st.error(f"파일 읽기 오류: {e}")
