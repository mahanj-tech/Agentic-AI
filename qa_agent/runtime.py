"""Playwright runtime: isolated sessions, evidence capture and self-healing element resolution."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Locator, Page, Playwright, sync_playwright

from .config import cfg
from . import llm
from .models import ElementPick

# Collects a compact, LLM-friendly description of what is on screen.
SNAPSHOT_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  const labelOf = el => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return txt(l); }
    const p = el.closest('label');
    if (p) { const c = p.cloneNode(true); c.querySelectorAll('input,select,textarea,option').forEach(x => x.remove()); return txt(c); }
    const lb = el.getAttribute('aria-labelledby'); if (lb) { const l = document.getElementById(lb); if (l) return txt(l); }
    return '';
  };
  const sel = el => {
    if (el.dataset.testid) return `testid=${el.dataset.testid}`;
    if (el.getAttribute('data-test-id')) return `css=[data-test-id="${el.getAttribute('data-test-id')}"]`;
    if (el.id && !/^\d/.test(el.id)) return `css=#${CSS.escape(el.id)}`;
    if (el.name) return `css=${el.tagName.toLowerCase()}[name="${el.name}"]`;
    return null;
  };
  const out = { title: document.title, url: location.href, headings: [], fields: [], buttons: [], links: [], tables: [], alerts: [], testids: [] };
  document.querySelectorAll('h1,h2,h3').forEach(h => vis(h) && out.headings.push(txt(h)));
  document.querySelectorAll('input,select,textarea').forEach(el => {
    if (!vis(el) || el.type === 'hidden') return;
    const f = { tag: el.tagName.toLowerCase(), type: el.type || null, label: labelOf(el), placeholder: el.placeholder || null,
      selector: sel(el), required: el.required || null, min: el.min || null, max: el.max || null, step: el.step || null,
      value: (el.value || '').slice(0, 40), disabled: el.disabled || null };
    if (el.tagName === 'SELECT') f.options = Array.from(el.options).map(o => o.text.trim()).slice(0, 25);
    out.fields.push(f);
  });
  document.querySelectorAll('button,[role=button],input[type=submit],[role=tab]').forEach(el => vis(el) &&
    out.buttons.push({ text: txt(el) || el.value || el.getAttribute('aria-label') || '', selector: sel(el), disabled: el.disabled || null }));
  document.querySelectorAll('a[href]').forEach(el => vis(el) && out.links.push({ text: txt(el), href: el.getAttribute('href') }));
  document.querySelectorAll('table,[role=table],[role=grid]').forEach(t => {
    if (!vis(t)) return;
    const heads = Array.from(t.querySelectorAll('th,[role=columnheader]')).map(txt);
    const rows = Array.from(t.querySelectorAll('tbody tr,[role=row]')).filter(r => !r.querySelector('th'));
    out.tables.push({ selector: sel(t), headers: heads, row_count: rows.length,
      row_selector: sel(t) ? `${sel(t)} tbody tr` : null, sample_rows: rows.slice(0, 2).map(txt) });
  });
  document.querySelectorAll('[role=alert],[role=status],[aria-live],.error,.alert,.toast,.invalid-feedback').forEach(el => {
    const t = txt(el); if (vis(el) && t) out.alerts.push(t); });
  document.querySelectorAll('[data-testid]').forEach(el => vis(el) &&
    out.testids.push({ testid: el.dataset.testid, text: txt(el).slice(0, 60) }));
  out.testids = out.testids.slice(0, 80);
  return out;
}
"""

INTERACTIVE_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const els = Array.from(document.querySelectorAll('a,button,input,select,textarea,[role],[data-testid],td,span,div,p,strong,h1,h2,h3,li,label'))
    .filter(el => vis(el) && (el.matches('a,button,input,select,textarea,[role],[data-testid]') || (el.children.length === 0 && (el.innerText||'').trim())));
  return els.slice(0, 250).map((el, i) => { el.setAttribute('data-qa-idx', i);
    return { i, tag: el.tagName.toLowerCase(), type: el.type || null, role: el.getAttribute('role'),
      testid: el.dataset.testid || null, id: el.id || null, name: el.getAttribute('name'),
      placeholder: el.getAttribute('placeholder'), aria: el.getAttribute('aria-label'),
      text: (el.innerText || el.value || '').replace(/\s+/g,' ').trim().slice(0, 60) }; });
}
"""

SETTLE_JS = r"""
(quietMs) => new Promise(res => {
  let t = setTimeout(done, quietMs); const start = Date.now();
  const mo = new MutationObserver(() => { clearTimeout(t); if (Date.now() - start > 3000) return done(); t = setTimeout(done, quietMs); });
  mo.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
  function done() { mo.disconnect(); res(true); }
})
"""

ERROR_STATE_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none'; };
  const found = [];
  document.querySelectorAll('[role=alert],[aria-live=assertive],.error,.error-message,.alert-danger,.alert-error,.invalid-feedback,.field-error,.text-danger,.text-red-500,.text-red-600,[data-testid*=error],[class*=error]')
    .forEach(el => { const t = (el.innerText||'').trim(); if (vis(el) && t) found.push(t.slice(0, 160)); });
  document.querySelectorAll('[aria-invalid=true]').forEach(el => found.push(`aria-invalid field: ${el.name || el.id || el.getAttribute('aria-label') || el.tagName}`));
  document.querySelectorAll('input,select,textarea').forEach(el => { if (el.willValidate && !el.checkValidity() && el.validationMessage && el.value !== undefined && document.activeElement === el)
    found.push(`native validation: ${el.validationMessage}`); });
  return [...new Set(found)];
}
"""

NUM_RE = re.compile(r"\(?-?\s?[$€£₹]?\s?-?\d[\d,]*(?:\.\d+)?\)?")


def parse_number(text: str) -> Optional[float]:
    if text is None:
        return None
    m = NUM_RE.search(text.replace("−", "-"))
    if not m:
        return None
    raw = m.group(0)
    neg = raw.strip().startswith("(") and raw.strip().endswith(")") or "-" in raw
    digits = re.sub(r"[^\d.]", "", raw)
    try:
        val = float(digits)
    except ValueError:
        return None
    return -val if neg else val


class Session:
    """One isolated browser context (fresh cookies/storage) with evidence capture."""

    def __init__(self, browser: Browser, shot_dir: Path, tag: str, heal_cache: dict | None = None):
        self.context: BrowserContext = browser.new_context(viewport=cfg.viewport, ignore_https_errors=True)
        self.context.set_default_timeout(cfg.action_timeout_ms)
        self.context.set_default_navigation_timeout(cfg.nav_timeout_ms)
        self.page: Page = self.context.new_page()
        self.shot_dir = shot_dir
        self.tag = tag
        self.network: list[dict] = []
        self.console_errors: list[str] = []
        self.heal_cache: dict[str, str] = heal_cache if heal_cache is not None else {}
        self._shot_n = 0
        self.page.on("console", lambda m: m.type == "error" and self.console_errors.append(m.text[:300]))
        self.page.on("pageerror", lambda e: self.console_errors.append(f"uncaught: {str(e)[:300]}"))
        self.page.on("response", self._on_response)
        # Playwright's "networkidle" is a one-time load event, so track in-flight XHR/fetch ourselves.
        self.inflight = 0
        self.page.on("request", self._req_start)
        self.page.on("requestfinished", self._req_end)
        self.page.on("requestfailed", self._req_end)

    def _req_start(self, req) -> None:
        if req.resource_type in {"xhr", "fetch"}:
            self.inflight += 1

    def _req_end(self, req) -> None:
        if req.resource_type in {"xhr", "fetch"}:
            self.inflight = max(0, self.inflight - 1)

    # ------------------------------------------------------------------ evidence
    def _on_response(self, resp) -> None:
        req = resp.request
        if req.resource_type not in {"xhr", "fetch", "document"}:
            return
        entry = {"t": round(time.time(), 3), "method": req.method, "url": resp.url, "status": resp.status,
                 "type": req.resource_type}
        if req.method != "GET" and req.post_data:
            entry["request_body"] = req.post_data[:500]
        if req.resource_type in {"xhr", "fetch"}:
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct or "text" in ct:
                    entry["response_body"] = resp.text()[:800]
            except Exception:
                pass
        self.network.append(entry)

    def screenshot(self, label: str) -> str:
        self._shot_n += 1
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)[:40]
        path = self.shot_dir / f"{self.tag}_{self._shot_n:02d}_{safe}.jpg"
        try:
            self.page.screenshot(path=str(path), type="jpeg", quality=60, full_page=False)
        except Exception:
            return ""
        return str(path)

    def snapshot(self) -> dict:
        try:
            return self.page.evaluate(SNAPSHOT_JS)
        except Exception:
            return {}

    def error_state(self) -> list[str]:
        try:
            return self.page.evaluate(ERROR_STATE_JS)
        except Exception:
            return []

    # ------------------------------------------------------------------ navigation & waiting
    def settle(self) -> None:
        """Wait for async UI: no XHR/fetch in flight for a moment, then DOM quiet (no fixed sleeps)."""
        deadline = time.time() + cfg.action_timeout_ms / 1000 * 2
        quiet_since = None
        while time.time() < deadline:
            self.page.wait_for_timeout(100)  # also lets Playwright dispatch request events
            if self.inflight == 0:
                quiet_since = quiet_since or time.time()
                if time.time() - quiet_since >= 0.3:
                    break
            else:
                quiet_since = None
        try:
            self.page.evaluate(SETTLE_JS, 250)
        except Exception:
            pass

    def open_app(self) -> None:
        self.page.goto(cfg.target_url, wait_until="domcontentloaded")
        self.settle()
        self.enter_demo()

    def enter_demo(self) -> bool:
        for loc in (self.page.get_by_role("button", name=re.compile(cfg.entry_button, re.I)),
                    self.page.get_by_role("link", name=re.compile(cfg.entry_button, re.I)),
                    self.page.get_by_text(re.compile(cfg.entry_button, re.I))):
            try:
                loc.first.wait_for(state="visible", timeout=2500)
                loc.first.click()
                self.settle()
                return True
            except Exception:
                continue
        return False

    def goto(self, path: str) -> None:
        url = path if urlparse(path).scheme else urljoin(cfg.target_url.rstrip("/") + "/", path.lstrip("/"))
        if path.startswith("#"):
            url = self.page.url.split("#")[0] + path
        if urlparse(url).netloc != urlparse(cfg.target_url).netloc:
            raise PermissionError(f"refusing to leave the target origin: {url}")
        self.page.goto(url, wait_until="domcontentloaded")
        self.settle()

    # ------------------------------------------------------------------ self-healing locator
    def _candidates(self, target: str):
        """Ordered list of (strategy_name, locator) to try for a target spec."""
        p = self.page
        out = []
        m = re.match(r"^(css|testid|label|placeholder|text|role|xpath)=(.*)$", target.strip(), re.S)
        if m:
            kind, val = m.group(1), m.group(2).strip()
            if kind == "css":
                out.append(("css", p.locator(val)))
            elif kind == "xpath":
                out.append(("xpath", p.locator(f"xpath={val}")))
            elif kind == "testid":
                out.append(("testid", p.get_by_test_id(val)))
                out.append(("testid~", p.locator(f'[data-test-id="{val}"],[data-test="{val}"],[data-cy="{val}"]')))
            elif kind == "label":
                out.append(("label", p.get_by_label(val)))
            elif kind == "placeholder":
                out.append(("placeholder", p.get_by_placeholder(val)))
            elif kind == "text":
                out.append(("text", p.get_by_text(val, exact=True)))
                out.append(("text~", p.get_by_text(val)))
            elif kind == "role":
                rm = re.match(r"(\w+)(?:\[name=(.+)\])?", val)
                if rm:
                    role, name = rm.group(1), (rm.group(2) or "").strip("'\" ")
                    out.append(("role", p.get_by_role(role, name=name) if name else p.get_by_role(role)))
            # heal: fall back to treating the payload as a plain label
            words = re.sub(r"[#.\[\]=\"'_-]+", " ", val).strip()
            if words:
                target = words
            else:
                return out
        t = target
        rx = re.compile(re.escape(t), re.I)
        out += [
            ("testid", p.get_by_test_id(t)),
            ("label", p.get_by_label(t)),
            ("placeholder", p.get_by_placeholder(t)),
            ("role:button", p.get_by_role("button", name=rx)),
            ("role:link", p.get_by_role("link", name=rx)),
            ("role:tab", p.get_by_role("tab", name=rx)),
            ("role:textbox", p.get_by_role("textbox", name=rx)),
            ("role:spinbutton", p.get_by_role("spinbutton", name=rx)),
            ("role:combobox", p.get_by_role("combobox", name=rx)),
            ("role:checkbox", p.get_by_role("checkbox", name=rx)),
            ("text", p.get_by_text(t, exact=True)),
            ("text~", p.get_by_text(rx)),
        ]
        return out

    def resolve(self, target: str, intent: str = "interact", allow_many: bool = False,
                timeout_ms: int | None = None) -> tuple[Optional[Locator], str]:
        """Return (locator, strategy). Polls until the element appears (async UIs), then asks
        the fast model to pick from the live DOM as a last resort. Successful picks are cached."""
        u = urlparse(self.page.url)
        key = f"{u.netloc}{u.path}|{target}"
        if key in self.heal_cache:
            loc = self.page.locator(self.heal_cache[key])
            if loc.count():
                return (loc if allow_many else loc.first), "healed(cached)"
        deadline = time.time() + (timeout_ms or cfg.action_timeout_ms) / 1000
        cands = self._candidates(target)
        while True:
            for name, loc in cands:
                try:
                    n = loc.count()
                except Exception:
                    continue
                if n == 0:
                    continue
                if allow_many:
                    return loc, name
                for i in range(min(n, 5)):
                    try:
                        if loc.nth(i).is_visible():
                            return loc.nth(i), name
                    except Exception:
                        pass
            if time.time() > deadline:
                break
            self.page.wait_for_timeout(250)
        return self._llm_pick(target, intent, key, allow_many)

    def _llm_pick(self, target: str, intent: str, key: str, allow_many: bool):
        try:
            elements = self.page.evaluate(INTERACTIVE_JS)
        except Exception:
            return None, "not-found"
        if not elements:
            return None, "not-found"
        compact = "\n".join(json.dumps({k: v for k, v in e.items() if v}) for e in elements)
        try:
            pick = llm.structured(
                "element-healing", cfg.fast_model,
                "You map a QA test step to an element on a web page. Return the index of the single element the "
                "step refers to, or -1 if no element plausibly matches. Do not guess: -1 is better than a wrong element.",
                f"Step intent: {intent}\nTarget description: {target}\nPage URL: {self.page.url}\n\nElements:\n{compact}",
                ElementPick)
        except (llm.BudgetExceeded, llm.LLMUnavailable):
            return None, "not-found"
        if pick.index < 0:
            return None, "not-found(llm)"
        sel = f'[data-qa-idx="{pick.index}"]'
        loc = self.page.locator(sel)
        if not loc.count():
            return None, "not-found"
        # build a durable selector for the cache
        stable = self.page.evaluate(
            """(s) => { const el = document.querySelector(s); if (!el) return null;
                 if (el.dataset.testid) return `[data-testid="${el.dataset.testid}"]`;
                 if (el.id) return `#${CSS.escape(el.id)}`;
                 if (el.name) return `${el.tagName.toLowerCase()}[name="${el.name}"]`; return null; }""", sel)
        if stable:
            self.heal_cache[key] = stable
        return (loc if allow_many else loc.first), "healed(llm)"

    def close(self) -> None:
        try:
            self.context.close()
        except Exception:
            pass


class BrowserPool:
    def __init__(self) -> None:
        self.pw: Playwright = sync_playwright().start()
        self.browser: Browser = self.pw.chromium.launch(headless=cfg.headless, slow_mo=cfg.slow_mo_ms)
        # healed selectors are reused across scenarios and runs, so each element costs one LLM call at most
        self.heal_file = Path(cfg.cache_dir) / "healed_selectors.json"
        try:
            self.heal_cache = json.loads(self.heal_file.read_text()) if cfg.use_cache else {}
        except Exception:
            self.heal_cache = {}

    def session(self, shot_dir: Path, tag: str) -> Session:
        shot_dir.mkdir(parents=True, exist_ok=True)
        return Session(self.browser, shot_dir, tag, self.heal_cache)

    def close(self) -> None:
        try:
            self.heal_file.parent.mkdir(parents=True, exist_ok=True)
            self.heal_file.write_text(json.dumps(self.heal_cache, indent=1))
        except Exception:
            pass
        try:
            self.browser.close()
        finally:
            self.pw.stop()
