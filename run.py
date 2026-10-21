#!/usr/bin/env python3
"""Agentic QA — verify a running web app against its PRD.

  python run.py --url https://target.example --prd ../test-website/PRD.md
  python run.py --plan artifacts/test_plan.json          # re-run a saved plan (no planning cost)
  python run.py --plan-only                              # explore + plan, review before executing
  python run.py --headed --slow-mo 300 --only SC-XFER     # for the demo video
  python run.py --plan plans/demobank_plan.json --reset-cmd "cd ../test-website/database && make reset"
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from qa_agent.config import cfg

console = Console()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="target URL (env TARGET_URL)")
    ap.add_argument("--prd", help="path to PRD.md (env PRD_PATH)")
    ap.add_argument("--plan", help="load a saved test plan JSON instead of generating one")
    ap.add_argument("--plan-only", action="store_true", help="explore + plan, then stop")
    ap.add_argument("--only", nargs="*", help="run only these scenario ids (prefix match)")
    ap.add_argument("--types", nargs="*", choices=["normal", "negative", "edge"], help="run only these scenario types")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--slow-mo", type=int, help="ms delay between browser actions (demo video)")
    ap.add_argument("--budget", type=float, help="max LLM spend in USD (env MAX_USD)")
    ap.add_argument("--no-adjudicate", action="store_true", help="skip LLM review of failures")
    ap.add_argument("--no-cache", action="store_true", help="ignore the LLM response cache")
    ap.add_argument("--out", help="output directory (default artifacts/)")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--reset-cmd", help="shell command run before executing, e.g. "
                    "'cd ../test-website/database && make reset' (deterministic seed data)")
    a = ap.parse_args()

    if a.url: cfg.target_url = a.url
    if a.prd: cfg.prd_path = a.prd
    if a.headed: cfg.headless = False
    if a.slow_mo is not None: cfg.slow_mo_ms = a.slow_mo
    if a.budget is not None: cfg.max_usd = a.budget
    if a.no_adjudicate: cfg.adjudicate = False
    if a.no_cache: cfg.use_cache = False
    if a.out: cfg.out_dir = Path(a.out)

    from qa_agent import explorer, planner, report
    from qa_agent.executor import run_scenario
    from qa_agent.llm import ledger
    from qa_agent.models import load_plan
    from qa_agent.runtime import BrowserPool

    t0 = time.time()
    out = Path(cfg.out_dir)
    shots = out / "screenshots"
    if shots.exists():
        shutil.rmtree(shots)
    out.mkdir(parents=True, exist_ok=True)

    console.rule("[bold]Agentic QA")
    console.print(f"target  {cfg.target_url}\nspec    {cfg.prd_path if not a.plan else a.plan}\n"
                  f"models  plan={cfg.plan_model}  fast={cfg.fast_model}  judge={cfg.judge_model}  budget=${cfg.max_usd:.2f}")

    pool = BrowserPool()
    try:
        if a.plan:
            plan = load_plan(json.loads(Path(a.plan).read_text()))
            mode = f"replay of saved plan ({Path(a.plan).name})"
            console.print(f"\n[cyan]1-2 · Loaded plan:[/cyan] {len(plan.requirements)} requirements, {len(plan.scenarios)} scenarios")
        else:
            prd_path = Path(cfg.prd_path)
            if not prd_path.exists():
                console.print(f"[red]PRD not found at {prd_path}. Pass --prd.[/red]")
                return 2
            prd = prd_path.read_text(encoding="utf-8")
            console.print("\n[cyan]1 · Exploring the application[/cyan]")
            site = explorer.explore(pool, shots)
            (out / "site_map.json").write_text(json.dumps(site, indent=2))
            console.print("\n[cyan]2 · Extracting requirements and designing scenarios[/cyan]")
            plan = planner.build_plan(prd, explorer.compact(site))
            (out / "test_plan.json").write_text(plan.model_dump_json(indent=2))
            mode = "full (explore → plan → execute → verify)"
            console.print(f"  plan saved to {out / 'test_plan.json'}  (LLM so far ${ledger.total_usd:.4f})")
            if a.plan_only:
                return 0

        scenarios = plan.scenarios
        if a.only:
            scenarios = [s for s in scenarios if any(s.id.startswith(p) for p in a.only)]
        if a.types:
            scenarios = [s for s in scenarios if s.type in a.types]

        if a.reset_cmd:
            import subprocess
            r = subprocess.run(a.reset_cmd, shell=True, capture_output=True, text=True)
            console.print(f"  reset: {'ok' if r.returncode == 0 else 'FAILED ' + r.stderr[-200:]}")
        console.print(f"\n[cyan]3 · Executing {len(scenarios)} scenarios[/cyan]")
        results = []
        for sc in scenarios:
            try:
                results.append(run_scenario(pool, sc, shots))
            except Exception as e:  # never let one scenario kill the run
                from qa_agent.models import ScenarioResult
                console.print(f"  [yellow]UNVERIFIED[/yellow] {sc.id} crashed: {e}")
                results.append(ScenarioResult(scenario=sc, status="UNVERIFIED", reason=f"agent error: {e}"))
    finally:
        pool.close()

    console.print("\n[cyan]4 · Writing report[/cyan]")
    meta = {"target": cfg.target_url, "prd": cfg.prd_path if not a.plan else a.plan,
            "duration": f"{time.time() - t0:.0f}s", "mode": mode,
            "models": {"plan": cfg.plan_model, "fast": cfg.fast_model, "judge": cfg.judge_model}}
    cost = ledger.summary()
    rep = report.build(plan, results, cost, out, meta)
    pdf = None if a.no_pdf else report.export_pdf(rep["html"])

    t = Table(title="Requirement verdicts")
    for col in ("Req", "Title", "Verdict"):
        t.add_column(col)
    colours = {"PASSED": "green", "FAILED": "red", "UNVERIFIED": "yellow"}
    for r in rep["requirements"]:
        t.add_row(r.requirement.id, r.requirement.title[:60], f"[{colours[r.status]}]{r.status}[/]")
    console.print(t)
    console.print(f"defects: [bold red]{rep['defects']}[/]   requirements: {rep['rc']}   "
                  f"LLM cost: [bold]${cost['total_usd']:.4f}[/] ({cost['total_calls']} calls, {cost['cache_hits']} cached)")
    console.print(f"report: {rep['html']}" + (f"\n        {pdf}" if pdf else ""))
    return 1 if rep["defects"] else 0


if __name__ == "__main__":
    sys.exit(main())
