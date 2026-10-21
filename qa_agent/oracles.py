"""Deterministic oracles. These decide PASS/FAIL from observed facts (DOM state, captured
numbers, HTTP traffic) so the verdict does not depend on a model's opinion."""
from __future__ import annotations

import ast
import math
import operator
import re

from .config import cfg
from . import llm
from .models import Check, CheckResult, SemanticVerdict
from .runtime import Session

TOL = 0.005  # money tolerance (half a cent)

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod}
_FUNCS = {"abs": abs, "round": round, "min": min, "max": max}


def _num_eq(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, abs_tol=TOL)
    return a == b


_CMP = {ast.Eq: _num_eq, ast.NotEq: lambda a, b: not _num_eq(a, b), ast.Lt: operator.lt,
        ast.LtE: lambda a, b: a < b or _num_eq(a, b), ast.Gt: operator.gt,
        ast.GtE: lambda a, b: a > b or _num_eq(a, b)}


def safe_eval(expr: str, variables: dict):
    """Evaluate '{after} == {before} - 25.5' style expressions without eval()."""
    missing = [v for v in re.findall(r"\{(\w+)\}", expr) if variables.get(v) is None]
    if missing:
        raise KeyError(f"uncaptured variable(s): {', '.join(missing)}")
    src = re.sub(r"\{(\w+)\}", lambda m: f"__v_{m.group(1)}", expr)
    env = {f"__v_{k}": v for k, v in variables.items()}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in env:
                return env[n.id]
            raise KeyError(n.id)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd, ast.Not)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else (not v if isinstance(n.op, ast.Not) else v)
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, comp in zip(n.ops, n.comparators):
                right = ev(comp)
                if type(op) not in _CMP or not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError(f"unsupported expression element: {ast.dump(n)[:60]}")

    return ev(ast.parse(src, mode="eval"))


def _visible_text(s: Session, target: str | None) -> str:
    if target:
        loc, _ = s.resolve(target, "read text", timeout_ms=2000)
        if loc is None:
            return ""
        try:
            return loc.inner_text()
        except Exception:
            return ""
    try:
        return s.page.inner_text("body")
    except Exception:
        return ""


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


def evaluate(check: Check, s: Session, variables: dict, net_start: int, screenshot: str | None,
             scenario_expected: str) -> CheckResult:
    k = check.kind
    r = CheckResult(kind=k, description=check.description, passed=None)
    try:
        if k in {"text_visible", "text_absent"}:
            body = _norm(_visible_text(s, check.target))
            want = _norm(check.value or "")
            present = want in body
            r.passed = present if k == "text_visible" else not present
            r.expected = f"text '{check.value}' {'visible' if k == 'text_visible' else 'not visible'}"
            r.observed = "present on page" if present else "not found on page"

        elif k in {"element_visible", "element_absent"}:
            loc, how = s.resolve(check.target or "", "check presence", timeout_ms=2500 if k == "element_visible" else 800)
            vis = bool(loc is not None and loc.is_visible())
            r.passed = vis if k == "element_visible" else not vis
            r.expected = f"'{check.target}' {'visible' if k == 'element_visible' else 'absent'}"
            r.observed = f"visible (via {how})" if vis else "not visible"

        elif k == "element_disabled":
            loc, how = s.resolve(check.target or "", "check disabled", timeout_ms=2500)
            if loc is None:
                r.observed = "element not found"
            else:
                dis = loc.is_disabled() or (loc.get_attribute("aria-disabled") == "true")
                r.passed = dis
                r.observed = "disabled" if dis else "enabled"
            r.expected = "disabled"

        elif k == "input_value":
            loc, _ = s.resolve(check.target or "", "read value", timeout_ms=2500)
            val = loc.input_value() if loc is not None else None
            r.passed = val is not None and _norm(val) == _norm(check.value or "")
            r.expected, r.observed = repr(check.value), repr(val)

        elif k == "text_matches":
            txt = _visible_text(s, check.target).strip()
            r.passed = bool(txt) and re.search(check.value or "", txt) is not None
            r.expected, r.observed = f"text matching /{check.value}/", repr(txt[:120])

        elif k == "expr":
            got = safe_eval(check.expr or "", variables)
            r.passed = bool(got)
            used = {v: variables.get(v) for v in re.findall(r"\{(\w+)\}", check.expr or "")}
            r.expected = check.expr or ""
            r.observed = ", ".join(f"{a}={b}" for a, b in used.items())

        elif k == "url_contains":
            r.passed = (check.value or "") in s.page.url
            r.expected, r.observed = f"URL contains '{check.value}'", s.page.url

        elif k == "url_not_contains":
            r.passed = (check.value or "") not in s.page.url
            r.expected, r.observed = f"URL does not contain '{check.value}'", s.page.url

        elif k in {"var_matches", "var_not_matches"}:
            name = (check.target or "").strip("{} ")
            if name not in variables:
                raise KeyError(f"uncaptured variable: {name}")
            txt = re.sub(r"\s+", " ", str(variables[name]))
            m = re.search(check.value or "", txt, re.I)
            r.passed = bool(m) if k == "var_matches" else not m
            r.expected = f"{name} {'matches' if k == 'var_matches' else 'does not match'} /{check.value}/"
            r.observed = repr(txt[:200]) if txt else "(empty)"

        elif k == "text_not_matches":
            txt = _visible_text(s, check.target)
            m = re.search(check.value or "", txt)
            r.passed = m is None
            r.expected = f"no text matching /{check.value}/"
            r.observed = f"found {m.group(0)!r}" if m else "no match"

        elif k == "all_rows_match":
            loc, how = s.resolve(check.target or "", "rows", allow_many=True, timeout_ms=2500)
            # keep tabs (cell separators) so a regex can target a column, e.g. "\tDeposit\t"
            rows = [] if loc is None else [re.sub(r"[ \r\n]+", " ", t).strip() for t in loc.all_inner_texts()]
            bad = [t for t in rows if not re.search(check.value or "", t)]
            if not rows:
                r.passed, r.observed = None, "no rows to inspect"
            else:
                r.passed = not bad
                r.observed = (f"{len(bad)} of {len(rows)} rows do not match, e.g. {bad[0][:110]!r}" if bad
                              else f"all {len(rows)} rows match")
            r.expected = f"every row matches /{check.value}/"

        elif k == "no_horizontal_overflow":
            dims = s.page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
            r.passed = dims[0] <= dims[1] + 1
            r.expected = "page content fits the window width (no sideways scrolling)"
            r.observed = f"content width {dims[0]}px, window {dims[1]}px"

        elif k == "request_count":
            method, _, frag = (check.value or "").partition(" ")
            n = sum(1 for e in s.network[net_start:] if e["method"] == method.upper() and frag in e["url"])
            r.passed = bool(safe_eval(f"{n} {check.expr or '== 1'}", {}))
            r.expected = f"{check.value} sent {check.expr or '== 1'} time(s)"
            r.observed = f"sent {n} time(s)"

        elif k == "error_shown":
            errs = s.error_state()
            hits = errs
            if check.value:
                kw = _norm(check.value)
                keyword_hits = [e for e in errs if kw in _norm(e)]
                if keyword_hits:
                    hits = keyword_hits
                elif not errs and kw in _norm(_visible_text(s, None)):
                    hits = [f"text containing '{check.value}' is visible"]
                # an error with different wording still counts as an error state
            r.passed = bool(hits)
            r.expected = "a visible validation / error message" + (f" mentioning '{check.value}'" if check.value else "")
            r.observed = "; ".join(hits[:3]) if hits else "no error or validation message visible"

        elif k == "no_server_errors":
            bad = [f"{n['method']} {n['url']} -> {n['status']}" for n in s.network[net_start:] if n["status"] >= 500]
            uncaught = [c for c in s.console_errors if c.startswith("uncaught")]
            r.passed = not bad and not uncaught
            r.expected = "no HTTP 5xx and no uncaught JS exceptions"
            r.observed = "; ".join((bad + uncaught)[:3]) or "none"

        elif k == "semantic":
            r.expected = check.value or ""
            if not screenshot:
                r.observed = "no screenshot available"
            else:
                snap = s.snapshot()
                verdict = llm.structured(
                    "semantic-check", cfg.fast_model,
                    "You verify one UI assertion for a QA agent. Answer strictly from the screenshot and DOM summary. "
                    "If the evidence is insufficient, set holds=false and say what is missing.",
                    [{"type": "text", "text": f"Assertion: {check.value}\nScenario expectation: {scenario_expected}\n"
                                              f"DOM summary: {str(snap)[:3500]}"},
                     llm.image_part(screenshot)],
                    SemanticVerdict)
                r.passed = verdict.holds
                r.observed = verdict.observed + " (model-judged)"
        else:
            r.observed = f"unknown check kind {k}"
    except (llm.BudgetExceeded, llm.LLMUnavailable) as e:
        r.passed, r.observed = None, f"not evaluated: {e}"
    except KeyError as e:
        r.passed, r.observed = None, f"not evaluated: {e}"
    except Exception as e:
        r.passed, r.observed = None, f"not evaluated: {type(e).__name__}: {str(e)[:150]}"
    return r
