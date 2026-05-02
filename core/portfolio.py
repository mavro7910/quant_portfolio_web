## """
core/portfolio.py

포트폴리오 데이터 관리 (JSON 저장/로드).

변경사항:

- [BUG FIX] _load: 파일이 없을 때 self._data 미초기화 상태로 save() 호출
  → RecursionError / AttributeError 발생 가능 → 순서 수정
- [BUG FIX] save: 파일 쓰기 실패 시 무음 실패(silent fail) → 예외 전파로 변경
- [BUG FIX] set_holding: shares 타입이 str로 넘어올 경우 float 변환 실패
  → 명시적 변환 + 예외 처리 추가
- [BUG FIX] Streamlit Cloud 환경에서 sys.frozen 체크가 무의미하고
  **file** 기반 경로가 /mount/src/… 로 잡혀 data/ 폴더 생성 실패
  → 환경변수 또는 홈 디렉토리 기반 경로로 폴백
- [개선] weekly_budget setter: 음수/0 방지
- [개선] _load: 타입 검증 강화 (holdings가 dict가 아닌 경우 초기화)
  """

from **future** import annotations

import json
import os
import sys
from pathlib import Path

def get_default_path() -> Path:
"""
실행 환경(EXE / 스크립트 / Streamlit Cloud)에 맞는 기본 저장 경로 반환.

```
우선순위:
1. 환경변수 PORTFOLIO_PATH (배포 환경 커스터마이징용)
2. EXE 빌드 환경: 실행 파일과 같은 폴더
3. 일반 스크립트: 프로젝트 루트 data/
4. 쓰기 불가능한 경우: 홈 디렉토리 ~/.quant_portfolio/
"""
# 1. 환경변수 우선
env_path = os.environ.get("PORTFOLIO_PATH")
if env_path:
    return Path(env_path)

# 2. EXE 빌드
if getattr(sys, "frozen", False):
    base_path = Path(sys.executable).parent
    return base_path / "data" / "portfolio.json"

# 3. 일반 스크립트 -- 프로젝트 루트
candidate = Path(__file__).parent.parent / "data" / "portfolio.json"
try:
    candidate.parent.mkdir(parents=True, exist_ok=True)
    # 쓰기 테스트
    test_file = candidate.parent / ".write_test"
    test_file.touch()
    test_file.unlink()
    return candidate
except OSError:
    pass

# 4. 폴백: 홈 디렉토리 (Streamlit Cloud, 읽기전용 파일시스템 등)
return Path.home() / ".quant_portfolio" / "portfolio.json"
```

class Portfolio:

```
def __init__(self, path: Path | str | None = None):
    self.path = Path(path) if path else get_default_path()
    self._ensure_directory()
    self._data: dict = {}       # 먼저 초기화 후 load
    self._data = self._load()

def _ensure_directory(self) -> None:
    """폴더가 없으면 생성"""
    try:
        self.path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass  # 읽기전용 환경에서는 무시 (홈 디렉토리 폴백이 처리)

# ──────────────────────────────
# 영속성 및 경로 관리
# ──────────────────────────────

def _load(self) -> dict:
    if self.path.exists():
        try:
            with open(self.path, encoding="utf-8") as f:
                content = json.load(f)

            if not isinstance(content, dict):
                return self._get_default_structure()

            # 필수 키 검증 및 기본값 보장
            content.setdefault("holdings", {})
            content.setdefault("benchmarks", ["QQQM", "XLK"])
            content.setdefault("weekly_budget", 100_000)

            # 타입 검증
            if not isinstance(content["holdings"], dict):
                content["holdings"] = {}
            if not isinstance(content["benchmarks"], list):
                content["benchmarks"] = ["QQQM", "XLK"]
            if not isinstance(content["weekly_budget"], (int, float)):
                content["weekly_budget"] = 100_000

            return content

        except (json.JSONDecodeError, OSError, KeyError):
            pass

    # 파일이 없거나 오류 → 기본 구조 생성 후 저장
    default_data = self._get_default_structure()
    self._data = default_data   # save() 가 _data를 참조하므로 먼저 할당
    self.save()
    return default_data

def _get_default_structure(self) -> dict:
    return {
        "holdings": {},
        "benchmarks": ["QQQM", "XLK"],
        "weekly_budget": 100_000,
    }

def save(self) -> None:
    """현재 데이터를 JSON 파일로 저장. 실패 시 예외 전파."""
    self._ensure_directory()
    with open(self.path, "w", encoding="utf-8") as f:
        json.dump(self._data, f, ensure_ascii=False, indent=2)

def relocate(self, new_path: str | Path) -> None:
    """데이터 파일을 새 위치로 옮기고 경로를 업데이트."""
    self.path = Path(new_path)
    self.save()

# ──────────────────────────────
# 보유 종목 관리
# ──────────────────────────────

@property
def holdings(self) -> dict[str, float]:
    return self._data.setdefault("holdings", {})

def set_holding(self, ticker: str, shares: float | str) -> None:
    ticker = ticker.upper().strip()
    try:
        shares = float(shares)
    except (TypeError, ValueError):
        raise ValueError(f"수량이 올바르지 않습니다: {shares!r}")

    if shares <= 0:
        self.holdings.pop(ticker, None)
    else:
        self.holdings[ticker] = shares

def remove_holding(self, ticker: str) -> None:
    self.holdings.pop(ticker.upper().strip(), None)

def tickers(self) -> list[str]:
    return list(self.holdings.keys())

# ──────────────────────────────
# 설정 값 관리
# ──────────────────────────────

@property
def weekly_budget(self) -> int:
    return int(self._data.get("weekly_budget", 100_000))

@weekly_budget.setter
def weekly_budget(self, v: int) -> None:
    v = int(v)
    if v <= 0:
        raise ValueError("주간 투자금은 0보다 커야 합니다.")
    self._data["weekly_budget"] = v

@property
def benchmarks(self) -> list[str]:
    return self._data.setdefault("benchmarks", ["QQQM", "XLK"])

@benchmarks.setter
def benchmarks(self, v: list[str]) -> None:
    self._data["benchmarks"] = [b.upper().strip() for b in v if b.strip()]

def __repr__(self) -> str:
    return (
        f"Portfolio({len(self.holdings)} tickers, "
        f"budget={self.weekly_budget:,} KRW, "
        f"path={self.path})"
    )
```