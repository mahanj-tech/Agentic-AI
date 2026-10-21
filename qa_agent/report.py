"""Builds the audit report: self-contained HTML (screenshots embedded), PDF, JSON and Markdown."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from jinja2 import Environment

from .models import RequirementResult, ScenarioResult, TestPlan

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}


def aggregate(plan: TestPlan, results: list[ScenarioResult]) -> list[RequirementResult]:
    out = []
    for r in plan.requirements:
        mine = [x for x in results if r.id in x.scenario.requirement_ids]
        failed = [x for x in mine if x.status == "FAILED"]
        passed = [x for x in mine if x.status == "PASSED"]
        if failed:
            st, summ = "FAILED", f"{len(failed)} of {len(mine)} scenarios failed: " + "; ".join(
                (x.adjudication.title if x.adjudication else x.scenario.title) for x in failed)
        elif mine and len(passed) == len(mine):
            st, summ = "PASSED", f"all {len(mine)} scenarios passed ({', '.join(sorted({x.scenario.type for x in mine}))})"
        elif passed:
            st, summ = "UNVERIFIED", f"{len(passed)} passed, {len(mine) - len(passed)} could not be verified"
        else:
            st, summ = "UNVERIFIED", "no scenario could verify this requirement" if mine else "no scenario covers this requirement"
        out.append(RequirementResult(requirement=r, status=st, scenario_ids=[x.scenario.id for x in mine], summary=summ))
    return out


def _img(path: str | None) -> str:
    if not path or not Path(path).exists():
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def repro_steps(res: ScenarioResult) -> list[str]:
    return [f"{st.note}" + (f"  → read {st.captured}" if st.captured else "") + (f"  ✗ {st.error}" if st.error else "")
            for st in res.steps]


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA Audit Report</title>
<style>
:root{--ink:#16181d;--mute:#5d6470;--line:#e3e6ec;--bg:#f6f7f9;--card:#fff;--pass:#127a3c;--passbg:#e5f4ea;--fail:#b4231b;--failbg:#fde9e7;--unv:#9a5b00;--unvbg:#fdf1dc;--acc:#2d4bd8}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif;color:var(--ink);background:var(--bg)}
main{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:40px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--ink)}h3{font-size:15px;margin:0}
.mute{color:var(--mute)}.small{font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:18px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:26px;line-height:1.1}.tile span{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.03em;white-space:nowrap}
.PASSED{background:var(--passbg);color:var(--pass)}.FAILED{background:var(--failbg);color:var(--fail)}.UNVERIFIED{background:var(--unvbg);color:var(--unv)}
.sev{background:#eef0f4;color:var(--ink)}.sev.critical{background:var(--fail);color:#fff}.sev.high{background:#e2574c;color:#fff}.sev.medium{background:#f2b33d}.sev.low{background:#d9dde5}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#eef0f4;font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:var(--mute)}
tr:last-child td{border-bottom:0}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--fail);border-radius:10px;padding:16px 18px;margin:14px 0;break-inside:avoid}
.card.unv{border-left-color:var(--unv)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:10px}@media(max-width:800px){.cols{grid-template-columns:1fr}}
ol{margin:6px 0;padding-left:20px}code,pre{font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}pre{background:#f1f3f6;padding:8px;border-radius:6px;white-space:pre-wrap;word-break:break-all;margin:4px 0}
.shots{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}.shots figure{margin:0;flex:1 1 260px;max-width:360px}.shots img{width:100%;border:1px solid var(--line);border-radius:6px}
figcaption{font-size:11px;color:var(--mute)}
details{margin:6px 0}summary{cursor:pointer;font-weight:600}
.kv td:first-child{width:28%;color:var(--mute)}
.ok{color:var(--pass);font-weight:700}.no{color:var(--fail);font-weight:700}.na{color:var(--unv);font-weight:700}
@media print{body{background:#fff}main{padding:0}.card,.tile,table{border-color:#ccc}details{display:block}details>summary{list-style:none}}
</style></head><body><main>
<p class="mute small">Automated QA audit · generated {{ generated }}</p>
<h1>Does the application behave the way its specification says?</h1>
<p class="mute">Target <code>{{ target }}</code> · Spec <code>{{ prd }}</code> · Run time {{ duration }} · Mode {{ mode }}</p>
<p>{{ app_summary }}</p>

<div class="grid">
 <div class="tile"><span>Requirements</span><b>{{ reqs|length }}</b>{{ rc.PASSED }} pass · {{ rc.FAILED }} fail · {{ rc.UNVERIFIED }} unverified</div>
 <div class="tile"><span>Scenarios run</span><b>{{ results|length }}</b>{{ tc.normal }} normal · {{ tc.negative }} negative · {{ tc.edge }} edge</div>
 <div class="tile"><span>Defects found</span><b style="color:var(--fail)">{{ defects|length }}</b>{{ sev_line }}</div>
 <div class="tile"><span>LLM cost this run</span><b>${{ '%.4f'|format(cost.total_usd) }}</b>{{ cost.total_calls }} calls · {{ cost.cache_hits }} from cache</div>
 <div class="tile"><span>Cost per scenario</span><b>${{ '%.4f'|format(cost.total_usd / (results|length or 1)) }}</b>budget cap ${{ '%.2f'|format(cost.budget_usd) }}</div>
</div>

<h2>1 · Requirement verdicts</h2>
<table><thead><tr><th>Req</th><th>Requirement</th><th>Verdict</th><th>Basis</th><th>Scenarios</th></tr></thead><tbody>
{% for r in reqs %}<tr><td><b>{{ r.requirement.id }}</b><div class="small mute">{{ r.requirement.priority }}{% if not r.requirement.explicit %} · implied{% endif %}</div></td>
<td><b>{{ r.requirement.title }}</b><div class="small">{{ r.requirement.text }}</div>{% if r.requirement.prd_quote %}<div class="small mute">PRD: “{{ r.requirement.prd_quote }}”</div>{% endif %}</td>
<td><span class="badge {{ r.status }}">{{ r.status }}</span></td><td class="small">{{ r.summary }}</td><td class="small">{{ r.scenario_ids|join(', ') }}</td></tr>{% endfor %}
</tbody></table>

<h2>2 · Defects ({{ defects|length }})</h2>
{% if not defects %}<p class="mute">No confirmed defects.</p>{% endif %}
{% for d in defects %}<div class="card">
<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><span class="badge sev {{ d.sev }}">{{ (d.sev or 'unrated')|upper }}</span>
<h3>BUG-{{ '%02d'|format(loop.index) }} · {{ d.title }}</h3></div>
<p class="small mute">{{ d.res.scenario.id }} · {{ d.res.scenario.type }} scenario · requirements {{ d.res.scenario.requirement_ids|join(', ') }} · reproduced on {{ d.res.attempts }} attempt(s){% if d.res.adjudication %} · judge: {{ d.res.adjudication.classification }} ({{ '%.0f'|format(d.res.adjudication.confidence*100) }}% confidence){% endif %}</p>
<div class="cols"><div><b>Steps to reproduce</b><ol>{% for s in d.steps %}<li>{{ s }}</li>{% endfor %}</ol></div>
<div><table class="kv"><tr><td>Expected</td><td>{{ d.expected }}</td></tr><tr><td>Observed</td><td>{{ d.observed }}</td></tr>
{% for c in d.res.checks if c.passed == False %}<tr><td>Failed check</td><td>{{ c.description }}<br><span class="small">expected <code>{{ c.expected }}</code><br>observed <code>{{ c.observed }}</code></span></td></tr>{% endfor %}
{% if d.res.variables %}<tr><td>Captured values</td><td><code>{{ d.res.variables }}</code></td></tr>{% endif %}</table></div></div>
{% if d.api %}<details><summary>API evidence ({{ d.api|length }})</summary>{% for n in d.api %}<pre>{{ n.method }} {{ n.url }} → {{ n.status }}{% if n.request_body %}
request: {{ n.request_body }}{% endif %}{% if n.response_body %}
response: {{ n.response_body }}{% endif %}</pre>{% endfor %}</details>{% endif %}
<div class="shots">{% for s in d.shots %}<figure><img src="{{ s.src }}" alt=""><figcaption>{{ s.cap }}</figcaption></figure>{% endfor %}</div>
</div>{% endfor %}

<h2>3 · Unverified ({{ unverified|length }})</h2>
<p class="small mute">Scenarios the agent could not decide with evidence. They are not counted as defects, to avoid false positives.</p>
{% for u in unverified %}<div class="card unv"><h3>{{ u.scenario.id }} · {{ u.scenario.title }}</h3>
<p class="small">{{ u.reason }}</p>{% if u.flaky %}<p class="small"><b>Inconsistent between attempts</b> — worth a manual look for race conditions.</p>{% endif %}
<details><summary>Steps</summary><ol>{% for s in steps_of(u) %}<li>{{ s }}</li>{% endfor %}</ol></details></div>{% endfor %}

<h2>4 · All scenarios</h2>
<table><thead><tr><th>ID</th><th>Type</th><th>Scenario</th><th>Verdict</th><th>Checks</th><th>Healing</th><th>Time</th></tr></thead><tbody>
{% for x in results %}<tr><td>{{ x.scenario.id }}</td><td>{{ x.scenario.type }}</td><td><details><summary>{{ x.scenario.title }}</summary>
<div class="small mute">{{ x.scenario.rationale }}</div><ol class="small">{% for s in steps_of(x) %}<li>{{ s }}</li>{% endfor %}</ol>
<div class="small">{% for c in x.checks %}<div><span class="{{ 'ok' if c.passed else ('na' if c.passed is none else 'no') }}">{{ '✓' if c.passed else ('?' if c.passed is none else '✗') }}</span> {{ c.description }} <span class="mute">— {{ c.observed }}</span></div>{% endfor %}</div>
</details></td><td><span class="badge {{ x.status }}">{{ x.status }}</span></td>
<td class="small">{{ x.checks|selectattr('passed')|list|length }}/{{ x.checks|length }}</td><td class="small">{{ healed(x) }}</td><td class="small">{{ x.duration_s }}s</td></tr>{% endfor %}
</tbody></table>

<h2>5 · Cost breakdown</h2>
<table><thead><tr><th>Model</th><th>Calls (cached)</th><th>Input tokens</th><th>Cached input</th><th>Output tokens</th><th>Rate $/1M (in / cached / out)</th><th>Cost</th></tr></thead><tbody>
{% for m, v in cost.models.items() %}<tr><td><code>{{ m }}</code></td><td>{{ v.calls }} ({{ v.cached_calls }})</td><td>{{ '{:,}'.format(v.input) }}</td><td>{{ '{:,}'.format(v.cached_input) }}</td><td>{{ '{:,}'.format(v.output) }}</td>
<td class="small">{% if v.rate %}{{ v.rate.input }} / {{ v.rate.cached_input }} / {{ v.rate.output }}{% else %}not in pricing.json{% endif %}</td><td>{% if v.priced %}${{ '%.4f'|format(v.usd) }}{% else %}n/a{% endif %}</td></tr>
{% else %}<tr><td colspan="7" class="mute">No model calls in this run (replayed a saved plan; all checks deterministic).</td></tr>{% endfor %}
</tbody></table>
<table style="margin-top:12px"><thead><tr><th>Stage</th><th>What the model does</th><th>Calls (cached)</th><th>Cost</th></tr></thead><tbody>
{% for s, v in cost.stages.items() %}<tr><td><code>{{ s }}</code></td><td class="small">{{ stage_desc.get(s, '') }}</td><td>{{ v.calls }} ({{ v.cached_calls }})</td><td>${{ '%.4f'|format(v.usd) }}</td></tr>{% endfor %}
<tr><td><code>exploration, execution, oracles</code></td><td class="small">Playwright + deterministic checks</td><td>0</td><td>$0.0000</td></tr>
</tbody></table>
<p class="small mute">Token counts come from the API's own usage fields (including image tokens and prompt-cache hits). Prices from pricing.json — verify against the provider's current price list. Repeat runs of an unchanged plan are served from the local response cache at $0.</p>

<h2>6 · Method</h2>
<ol class="small">
<li><b>Explore</b> (no LLM): enter the demo, discover views, record fields, buttons, tables and stable selectors.</li>
<li><b>Plan</b> (plan model): extract explicit + implied requirements from the PRD, then design normal / negative / edge scenarios grounded in the explored site map.</li>
<li><b>Execute</b>: one fresh browser context per scenario; self-healing element resolution (test id → label → placeholder → ARIA role → text → fast-model pick from live DOM); network-idle + DOM-quiet waits instead of sleeps.</li>
<li><b>Verify</b>: deterministic oracles over captured before/after values, DOM state, validation messages and HTTP traffic. A success toast is never accepted as proof.</li>
<li><b>Confirm</b>: failures re-run once in a clean context (flake filter), then reviewed by the judge model, which can downgrade test-design mistakes to UNVERIFIED.</li>
</ol>
</main></body></html>"""

STAGE_DESC = {
    "requirement-extraction": "PRD → requirement list",
    "scenario-design": "requirements + site map → scenarios",
    "element-healing": "fallback element pick when all locator strategies fail",
    "semantic-check": "visual assertions that DOM checks cannot express",
    "failure-adjudication": "review failed/blocked scenarios to cut false positives",
}


def build(plan: TestPlan, results: list[ScenarioResult], cost: dict, out_dir: Path, meta: dict) -> dict:
    reqs = aggregate(plan, results)
    defects = []
    for x in results:
        if x.status != "FAILED":
            continue
        adj = x.adjudication
        failing = [c for c in x.checks if c.passed is False]
        shots = []
        for st in x.steps:
            if st.screenshot and (st.op in {"click", "press", "open"} or st is x.steps[-1] or not st.ok):
                shots.append({"src": _img(st.screenshot), "cap": f"after step {st.index}: {st.note}"})
        prio = {r.id: r.priority for r in plan.requirements}
        fallback_sev = min((prio.get(i, "low") for i in x.scenario.requirement_ids),
                           key=lambda p: SEV_ORDER.get(p, 4), default="medium")
        defects.append({
            "res": x, "sev": adj.severity if adj else fallback_sev,
            "title": adj.title if adj else f"Not met: {x.scenario.title}",
            "expected": adj.expected if adj else x.scenario.expected,
            "observed": adj.observed if adj else "; ".join(f"{c.observed}" for c in failing) or x.reason,
            "steps": repro_steps(x),
            "api": [n for n in x.network if n.get("method") != "GET" or n.get("status", 200) >= 400][-6:],
            "shots": shots[-4:],
        })
    defects.sort(key=lambda d: SEV_ORDER.get(d["sev"], 4))
    rc = {k: sum(r.status == k for r in reqs) for k in ("PASSED", "FAILED", "UNVERIFIED")}
    tc = {k: sum(x.scenario.type == k for x in results) for k in ("normal", "negative", "edge")}
    sev_counts = {}
    for d in defects:
        sev_counts[d["sev"] or "unrated"] = sev_counts.get(d["sev"] or "unrated", 0) + 1
    sev_line = " · ".join(f"{v} {k}" for k, v in sev_counts.items()) or "—"

    env = Environment(autoescape=True)
    env.globals.update(steps_of=repro_steps, stage_desc=STAGE_DESC,
                       healed=lambda x: ", ".join(sorted({s.resolved_by for s in x.steps if s.resolved_by and s.resolved_by.startswith(("healed", "text~", "role:"))})) or "—")
    page = env.from_string(TEMPLATE).render(
        generated=time.strftime("%Y-%m-%d %H:%M"), target=meta["target"], prd=meta["prd"], duration=meta["duration"],
        mode=meta["mode"], app_summary=plan.app_summary, reqs=reqs, results=results, defects=defects,
        unverified=[x for x in results if x.status == "UNVERIFIED"], rc=rc, tc=tc, sev_line=sev_line, cost=cost)

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "qa_audit_report.html"
    html_path.write_text(page, encoding="utf-8")

    data = {"meta": meta, "cost": cost, "requirements": [r.model_dump() for r in reqs],
            "scenarios": [x.model_dump() for x in results]}
    (out_dir / "qa_audit_report.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    md = [f"# QA Audit — {meta['target']}", "",
          f"Requirements: {rc['PASSED']} passed, {rc['FAILED']} failed, {rc['UNVERIFIED']} unverified · "
          f"Scenarios: {len(results)} · Defects: {len(defects)} · LLM cost: ${cost['total_usd']:.4f}", "",
          "| Req | Title | Verdict | Basis |", "|---|---|---|---|"]
    md += [f"| {r.requirement.id} | {r.requirement.title} | {r.status} | {r.summary} |" for r in reqs]
    md += ["", "## Defects", ""]
    for i, d in enumerate(defects, 1):
        md += [f"### BUG-{i:02d} [{(d['sev'] or 'unrated').upper()}] {d['title']}",
               f"Scenario {d['res'].scenario.id} · requirements {', '.join(d['res'].scenario.requirement_ids)}", "",
               "**Steps to reproduce**", *[f"{n}. {s}" for n, s in enumerate(d["steps"], 1)], "",
               f"**Expected:** {d['expected']}", "", f"**Observed:** {d['observed']}", ""]
    (out_dir / "qa_audit_report.md").write_text("\n".join(md), encoding="utf-8")
    return {"html": html_path, "requirements": reqs, "defects": len(defects), "rc": rc}


def export_pdf(html_path: Path) -> Path | None:
    try:
        from playwright.sync_api import sync_playwright
        pdf = html_path.with_suffix(".pdf")
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(html_path.resolve().as_uri())
            pg.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
            pg.pdf(path=str(pdf), format="A4", print_background=True,
                   margin={"top": "14mm", "bottom": "14mm", "left": "10mm", "right": "10mm"})
            b.close()
        return pdf
    except Exception:
        return None
