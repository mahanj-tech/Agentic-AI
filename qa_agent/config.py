"""Runtime configuration. Every value can be overridden with an environment variable
(or a .env file in the agent/ directory) so nothing secret is ever committed."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:  # pragma: no cover
    pass

AGENT_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    # ---- target -----------------------------------------------------------
    target_url: str = _env("TARGET_URL", "http://localhost:8080")
    prd_path: str = _env("PRD_PATH", "../test-website/PRD.md")
    entry_button: str = _env("ENTRY_BUTTON", "Enter Demo")

    # ---- models (any OpenAI-compatible endpoint: OpenAI, Azure, OpenRouter, Ollama…) ----
    # Three tiers so the expensive model is only used where judgement matters.
    plan_model: str = _env("PLAN_MODEL", "gpt-4.1")        # 1-3 calls per run: requirement + scenario design
    fast_model: str = _env("FAST_MODEL", "gpt-4.1-mini")   # element healing, semantic checks
    judge_model: str = _env("JUDGE_MODEL", "gpt-4.1")      # only for scenarios that FAILED or got BLOCKED
    base_url: str | None = os.getenv("OPENAI_BASE_URL") or None

    # ---- budget / efficiency ------------------------------------------------
    max_usd: float = float(_env("MAX_USD", "1.00"))         # hard stop for LLM spend per run
    use_cache: bool = _bool("LLM_CACHE", True)              # identical prompts are answered from disk
    adjudicate: bool = _bool("ADJUDICATE", True)            # LLM second opinion on failures
    rerun_failures: bool = _bool("RERUN_FAILURES", True)    # flake check before reporting a defect

    # ---- browser ------------------------------------------------------------
    headless: bool = _bool("HEADLESS", True)
    slow_mo_ms: int = int(_env("SLOW_MO_MS", "0"))          # set ~250 for the demo video
    action_timeout_ms: int = int(_env("ACTION_TIMEOUT_MS", "6000"))
    nav_timeout_ms: int = int(_env("NAV_TIMEOUT_MS", "20000"))
    max_explore_pages: int = int(_env("MAX_EXPLORE_PAGES", "15"))
    viewport: dict = field(default_factory=lambda: {"width": 1280, "height": 800})

    # ---- output -------------------------------------------------------------
    out_dir: Path = Path(_env("OUT_DIR", str(AGENT_DIR / "artifacts")))
    cache_dir: Path = Path(_env("CACHE_DIR", str(AGENT_DIR / ".cache")))

    def pricing(self) -> dict:
        return json.loads((AGENT_DIR / "pricing.json").read_text())["models"]


cfg = Config()
