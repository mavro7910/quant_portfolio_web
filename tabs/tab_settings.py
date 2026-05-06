"""tabs/tab_settings.py — 설정 탭 (API 키 관리 포함)"""

import json
import streamlit as st

from core.portfolio import Portfolio
from core.secrets_store import (
    load_api_key, save_api_key, delete_api_key,
    load_finnhub_key, save_finnhub_key, delete_finnhub_key,
    load_marketaux_key, save_marketaux_key, delete_marketaux_key,
)
from utils.ai_client import (
    set_api_key, get_api_key, has_api_key, clear_api_key, validate_api_key,
    set_finnhub_key, get_finnhub_key, has_finnhub_key, clear_finnhub_key, validate_finnhub_key,
    set_marketaux_key, get_marketaux_key, has_marketaux_key, clear_marketaux_key, validate_marketaux_key,
)


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

    # ── Supabase 연결 테스트 (레거시 - 숨김) ──────────────────────────
    if st.session_state.get("_show_debug"):
        st.markdown('<div class="section-label">Supabase 연결 테스트</div>', unsafe_allow_html=True)
        if st.button("🔌 연결 테스트", key="btn_test_supabase"):
            try:
                from supabase import create_client
                import streamlit as st_inner
                url = st_inner.secrets["SUPABASE_URL"]
                key = st_inner.secrets["SUPABASE_KEY"]
                sb = create_client(url, key)
                res = sb.table("user_secrets").select("uid").limit(1).execute()
                st.success(f"✅ Supabase 연결 성공!")
            except KeyError as e:
                st.error(f"❌ secrets에 {e} 없음")
            except Exception as e:
                st.error(f"❌ 연결 실패: {e}")

    # ── 계정 정보 ──────────────────────────────────────────────────
    st.markdown('<div class="section-label">계정 정보</div>', unsafe_allow_html=True)
    st.markdown(f"""
<div class="info-banner">
    👤 <b>로그인 계정:</b> {user_name} ({user_email})<br>
    💾 <b>데이터 저장 경로:</b> <code>portfolio_{file_key}.json</code>
</div>
""", unsafe_allow_html=True)

    # ── AI API 키 ──────────────────────────────────────────────────
    st.markdown('<div class="section-label">🤖 AI 시그널 API 키</div>', unsafe_allow_html=True)

    # 저장 결과 메시지
    if "key_save_msg" in st.session_state:
        msg_type, msg_text = st.session_state.pop("key_save_msg")
        if msg_type == "success":
            st.success(msg_text)
        else:
            st.error(msg_text)

    # 세션에 키 없으면 Supabase에서 자동 로드
    if not has_api_key():
        stored_key, err = load_api_key(file_key)
        if stored_key:
            set_api_key(stored_key)
        elif err:
            st.warning(f"Gemini 키 자동 로드 실패: {err}")

    if not has_finnhub_key():
        stored_fh, _ = load_finnhub_key(file_key)
        if stored_fh:
            set_finnhub_key(stored_fh)

    if not has_marketaux_key():
        stored_mx, _ = load_marketaux_key(file_key)
        if stored_mx:
            set_marketaux_key(stored_mx)

    # 현재 상태 표시
    col_g, col_f, col_mx = st.columns(3)
    with col_g:
        if has_api_key():
            masked = "●●●●" + get_api_key()[-4:]
            st.markdown(f'<div class="success-banner">✅ Gemini <code>{masked}</code></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="warn-banner">⚠️ Gemini 키 없음</div>', unsafe_allow_html=True)
    with col_f:
        if has_finnhub_key():
            masked_fh = "●●●●" + get_finnhub_key()[-4:]
            st.markdown(f'<div class="success-banner">✅ Finnhub <code>{masked_fh}</code></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="warn-banner">⚠️ Finnhub 키 없음</div>', unsafe_allow_html=True)
    with col_mx:
        if has_marketaux_key():
            masked_mx = "●●●●" + get_marketaux_key()[-4:]
            st.markdown(f'<div class="success-banner">✅ Marketaux <code>{masked_mx}</code></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="warn-banner">⚠️ Marketaux 키 없음 (선택)</div>', unsafe_allow_html=True)

    # 입력 폼
    col_k1, col_k2, col_k3 = st.columns(3)
    with col_k1:
        new_gemini = st.text_input(
            "Gemini API 키",
            type="password",
            placeholder="AIza...",
            help="aistudio.google.com 에서 무료 발급",
            key="inp_gemini_key",
        )
    with col_k2:
        new_finnhub = st.text_input(
            "Finnhub API 키",
            type="password",
            placeholder="d1abc123...",
            help="finnhub.io/register 에서 무료 발급",
            key="inp_finnhub_key",
        )
    with col_k3:
        new_marketaux = st.text_input(
            "Marketaux API 키 (선택)",
            type="password",
            placeholder="marketaux 키...",
            help="marketaux.com 에서 무료 발급 (뉴스 품질 향상)",
            key="inp_marketaux_key",
        )

    col_save, col_del = st.columns([3, 1])
    with col_save:
        if st.button("✅ 검증 후 저장", key="btn_save_keys", use_container_width=True):
            errors = []
            saved  = []

            if new_gemini.strip():
                valid, err = validate_api_key(new_gemini.strip())
                if valid:
                    set_api_key(new_gemini.strip())
                    ok, save_err = save_api_key(file_key, new_gemini.strip())
                    if ok:
                        saved.append("Gemini")
                    else:
                        errors.append(f"Gemini 저장 실패: {save_err}")
                else:
                    errors.append(f"Gemini: {err}")

            if new_finnhub.strip():
                valid_fh, err_fh = validate_finnhub_key(new_finnhub.strip())
                if valid_fh:
                    set_finnhub_key(new_finnhub.strip())
                    ok_fh, save_err_fh = save_finnhub_key(file_key, new_finnhub.strip())
                    if ok_fh:
                        saved.append("Finnhub")
                    else:
                        errors.append(f"Finnhub 저장 실패: {save_err_fh}")
                else:
                    errors.append(f"Finnhub: {err_fh}")

            if new_marketaux.strip():
                valid_mx, err_mx = validate_marketaux_key(new_marketaux.strip())
                if valid_mx:
                    set_marketaux_key(new_marketaux.strip())
                    ok_mx, save_err_mx = save_marketaux_key(file_key, new_marketaux.strip())
                    if ok_mx:
                        saved.append("Marketaux")
                    else:
                        errors.append(f"Marketaux 저장 실패: {save_err_mx}")
                else:
                    errors.append(f"Marketaux: {err_mx}")

            if not new_gemini.strip() and not new_finnhub.strip() and not new_marketaux.strip():
                st.error("키를 하나 이상 입력하세요.")
            else:
                if saved:
                    st.session_state["key_save_msg"] = ("success", f"✅ {', '.join(saved)} 키 저장 완료!")
                if errors:
                    st.session_state["key_save_msg"] = ("error", "\n".join(errors))
                st.rerun()

    with col_del:
        if has_api_key() or has_finnhub_key() or has_marketaux_key():
            if st.button("🗑️ 전체 삭제", key="btn_del_keys", use_container_width=True):
                clear_api_key()
                clear_finnhub_key()
                clear_marketaux_key()
                delete_api_key(file_key)
                delete_finnhub_key(file_key)
                delete_marketaux_key(file_key)
                st.rerun()

    st.markdown(
        '<div class="info-banner">'
        '🔒 키는 암호화되어 안전하게 저장됩니다. 관리자도 원문을 볼 수 없어요.<br>'
        '· <a href="https://aistudio.google.com/app/apikey" target="_blank" style="color:#90caf9">Gemini 발급</a>'
        ' &nbsp;·&nbsp; '
        '<a href="https://finnhub.io/register" target="_blank" style="color:#90caf9">Finnhub 발급</a>'
        ' &nbsp;·&nbsp; '
        '<a href="https://www.marketaux.com/register" target="_blank" style="color:#90caf9">Marketaux 발급 (무료, 뉴스 품질↑)</a>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── JSON 내보내기/불러오기    # ── JSON 내보내기/불러오기 ──────────────────────────────────────
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
