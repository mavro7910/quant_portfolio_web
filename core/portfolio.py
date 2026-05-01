"""
core/portfolio.py
-----------------
포트폴리오 데이터 관리 (JSON 저장/로드).
경로 변경 기능을 지원하며, 파일 부재 시 기본 구조를 생성합니다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

def get_default_path() -> Path:
    """EXE 실행 환경과 스크립트 실행 환경을 모두 고려한 기본 저장 경로"""
    # EXE로 빌드된 경우 실행 파일과 같은 폴더의 data 디렉토리 사용
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent.parent
    
    return base_path / "data" / "portfolio.json"

class Portfolio:
    def __init__(self, path: Path | str | None = None):
        # 경로가 지정되지 않으면 환경에 맞는 기본 경로 사용
        self.path = Path(path) if path else get_default_path()
        self._ensure_directory()
        self._data: dict = self._load()

    def _ensure_directory(self) -> None:
        """폴더가 없으면 생성"""
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────
    #  영속성 및 경로 관리
    # ──────────────────────────────

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    content = json.load(f)
                    # 필수 키 검증 및 기본값 보장
                    if not isinstance(content, dict): return self._get_default_structure()
                    content.setdefault("holdings", {})
                    content.setdefault("benchmarks", ["QQQM", "XLK"])
                    content.setdefault("weekly_budget", 100000)
                    return content
            except (json.JSONDecodeError, OSError):
                pass
        
        # 파일이 없거나 오류 발생 시 기본 구조 반환 및 즉시 저장
        default_data = self._get_default_structure()
        self._data = default_data
        self.save()
        return default_data

    def _get_default_structure(self) -> dict:
        return {"holdings": {}, "benchmarks": ["QQQM", "XLK"], "weekly_budget": 100000}

    def save(self) -> None:
        """현재 데이터 저장"""
        self._ensure_directory()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def relocate(self, new_path: str | Path) -> None:
        """데이터 파일을 새 위치로 옮기고 경로를 업데이트함"""
        new_path = Path(new_path)
        # 기존 데이터를 새 경로에 저장
        self.path = new_path
        self.save()

    # ──────────────────────────────
    #  보유 종목 관리
    # ──────────────────────────────

    @property
    def holdings(self) -> dict[str, float]:
        return self._data.setdefault("holdings", {})

    def set_holding(self, ticker: str, shares: float) -> None:
        ticker = ticker.upper().strip()
        if shares <= 0:
            self.holdings.pop(ticker, None)
        else:
            self.holdings[ticker] = float(shares)

    def remove_holding(self, ticker: str) -> None:
        self.holdings.pop(ticker.upper().strip(), None)

    def tickers(self) -> list[str]:
        return list(self.holdings.keys())

    # ──────────────────────────────
    #  설정 값 관리
    # ──────────────────────────────

    @property
    def weekly_budget(self) -> int:
        return int(self._data.get("weekly_budget", 100_000))

    @weekly_budget.setter
    def weekly_budget(self, v: int) -> None:
        self._data["weekly_budget"] = int(v)

    @property
    def benchmarks(self) -> list[str]:
        return self._data.setdefault("benchmarks", ["QQQM", "XLK"])

    @benchmarks.setter
    def benchmarks(self, v: list[str]) -> None:
        self._data["benchmarks"] = [b.upper().strip() for b in v]

    def __repr__(self) -> str:
        return f"Portfolio({len(self.holdings)} tickers, budget={self.weekly_budget:,} KRW)"