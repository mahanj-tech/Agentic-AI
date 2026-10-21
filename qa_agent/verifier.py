"""Second opinion on failures, to keep false positives low.

Deterministic oracles decide that *something* differed from the spec. The judge model
then looks at the evidence (failed checks with observed values, API traffic, the final
screenshot) and classifies it:

  defect / missing_feature   -> stays FAILED (reported as a bug)
  test_design_issue          -> UNVERIFIED  (our scenario was wrong, not the app)
  agent_limitation           -> UNVERIFIED  (we could not operate the UI)

Only failing or blocked scenarios reach this stage, so the expensive model is called a
handful of times per run instead of once per step.
"""
from __future__ import annotations

import json

from .config import cfg
from . import llm
from .models import Adjudication, ScenarioResult

SYSTEM = (
    "You are a senior QA lead reviewing an automated test result against a product spec. "
    "Be strict about evidence: classify as 'defect' only when the observed values clearly contradict the "
    "expected behaviour. Use 'missing_feature' when the spec requires a UI element/behaviour that is "
    "absent from the page. Use 'test_design_issue' when the test itself made a wrong assumption (wrong field, "
    "wrong expected value, checked the wrong element). Use 'agent_limitation' when the agent could not "
    "operate the UI but the feature may exist. Severity: critical = money/data integrity or security, "
    "high = core flow broken, medium = validation/UX contract broken, low = cosmetic."
)


def adjudicate(res: ScenarioResult) -> None:
    sc = res.scenario
    evidence = {
        "scenario": sc.title,
        "type": sc.type,
        "expected_behaviour": sc.expected,
        "steps_executed": [f"{st.index}. {st.note}" + (f" -> captured {st.captured}" if st.captured else "")
                           + (f" -> ERROR {st.error}" if st.error else "") for st in res.steps],
        "checks": [c.model_dump() for c in res.checks],
        "captured_variables": res.variables,
        "api_calls": [{k: n.get(k) for k in ("method", "url", "status", "request_body", "response_body")}
                      for n in res.network if n.get("method") != "GET" or n.get("status", 200) >= 400][-8:],
        "console_errors": res.console_errors[-5:],
        "agent_reason": res.reason,
    }
    shot = next((st.screenshot for st in reversed(res.steps) if st.screenshot), None)
    content: list = [{"type": "text", "text": json.dumps(evidence, default=str)[:9000]}]
    if shot:
        content.append(llm.image_part(shot, detail="high"))
    try:
        adj = llm.structured("failure-adjudication", cfg.judge_model, SYSTEM, content, Adjudication)
    except (llm.BudgetExceeded, llm.LLMUnavailable) as e:
        res.reason += f" [not adjudicated: {e}]"
        return
    res.adjudication = adj
    if res.status == "FAILED" and adj.classification in {"test_design_issue", "agent_limitation"} and adj.confidence >= 0.6:
        res.status = "UNVERIFIED"
        res.reason = f"judge: {adj.classification} — {adj.explanation}"
    elif res.status == "UNVERIFIED" and adj.classification == "missing_feature" and adj.confidence >= 0.7:
        res.status = "FAILED"
        res.reason = f"missing feature — {adj.explanation}"
