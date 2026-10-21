"""Autonomous exploration: enter the demo, discover pages/views and record what each one
contains (fields, buttons, tables, stable selectors). No LLM calls — this is free, and it
grounds the planner in the real UI so generated steps target elements that exist."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from rich.console import Console

from .config import cfg
from .runtime import BrowserPool

console = Console()

NAV_BUTTONS_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const t = el => (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim();
  const nodes = document.querySelectorAll('nav button, header button, aside button, [role=tab], [role=menuitem], nav [role=link], .nav button, .sidebar button, .tabs button');
  return [...new Set(Array.from(nodes).filter(vis).map(t).filter(x => x && x.length < 40))];
}
"""

# nav-area buttons are views, so only obviously destructive labels are skipped
RISKY = re.compile(r"log ?out|sign ?out|delete|remove|reset|close account|clear data", re.I)


def _key(snap: dict) -> str:
    u = urlparse(snap.get("url", ""))
    return f"{u.path}{('#' + u.fragment) if u.fragment else ''}|{'/'.join(snap.get('headings', [])[:2])}"


def explore(pool: BrowserPool, shot_dir: Path) -> dict:
    s = pool.session(shot_dir, "explore")
    pages: dict[str, dict] = {}
    try:
        s.open_app()
        home = s.snapshot()
        home["screenshot"] = s.screenshot("home")
        home["reached_by"] = f"open app, click '{cfg.entry_button}'"
        pages[_key(home)] = home
        origin = urlparse(s.page.url).netloc

        link_queue = []
        for l in home.get("links", []):
            href = l.get("href") or ""
            if href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            full = urljoin(s.page.url, href).split("#")[0] if not href.startswith("#/") else urljoin(s.page.url, href)
            if href.startswith("#") and not href.startswith("#/"):
                continue  # in-page anchor such as 'Skip to main content'
            if urlparse(full).netloc == origin and full not in link_queue:
                link_queue.append(full)
        try:
            nav_buttons = s.page.evaluate(NAV_BUTTONS_JS)
        except Exception:
            nav_buttons = []

        for url in link_queue:
            if len(pages) >= cfg.max_explore_pages:
                break
            try:
                s.page.goto(url, wait_until="domcontentloaded")
                s.settle()
                snap = s.snapshot()
                if _key(snap) not in pages:
                    snap["screenshot"] = s.screenshot("page")
                    snap["reached_by"] = f"navigate to {url}"
                    pages[_key(snap)] = snap
            except Exception as e:
                console.print(f"  [dim]explore: could not open {url}: {e}[/dim]")

        for label in nav_buttons:
            if len(pages) >= cfg.max_explore_pages or RISKY.search(label):
                continue
            try:
                s.open_app()
                s.page.get_by_role("button", name=label).or_(s.page.get_by_role("tab", name=label)).first.click()
                s.settle()
                snap = s.snapshot()
                if _key(snap) not in pages:
                    snap["screenshot"] = s.screenshot(f"nav_{label}")
                    snap["reached_by"] = f"click nav '{label}'"
                    pages[_key(snap)] = snap
            except Exception:
                continue
    finally:
        s.close()

    site = {"base_url": cfg.target_url, "pages": list(pages.values())}
    console.print(f"  discovered {len(pages)} page(s)/view(s): "
                  + ", ".join((p.get('headings') or [p.get('title', '?')])[0][:30] for p in pages.values()))
    return site


def compact(site: dict) -> str:
    """Token-lean text rendering of the site map for the planner prompt."""
    lines = [f"BASE URL: {site['base_url']}"]
    for p in site["pages"]:
        lines.append(f"\n## VIEW {p.get('url')}  (reached by: {p.get('reached_by')})")
        if p.get("headings"):
            lines.append("headings: " + " | ".join(p["headings"][:8]))
        for f in p.get("fields", []):
            bits = [f"{f['tag']}", f"type={f.get('type')}", f"label='{f.get('label')}'"]
            for k in ("placeholder", "selector", "min", "max", "step", "required"):
                if f.get(k):
                    bits.append(f"{k}={f[k]}")
            if f.get("options"):
                bits.append(f"options={f['options']}")
            lines.append("field: " + " ".join(bits))
        for b in p.get("buttons", [])[:30]:
            lines.append(f"button: '{b['text']}'" + (f" selector={b['selector']}" if b.get("selector") else "")
                         + (" (disabled)" if b.get("disabled") else ""))
        for l in p.get("links", [])[:20]:
            lines.append(f"link: '{l['text']}' -> {l['href']}")
        for t in p.get("tables", []):
            lines.append(f"table: selector={t.get('selector')} row_selector={t.get('row_selector')} headers={t['headers']} "
                         f"rows={t['row_count']} sample={t['sample_rows']}")
        if p.get("testids"):
            lines.append("testids: " + "; ".join(f"{x['testid']}='{x['text']}'" for x in p["testids"][:60]))
        if p.get("alerts"):
            lines.append("visible messages: " + " | ".join(p["alerts"][:5]))
    return "\n".join(lines)
