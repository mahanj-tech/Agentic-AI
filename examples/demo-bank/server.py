#!/usr/bin/env python3
"""Tiny stand-in target for developing the agent offline (stdlib only, synthetic data).

It is NOT the hackathon target. It deliberately contains a few planted defects so the
agent's detection can be demonstrated end to end:  python server.py  -> http://localhost:8080
"""
import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).parent
LOCK = threading.Lock()


def seed():
    return {
        "accounts": [
            {"id": "chk", "name": "Everyday Checking", "number": "****4021", "balance": 2450.75},
            {"id": "sav", "name": "High-Yield Savings", "number": "****7788", "balance": 10200.00},
            {"id": "crd", "name": "Travel Credit Card", "number": "****1190", "balance": 315.40},
        ],
        "transactions": [
            {"id": 1, "date": "2026-10-01", "account": "chk", "description": "Payroll deposit", "type": "credit", "amount": 3200.00},
            {"id": 2, "date": "2026-10-03", "account": "chk", "description": "Grocery Mart", "type": "debit", "amount": 84.12},
            {"id": 3, "date": "2026-10-05", "account": "sav", "description": "Interest", "type": "credit", "amount": 12.40},
            {"id": 4, "date": "2026-10-07", "account": "chk", "description": "Electric utility", "type": "debit", "amount": 120.55},
            {"id": 5, "date": "2026-10-09", "account": "crd", "description": "Airline ticket", "type": "debit", "amount": 315.40},
        ],
    }


STATE = seed()


def acct(i):
    return next((a for a in STATE["accounts"] if a["id"] == i), None)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/accounts":
            return self._json(200, STATE["accounts"])
        if u.path == "/api/transactions":
            q = parse_qs(u.query)
            rows = list(STATE["transactions"])
            t = (q.get("type") or ["all"])[0]
            if t == "credit":           # PLANTED BUG: "debit" filter is ignored
                rows = [r for r in rows if r["type"] == t]
            rows.sort(key=lambda r: r["id"], reverse=True)
            return self._json(200, rows)
        body = (HERE / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        global STATE
        u = urlparse(self.path)
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if u.path == "/api/reset":
            STATE = seed()
            return self._json(200, {"ok": True})
        if u.path != "/api/transfer":
            return self._json(404, {"error": "not found"})
        time.sleep(0.6)  # async UI
        with LOCK:
            src, dst = acct(data.get("from")), acct(data.get("to"))
            try:
                amount = float(data.get("amount"))
            except (TypeError, ValueError):
                return self._json(400, {"error": "Enter a valid amount"})
            if not src or not dst:
                return self._json(400, {"error": "Select both accounts"})
            if src is dst:
                return self._json(400, {"error": "Source and destination must differ"})
            if amount == 0:
                return self._json(400, {"error": "Amount must be greater than zero"})
            # PLANTED BUG: negative amounts and overdrafts are not rejected
            src["balance"] = round(src["balance"] - amount, 2)
            dst["balance"] = round(dst["balance"] + int(amount), 2)  # PLANTED BUG: cents dropped on credit
            now = datetime.now().strftime("%Y-%m-%d")
            nid = max(t["id"] for t in STATE["transactions"]) + 1
            memo = data.get("memo") or "Transfer"
            STATE["transactions"] += [
                {"id": nid, "date": now, "account": src["id"], "description": f"{memo} to {dst['name']}", "type": "debit", "amount": amount},
                {"id": nid + 1, "date": now, "account": dst["id"], "description": f"{memo} from {src['name']}", "type": "credit", "amount": amount},
            ]
            return self._json(200, {"ok": True, "reference": f"TX{nid:05d}"})


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"demo bank on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
