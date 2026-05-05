"""
core/secrets_store.py

- API 키: AES-256-GCM 암호화 → user_secrets 테이블
- 시그널 캐시: signal_cache 테이블 (날짜별 저장)
"""

from __future__ import annotations
import base64
import os
import json
from datetime import date
import streamlit as st


def _derive_key(uid: str) -> bytes:
    import hmac, hashlib
    secret = ""
    try:
        secret = st.secrets.get("ES", "")
    except Exception:
        secret = os.getenv("ES", "")
    if not secret:
        raise ValueError("st.secrets['ES'] 가 설정되지 않았습니다.")
    raw = hmac.new(secret.encode(), uid.encode(), hashlib.sha256).digest()
    return hashlib.sha256(raw).digest()


def _encrypt(plaintext: str, uid: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _derive_key(uid)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt(blob: str, uid: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = _derive_key(uid)
    raw = base64.b64decode(blob)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def _get_supabase():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


# ─────────────────────────────────────────────
# API 키 (user_secrets 테이블)
# ─────────────────────────────────────────────

def load_api_key(uid: str) -> tuple[str | None, str | None]:
    """
    복호화된 키, 에러메시지 반환.
    성공: (key, None) / 실패: (None, error_msg)
    """
    sb = _get_supabase()
    if not sb:
        return None, "Supabase 미연결"
    try:
        res = sb.table("user_secrets").select("s").eq("uid", uid).execute()
        if res.data:
            return _decrypt(res.data[0]["s"], uid), None
        return None, None  # 저장된 키 없음
    except Exception as e:
        return None, str(e)


def save_api_key(uid: str, raw_key: str) -> tuple[bool, str | None]:
    """
    성공: (True, None) / 실패: (False, error_msg)
    """
    sb = _get_supabase()
    if not sb:
        return False, "Supabase 미연결 — st.secrets에 SUPABASE_URL/KEY 확인"
    try:
        encrypted = _encrypt(raw_key, uid)
        sb.table("user_secrets").upsert(
            {"uid": uid, "s": encrypted},
            on_conflict="uid",
        ).execute()
        return True, None
    except Exception as e:
        return False, str(e)


def delete_api_key(uid: str) -> tuple[bool, str | None]:
    sb = _get_supabase()
    if not sb:
        return False, "Supabase 미연결"
    try:
        sb.table("user_secrets").delete().eq("uid", uid).execute()
        return True, None
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# 시그널 캐시 (signal_cache 테이블)
# ─────────────────────────────────────────────

def load_signal_cache(uid: str) -> tuple[list | None, str | None]:
    """
    오늘 날짜 캐시 로드.
    성공: (data, None) / 없음: (None, None) / 실패: (None, error_msg)
    """
    sb = _get_supabase()
    if not sb:
        return None, "Supabase 미연결"
    try:
        today = date.today().isoformat()
        res = (
            sb.table("signal_cache")
            .select("data")
            .eq("uid", uid)
            .eq("cache_date", today)
            .execute()
        )
        if res.data:
            return res.data[0]["data"], None
        return None, None
    except Exception as e:
        return None, str(e)


def save_signal_cache(uid: str, data: list) -> tuple[bool, str | None]:
    """
    오늘 날짜로 분석 결과 저장.
    """
    sb = _get_supabase()
    if not sb:
        return False, "Supabase 미연결"
    try:
        today = date.today().isoformat()
        sb.table("signal_cache").upsert(
            {"uid": uid, "cache_date": today, "data": data},
            on_conflict="uid,cache_date",
        ).execute()
        return True, None
    except Exception as e:
        return False, str(e)
