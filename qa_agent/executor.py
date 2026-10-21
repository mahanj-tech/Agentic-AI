"""Runs scenarios: one isolated browser context per attempt, evidence on every step,
deterministic checks, flake re-run, then (only for failures) an LLM adjudication."""
from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

from .config import cfg
from . import oracles, verifier
from .models import Action, ScenarioResult, Scenario, StepResult
from .runtime import BrowserPool, Session, parse_number

console = Console()


def describe(a: Action) -> str:
    if a.note:
        return a.note
    t = f"'{a.target}'" if a.target else ""
    return {
        "goto": f"Open {a.value}",
        "click": f"Click {t}",
        "fill": f"Enter '{a.value}' into {t}" if a.value else f"Clear {t}",
        "select": f"Select '{a.value}' in {t}",
        "check": f"Tick {t}",
        "uncheck": f"Untick {t}",
        "press": f"Press {a.value} in {t}",
        "wait_for_text": f"Wait until '{a.value}' appears",
        "capture": f"Read {t} as {a.var}",
        "reload": "Reload the page",
        "set_viewport": f"Resize the window to {a.value}",
        "double_click": f"Double-click {t} rapidly",
        "back": "Press the browser Back button",
    }.get(a.op, a.op)


def resolve_value(raw: str | None, variables: dict) -> str | None:
    """'=<expr>' values are computed from captured variables, e.g. '={bal} + 50' -> '1250.75'."""
    if raw is None or not raw.startswith("="):
        return raw
    val = oracles.safe_eval(raw[1:], variables)
    return f"{val:.2f}" if isinstance(val, float) or isinstance(val, int) else str(val)


SELECT_JS = """(el, want) => {
  const w = want.trim().toLowerCase();
  const opts = Array.from(el.options);
  const hit = opts.find(o => o.value === want) || opts.find(o => o.text.trim().toLowerCase() === w)
           || opts.find(o => o.text.toLowerCase().includes(w)) || opts.find(o => o.value.toLowerCase().includes(w));
  if (!hit) return null;
  el.value = hit.value;
  el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));
  return hit.text.trim();
}"""


def _do(s: Session, a: Action, variables: dict) -> tuple[str | None, str | None]:
    """Perform one action. Returns (resolved_by, captured_value)."""
    if a.op == "goto":
        s.goto(a.value or "/")
        return "url", None
    if a.op == "reload":
        s.page.reload()
        s.settle()
        return "reload", None
    if a.op == "set_viewport":
        w, h = (int(x) for x in (a.value or "390x844").lower().split("x"))
        s.page.set_viewport_size({"width": w, "height": h})
        s.settle()
        return "viewport", None
    if a.op == "back":
        s.page.go_back()
        s.settle()
        return "history", None
    if a.op == "wait_for_text":
        s.page.get_by_text(a.value or "").first.wait_for(state="visible", timeout=cfg.action_timeout_ms)
        return "text", None

    if a.op == "capture" and (a.value or "").lower() in {"errors", "messages"}:
        # snapshot what the user is told right now (before navigating away to re-read state)
        s.settle()
        if a.value.lower() == "errors":
            txt = " | ".join(s.error_state())
        else:
            snap = s.snapshot()
            txt = " | ".join(snap.get("alerts", []) + s.error_state())
        variables[a.var or a.value.lower()] = txt
        return "page-state", repr(txt[:160])

    many = a.op == "capture" and (a.value or "").lower() == "count"
    if many:
        # counting: zero matching elements is a valid observation, not a missing element
        s.settle()
        loc, how = s.resolve(a.target or "", "count", allow_many=True, timeout_ms=1500)
        n = 0 if loc is None else loc.count()
        variables[a.var or "value"] = n
        return (how if loc is not None else "count(0)"), repr(n)
    loc, how = s.resolve(a.target or "", f"{a.op} {a.value or ''}".strip(), allow_many=many)
    if loc is None:
        raise LookupError(f"element not found: '{a.target}' (tried testid/label/placeholder/role/text + LLM pick)")

    if a.op == "click":
        loc.scroll_into_view_if_needed()
        loc.click()
    elif a.op == "double_click":
        loc.scroll_into_view_if_needed()
        loc.dblclick()
    elif a.op == "fill":
        value = resolve_value(a.value, variables)
        loc.fill("")
        if value:
            loc.fill(value)
        if value != a.value:
            s.settle()
            return how, f"entered {value!r}"
    elif a.op == "select":
        # option labels often contain live data (e.g. balances), so match exact, then partial, then value
        picked = loc.evaluate(SELECT_JS, a.value or "")
        if picked is None:
            raise LookupError(f"no option matching '{a.value}' in {a.target}")
        s.settle()
        return how, f"selected {picked!r}"
    elif a.op == "check":
        loc.check()
    elif a.op == "uncheck":
        loc.uncheck()
    elif a.op == "press":
        loc.press(a.value or "Enter")
    elif a.op == "capture":
        kind = (a.value or "text").lower()
        if kind == "count":
            val = loc.count()
        else:
            txt = loc.input_value() if loc.evaluate("e => ['INPUT','SELECT','TEXTAREA'].includes(e.tagName)") else loc.inner_text()
            val = parse_number(txt) if kind == "number" else txt.strip()
        variables[a.var or "value"] = val
        return how, repr(val)
    s.settle()
    return how, None


def run_once(pool: BrowserPool, sc: Scenario, shot_dir: Path, attempt: int) -> ScenarioResult:
    s =pool.session(shot_dir, f"{sc.id}_a{attempt}")
    variables: dict = {}
    steps: list[StepResult] = []
    blocked: str | None = None
    try:
        s.open_app()
        steps.append(StepResult(index=0, op="open", note=f"Open {cfg.target_url} and click '{cfg.entry_button}'",
                                screenshot=s.screenshot("start"), url=s.page.url))
        net_start = len(s.network)
        for i, a in enumerate(sc.steps, 1):
            sr = StepResult(index=i, op=a.op, target=a.target, value=a.value, note=describe(a))
            try:
                sr.resolved_by, sr.captured = _do(s, a, variables)
            except Exception as e:
                sr.ok = False
                sr.error = f"{type(e).__name__}: {str(e).splitlines()[0][:220]}"
                blocked = f"step {i} ({describe(a)}) could not run: {sr.error}"
            if a.op != "capture" or not sr.ok:
                sr.screenshot = s.screenshot(f"s{i}_{a.op}")
            sr.url = s.page.url
            steps.append(sr)
            if blocked:
                break

        final_shot = s.screenshot("final")
        checks = []
        if not blocked:
            checks = [oracles.evaluate(c, s, variables, net_start, final_shot, sc.expected) for c in sc.checks]

        res = ScenarioResult(scenario=sc, status="UNVERIFIED", steps=steps, checks=checks, variables=variables,
                             network=[n for n in s.network if n["type"] != "document"][-40:],
                             console_errors=s.console_errors[-20:], attempts=attempt)
        if blocked:
            res.reason = blocked
        elif not checks:
            res.reason = "scenario has no checks"
        elif any(c.passed is False for c in checks):
            res.status = "FAILED"
            res.reason = "; ".join(f"{c.description}: expected {c.expected}, observed {c.observed}"
                                   for c in checks if c.passed is False)
        elif any(c.passed is None for c in checks):
            res.reason = "; ".join(f"{c.description}: {c.observed}" for c in checks if c.passed is None)
        else:
            res.status = "PASSED"
            res.reason = "all checks passed"
        steps[-1].screenshot = steps[-1].screenshot or final_shot
        return res
    finally:
        s.close()


def run_scenario(pool: BrowserPool, sc: Scenario, shot_dir: Path) -> ScenarioResult:
    t0 = time.time()
    res = run_once(pool, sc, shot_dir, 1)
    if res.status == "FAILED" and cfg.rerun_failures:
        again = run_once(pool, sc, shot_dir, 2)
        if again.status == "PASSED":
            res.flaky = True
            res.status = "UNVERIFIED"
            res.reason = "inconsistent: failed on attempt 1, passed on attempt 2 (possible race/flaky behaviour). " + res.reason
        res.attempts = 2
    if cfg.adjudicate and (res.status == "FAILED" or (res.status == "UNVERIFIED" and res.reason.startswith("step"))):
        verifier.adjudicate(res)
    res.duration_s = round(time.time() - t0, 2)
    colour = {"PASSED": "green", "FAILED": "red", "UNVERIFIED": "yellow"}[res.status]
    from rich.markup import escape
    console.print(f"  [{colour}]{res.status:<10}[/{colour}] {sc.id} {escape('[' + sc.type + ']')} {escape(sc.title)}"
                  + (f"  [dim]{escape(res.reason[:110])}[/dim]" if res.status != "PASSED" else ""))
    return res
