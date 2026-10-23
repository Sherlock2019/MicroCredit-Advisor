"""Smoke test against a running stack, through the portal's /api proxy. Standard library only, so it runs on a bare EC2.

    python3 scripts/smoke_test.py [--url http://127.0.0.1:8480] [--demo-key KEY]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8480")
    ap.add_argument("--demo-key", default="")
    a = ap.parse_args()
    results = []

    def call(method, path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if a.demo_key:
            headers["X-Demo-Key"] = a.demo_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(a.url + path, data=json.dumps(body).encode() if body is not None else None,  # noqa: S310
                                     headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - URL given by the operator
            return json.loads(r.read() or b"{}")

    def check(name, fn):
        try:
            detail = fn()
            results.append((name, True, detail))
        except (urllib.error.URLError, AssertionError, KeyError, ValueError) as exc:
            results.append((name, False, str(exc)[:200]))

    tok = {}
    check("gateway health", lambda: call("GET", "/health")["status"])
    check("capabilities", lambda: len(call("GET", "/api/v1/platform/capabilities")["applications"]))
    check("dev sign-in", lambda: tok.update(t=call("POST", "/api/v1/dev/token", {"username": "fatima.finance"})["access_token"]) or "ok")
    check("finance applications", lambda: call("GET", "/api/v1/finance/applications", token=tok.get("t"))["total"])
    tok_p = {}
    check("project sign-in", lambda: tok_p.update(t=call("POST", "/api/v1/dev/token", {"username": "ana.project"})["access_token"]) or "ok")
    check("project map", lambda: len(call("GET", "/api/v1/projects/map", token=tok_p.get("t"))["sites"]))
    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
