"""PRD -> verifiable requirements -> executable scenarios (normal / negative / edge).

Two model calls (plus one per extra batch of requirements). The long, static part of the
prompt (instructions + site map) comes first so OpenAI's automatic prompt caching bills
repeat batches at the cached-input rate.
"""
from __future__ import annotations

import re

from rich.console import Console

from .config import cfg
from . import llm
from .models import RequirementSet, ScenarioSet, TestPlan

console = Console()

REQ_SYSTEM = """You are a QA analyst. Extract every verifiable requirement from the PRD.
Rules:
- One requirement = one testable behaviour. Split compound sentences.
- Include implied requirements a careful tester would hold the app to (e.g. a successful transfer must
  change both balances and add a transaction record; invalid amounts must be rejected with a visible message;
  filters must show only matching rows). Mark those explicit=false.
- Keep numbers, limits, formats, field names and messages exactly as the PRD states them.
- prd_quote: the shortest PRD fragment (max 15 words) the requirement comes from.
- Ids REQ-01, REQ-02, … in PRD order."""

SCENARIO_SYSTEM = """You design executable browser tests for a QA agent. The agent drives a real browser with
the ACTION DSL below and judges results ONLY with the CHECK DSL. Write scenarios that would expose real defects.

ACTION DSL (each step: op, target, value, var, note)
- goto(value=path or '#hash')        - click(target)                 - fill(target, value)  (value '' = clear)
- select(target, value=option label) - check/uncheck(target)         - press(target, value='Enter')
- wait_for_text(value)               - reload      - back (browser Back)
- set_viewport(value='390x844')      - double_click(target)  rapid second click, for duplicate-submission tests
- VALUES may be computed: value '={bal_before} + 50' fills balance+50 (2 decimals). Use this for boundaries
  relative to live data: exactly the balance, balance + 0.01, etc.
- select matches the option label exactly, then partially, then by value: use the stable part of the label
  (e.g. 'Everyday Checking') because labels often include live balances.
- capture(target, var, value='number'|'text'|'count')  stores a value for later checks.
  'count' counts ALL elements matching target -> use a row selector such as css=#tx-table tbody tr.
TARGETS: prefer selectors listed in the SITE MAP (testid=…, css=#id, css=input[name=…]); otherwise
label=…, placeholder=…, role=button[name=…], text=…, or the exact visible label. Never invent ids.

CHECK DSL (each check: kind, target, value, expr, description)
- expr: arithmetic/comparison over captured vars, e.g. "{from_after} == {from_before} - 125.50",
  "{rows_after} == {rows_before} + 1", "{from_after} == {from_before}". Money compares with 0.005 tolerance.
- text_visible / text_absent (value, optional target scope)   - element_visible / element_absent / element_disabled (target)
- all_rows_match(target=row selector, value=regex): EVERY row must match (filters). Rows are whitespace-normalised.
- capture(value='errors'|'messages', var=…) snapshots the visible error / status text right after an action;
  then var_matches(target=var, value=regex) / var_not_matches. Use this to check the message BEFORE navigating
  elsewhere to re-read balances.
- text_not_matches(value=regex, optional target): e.g. leaked identifiers   - url_not_contains(value)
- no_horizontal_overflow: page fits the current viewport (use after set_viewport)
- request_count(value='POST /api/transfers', expr='== 1'): requests sent during the scenario
- input_value(target, value)   - text_matches(target, value=regex) for formats   - url_contains(value)   - no_server_errors
- error_shown(value=optional keyword): a visible validation/alert/error state exists.
- semantic(value): LLM judges a screenshot. COSTS MONEY and is less reliable: use only when nothing else can verify it.

DESIGN RULES
1. A success message is never proof. Verify state: capture balances/row counts BEFORE and AFTER and assert with expr.
2. State is shared between tests and may already have been changed by other tests, so assert RELATIVE deltas,
   never absolute balances from the PRD seed data (unless the requirement is about initial data).
3. Negative tests must assert BOTH that an error is shown AND that state did not change
   (e.g. "{bal_after} == {bal_before}" and "{rows_after} == {rows_before}").
4. Edge cases: boundary values (0, 0.01, exactly the balance, balance + 0.01, max limits), decimals with
   >2 places, empty, whitespace, non-numeric, very large numbers, same source and destination, rapid repeat.
5. For filters/search: capture count with the filter applied, and assert every visible row matches
   (e.g. text_absent of a value that must not appear inside the table target).
6. Keep each scenario 3-14 steps. Use small amounts (1-150) so balances last across the suite.
7. Every requirement gets at least one scenario; high-priority ones get normal + negative + edge.
8. Use 'note' to write each step as a human reproduction step.
9. Session/access requirements: test refresh (reload), logout, then goto a protected path directly, and Back.
10. Date filters: boundaries are inclusive - pick a start/end equal to the date of a row visible in the site map
    and assert that row is present. Also test a range with no rows (empty state) and clearing filters.
11. Duplicate submission: double_click the submit button, then request_count == 1 and the delta applied once.
12. If a requirement cannot be exercised through the UI at all, still write a scenario with a single
   element_visible check for the feature so its absence is reported."""


def extract_requirements(prd: str) -> RequirementSet:
    return llm.structured("requirement-extraction", cfg.plan_model, REQ_SYSTEM, f"PRD:\n\n{prd}", RequirementSet)


def design_scenarios(prd: str, reqs: RequirementSet, site_text: str, batch: int = 6) -> ScenarioSet:
    static = f"{SCENARIO_SYSTEM}\n\nSITE MAP (explored live; selectors are real):\n{site_text}\n\nFULL PRD:\n{prd}"
    out: list = []
    for i in range(0, len(reqs.requirements), batch):
        chunk = reqs.requirements[i:i + batch]
        user = ("Write scenarios for these requirements (ids SC-<req number>-<letter>):\n" +
                "\n".join(f"- {r.id} [{r.priority}] {r.title}: {r.text}" for r in chunk))
        part = llm.structured("scenario-design", cfg.plan_model, static, user, ScenarioSet)
        out.extend(part.scenarios)
        console.print(f"  designed {len(part.scenarios)} scenarios for {chunk[0].id}..{chunk[-1].id}")
    return ScenarioSet(scenarios=out)


def sanitize(plan: TestPlan) -> TestPlan:
    """Catch planner mistakes before they become false FAILs."""
    seen: set[str] = set()
    req_ids = {r.id for r in plan.requirements}
    for n, sc in enumerate(plan.scenarios, 1):
        if sc.id in seen:
            sc.id = f"{sc.id}-{n}"
        seen.add(sc.id)
        sc.requirement_ids = [r for r in sc.requirement_ids if r in req_ids] or sc.requirement_ids
        captured = {a.var for a in sc.steps if a.op == "capture" and a.var}
        kept = []
        for c in sc.checks:
            if c.kind == "expr":
                used = set(re.findall(r"\{(\w+)\}", c.expr or ""))
                if not used <= captured:
                    console.print(f"  [dim]plan fix: dropped check in {sc.id} using uncaptured {used - captured}[/dim]")
                    continue
            kept.append(c)
        sc.checks = kept
    return plan


def build_plan(prd: str, site_text: str) -> TestPlan:
    reqs = extract_requirements(prd)
    console.print(f"  extracted {len(reqs.requirements)} requirements "
                  f"({sum(not r.explicit for r in reqs.requirements)} implied)")
    scs = design_scenarios(prd, reqs, site_text)
    return sanitize(TestPlan(app_summary=reqs.app_summary, requirements=reqs.requirements, scenarios=scs.scenarios))
