"""Typed contracts shared by every stage.

The plan schemas (Requirement → Scenario → Action/Check) are sent to the LLM as
*strict* structured-output schemas, so every field is required and nullable
instead of having defaults. `load_plan()` fills the gaps for hand-written plans.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- plan

ActionOp = Literal[
    "goto",        # value = path or absolute URL
    "click",       # target
    "fill",        # target, value  (value "" clears the field)
    "select",      # target, value  (option label or value)
    "check",       # target
    "uncheck",     # target
    "press",       # target, value = key name e.g. "Enter"
    "wait_for_text",  # value
    "capture",     # target, var, value = "number" | "text" | "count"; or value = "errors" | "messages" (no target)
    "reload",
    "set_viewport",  # value = "390x844"
    "double_click",  # target: two rapid clicks (duplicate-submission test)
    "back",          # browser back button
]

CheckKind = Literal[
    "text_visible",      # value (optionally scoped to target)
    "text_absent",       # value (optionally scoped to target)
    "element_visible",   # target
    "element_absent",    # target
    "element_disabled",  # target
    "input_value",       # target, value
    "text_matches",      # target, value = regex the element text must match (formats)
    "expr",              # expr, e.g. "{after} == {before} - 25.5"  (vars from capture)
    "var_matches",       # target = captured var name, value = regex its text must match
    "var_not_matches",   # target = captured var name, value = regex it must NOT match
    "text_not_matches",  # target (optional, default body), value = regex that must NOT occur
    "all_rows_match",    # target = row selector, value = regex every row must match (filters)
    "no_horizontal_overflow",  # page fits the viewport width (responsive layout)
    "request_count",     # value = "POST /api/path", expr = "== 1" (requests during the scenario)
    "url_contains",      # value
    "url_not_contains",  # value
    "error_shown",       # value = optional keyword; any visible validation/alert/error state
    "no_server_errors",  # no HTTP >= 500 and no uncaught page errors during the scenario
    "semantic",          # value = natural-language assertion judged by the LLM from screenshot+DOM
]


class Requirement(BaseModel):
    id: str = Field(description="Stable id like REQ-01")
    title: str
    text: str = Field(description="Verifiable statement, paraphrased from the PRD")
    prd_quote: str = Field(description="Shortest PRD phrase this requirement is based on")
    category: str = Field(description="e.g. navigation, accounts, transfers, transactions, filters, validation")
    priority: Literal["high", "medium", "low"]
    explicit: bool = Field(description="False when the requirement is implied rather than stated")


class Action(BaseModel):
    op: ActionOp
    target: Optional[str] = Field(description="Element: 'testid=..', 'css=..', 'label=..', 'role=button[name=..]', 'text=..' or a plain visible label")
    value: Optional[str] = Field(description="Literal value, or '=<expr>' computed from captured vars, e.g. '={bal_before} + 50'")
    var: Optional[str] = Field(description="Variable name for capture")
    note: Optional[str] = Field(description="Human-readable step for reproduction steps")


class Check(BaseModel):
    kind: CheckKind
    target: Optional[str]
    value: Optional[str]
    expr: Optional[str]
    description: str = Field(description="What this check proves, in plain words")


class Scenario(BaseModel):
    id: str = Field(description="e.g. SC-03")
    requirement_ids: List[str]
    type: Literal["normal", "negative", "edge"]
    title: str
    rationale: str = Field(description="Why this scenario could expose a defect")
    steps: List[Action]
    checks: List[Check]
    expected: str = Field(description="Expected behaviour per the PRD, one or two sentences")


class RequirementSet(BaseModel):
    app_summary: str
    requirements: List[Requirement]


class ScenarioSet(BaseModel):
    scenarios: List[Scenario]


class TestPlan(BaseModel):
    app_summary: str
    requirements: List[Requirement]
    scenarios: List[Scenario]


def load_plan(data: dict) -> TestPlan:
    """Accept hand-written plans that omit nullable keys."""
    for sc in data.get("scenarios", []):
        sc.setdefault("rationale", "")
        for a in sc.get("steps", []):
            for k in ("target", "value", "var", "note"):
                a.setdefault(k, None)
        for c in sc.get("checks", []):
            for k in ("target", "value", "expr"):
                c.setdefault(k, None)
            c.setdefault("description", c["kind"])
    for r in data.get("requirements", []):
        r.setdefault("prd_quote", "")
        r.setdefault("explicit", True)
        r.setdefault("priority", "medium")
        r.setdefault("category", "general")
    return TestPlan.model_validate(data)


# --------------------------------------------------------------------------- LLM verdicts

class ElementPick(BaseModel):
    index: int = Field(description="Index of the matching element, or -1 if none matches")
    reason: str


class SemanticVerdict(BaseModel):
    holds: bool
    observed: str = Field(description="What is actually on screen that decides the answer")


class Adjudication(BaseModel):
    classification: Literal["defect", "missing_feature", "test_design_issue", "agent_limitation"]
    confidence: float = Field(description="0..1")
    severity: Literal["critical", "high", "medium", "low"]
    title: str = Field(description="Bug title, max 12 words")
    observed: str
    expected: str
    explanation: str


# --------------------------------------------------------------------------- results

Status = Literal["PASSED", "FAILED", "UNVERIFIED"]


class StepResult(BaseModel):
    index: int
    op: str
    target: Optional[str] = None
    value: Optional[str] = None
    note: Optional[str] = None
    ok: bool = True
    resolved_by: Optional[str] = None    # locator strategy that worked (shows self-healing)
    captured: Optional[str] = None
    error: Optional[str] = None
    screenshot: Optional[str] = None
    url: Optional[str] = None


class CheckResult(BaseModel):
    kind: str
    description: str
    passed: Optional[bool]   # None = could not be evaluated
    observed: str = ""
    expected: str = ""


class ScenarioResult(BaseModel):
    scenario: Scenario
    status: Status
    reason: str = ""
    steps: List[StepResult] = []
    checks: List[CheckResult] = []
    variables: dict = {}
    network: List[dict] = []
    console_errors: List[str] = []
    attempts: int = 1
    flaky: bool = False
    adjudication: Optional[Adjudication] = None
    duration_s: float = 0.0


class RequirementResult(BaseModel):
    requirement: Requirement
    status: Status
    scenario_ids: List[str]
    summary: str
