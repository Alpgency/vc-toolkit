"""Shared helpers for the Twenty setup/seed/reset scripts.

Env:
  TWENTY_BASE_URL  Twenty URL (default http://localhost:3000)
  TWENTY_API_KEY   API key from Twenty: Settings > APIs & Webhooks
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("TWENTY_BASE_URL", "http://localhost:3000").rstrip("/")
KEY = os.environ.get("TWENTY_API_KEY")
if not KEY:
    sys.exit("TWENTY_API_KEY is required")

# Pipeline stages on opportunity.stage. The workflows read and write these
# values, so rename labels freely but keep the values in sync with n8n.
STAGES = [
    ("NEW", "New", "blue"),
    ("OUT_OF_SCOPE", "Out of scope", "gray"),
    ("REACH_OUT", "Reach out", "yellow"),
    ("SEQUENCE_RUNNING", "Sequence running", "orange"),
    ("REPLIED", "Replied", "purple"),
    ("FIRST_MEETING", "First meeting", "green"),
    ("SHORTLIST", "Shortlist", "turquoise"),
]
STAGE_BY_TITLE = {label: value for value, label, _ in STAGES}


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise SystemExit(f"{method} {path} -> {e.code}: {detail}") from e


def unwrap(resp: dict):
    """Twenty wraps results as {data: {<key>: ...}}; return the inner value."""
    data = resp.get("data", resp)
    if isinstance(data, dict) and len(data) >= 1:
        return next(iter(data.values()))
    return data


def list_records(obj: str, limit: int = 60, flt: str | None = None) -> list:
    # ponytail: single page (Twenty caps a page at 60), add cursor paging past 60 records
    q = f"limit={limit}"
    if flt:
        q += "&filter=" + urllib.parse.quote(flt, safe="[]:.,")
    out = unwrap(call("GET", f"/rest/{obj}?{q}"))
    return out if isinstance(out, list) else []
