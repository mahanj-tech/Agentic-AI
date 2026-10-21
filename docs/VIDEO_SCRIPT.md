# Walkthrough video (about 4.5 minutes)

**Before recording**
1. Do a full run, then review the plan: `python run.py --url $TARGET_URL --prd ../test-website/PRD.md`.
2. Pick 3–4 scenarios for the live segment. For DemoBank, these work well:
   `--only SC-XFER-01 SC-XFER-11 SC-XFER-16 SC-HIST-08`. That is a passing exact transfer, a negative amount the app wrongly accepts, an overdraft it wrongly allows, and the inclusive end-date bug.
3. Keep `artifacts/qa_audit_report.html` from the full run open in a browser tab.

| Time | Show | Say |
|---|---|---|
| 0:00–0:30 | README architecture diagram | "Our agent verifies the site against its PRD. Exploration and verification are deterministic code; models are used only to read the spec, design tests and review failures." |
| 0:30–1:15 | Terminal: `python run.py --plan-only` output; open `test_plan.json` | "It explored N views with no LLM calls, extracted N requirements including implied ones, and designed normal, negative and edge scenarios. Each step targets a selector it actually saw." Point at one negative scenario's checks: error shown **and** balances unchanged. |
| 1:15–2:30 | `python run.py --plan artifacts/test_plan.json --headed --slow-mo 250 --only <ids>` | Narrate as the browser moves: "It reads both balances first… submits… waits for the request to finish rather than sleeping… reads them again. The success message isn't trusted. The numbers are." If a step heals, point out `resolved_by`. |
| 2:30–3:30 | Report → Defects section, top bug | "Here's a defect: expected vs observed values, captured before/after numbers, the API request and response, screenshots, and steps a developer can follow. It reproduced on a clean re-run, and the judge model confirmed it's an app defect, not a test mistake." |
| 3:30–4:00 | Report → Unverified section | "Anything we can't prove is reported as unverified with a reason. That keeps false positives out." |
| 4:00–4:30 | Report → Cost breakdown | "This run cost $X: per model, per stage, from the API's own token counts. Replaying a saved plan is nearly free because responses are cached and the budget is capped." |
