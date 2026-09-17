#!/usr/bin/env python3
"""CoreSignal employee_base client plus shared helpers for the pipeline.

Reads CORESIGNAL_API_KEY from the environment. Every request is appended to
<work>/credit-ledger.txt with the x-credits-remaining header, which is the
source of truth for spend. Collect calls are billed and refuse to run once
the last known remaining drops below CREDIT_FLOOR. Searches are free.

Paths:
  NETWORK_CONFIG  config file (default: pipeline/config.json)
  NETWORK_WORK    working dir for collects, searches, targets, ledger
                  (default: pipeline/work, gitignored)
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

BASE = "https://api.coresignal.com/cdapi/v2/employee_base"

# Some CDN edges reject python-urllib's default agent, so send a browser one.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("NETWORK_CONFIG", os.path.join(HERE, "config.json"))
WORK = os.environ.get("NETWORK_WORK", os.path.join(HERE, "work"))
COLLECTS = os.path.join(WORK, "collects")
SEARCHES = os.path.join(WORK, "searches")
TARGETS = os.path.join(WORK, "targets.json")
LEDGER_PATH = os.path.join(WORK, "credit-ledger.txt")

CREDIT_FLOOR = 300
COLLECT_COST = 10  # check your plan; the ledger header is authoritative


class CreditsExhausted(Exception):
    """402 from CoreSignal: credits are gone. Never swallow this."""


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__("CoreSignal %s: %s" % (status, str(body)[:200]))
        self.status = status
        self.body = body


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise SystemExit("Missing %s. Copy config.example.json to config.json."
                         % CONFIG_PATH)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def api_key():
    key = os.environ.get("CORESIGNAL_API_KEY", "").strip()
    if not key:
        raise SystemExit("CORESIGNAL_API_KEY is not set in the environment.")
    return key


def last_known_remaining():
    """Most recent remaining= value in the ledger, or None if never seen."""
    if not os.path.exists(LEDGER_PATH):
        return None
    result = None
    with open(LEDGER_PATH) as f:
        for line in f:
            i = line.rfind("remaining=")
            if i < 0:
                continue
            val = line[i + len("remaining="):].strip()
            if val.isdigit():
                result = int(val)
    return result


def _log(method, endpoint, status, remaining):
    os.makedirs(WORK, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rem = str(remaining) if remaining is not None else "?"
    with open(LEDGER_PATH, "a") as f:
        f.write("%s %s %s %s remaining=%s\n" % (stamp, method, endpoint, status, rem))


def _remaining_from(headers):
    raw = headers.get("x-credits-remaining") if headers else None
    if raw is None:
        return None
    raw = str(raw).strip()
    return int(raw) if raw.isdigit() else None


def _guard_billed(endpoint):
    if os.environ.get("CORESIGNAL_FLOOR_OVERRIDE") == "1":
        return
    rem = last_known_remaining()
    if rem is not None and rem < CREDIT_FLOOR:
        raise SystemExit(
            "Refusing billed call %s: last known credits remaining is %d, below "
            "the floor of %d. Set CORESIGNAL_FLOOR_OVERRIDE=1 to override on "
            "purpose." % (endpoint, rem, CREDIT_FLOOR)
        )


def _request(method, endpoint, body=None, billed=False):
    if billed:
        _guard_billed(endpoint)
    url = BASE + endpoint
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "apikey": api_key(),
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    last_err = None
    for attempt in range(3):
        if attempt:
            time.sleep(3 * attempt)
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                status = res.status
                remaining = _remaining_from(res.headers)
                payload = res.read()
        except urllib.error.HTTPError as e:
            status = e.code
            remaining = _remaining_from(e.headers)
            payload = e.read()
        except urllib.error.URLError as e:
            last_err = e
            continue
        _log(method, endpoint, status, remaining)
        if status == 402:
            raise CreditsExhausted("402 on %s: CoreSignal credits exhausted." % endpoint)
        if status == 429 or status >= 500:
            last_err = ApiError(status, payload)
            continue
        if status >= 400:
            raise ApiError(status, payload)
        try:
            return json.loads(payload)
        except ValueError:
            raise ApiError(status, payload)
    if isinstance(last_err, Exception):
        raise last_err
    raise ApiError(0, "request failed with no response")


def search_es_dsl(query_body):
    """Free. Body is standard ES DSL: {"query": {...}}."""
    return _request("POST", "/search/es_dsl", body=query_body)


def search_filter(params):
    """Free. Flat filter params (experience_company_name, experience_title, ...)."""
    return _request("POST", "/search/filter", body=params)


def collect(id_or_shorthand):
    """Billed. Numeric provider id or a LinkedIn shorthand."""
    return _request("GET", "/collect/%s" % id_or_shorthand, billed=True)


# ---- shared helpers ----

def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def ids_from(result):
    """Search responses are bare int arrays; tolerate string ids and ES hits."""
    if isinstance(result, dict):
        hits = result.get("hits")
        if isinstance(hits, dict):
            result = [h.get("_id") for h in hits.get("hits", []) if isinstance(h, dict)]
    out = []
    for v in result if isinstance(result, list) else []:
        if isinstance(v, int):
            out.append(v)
        elif isinstance(v, str) and v.isdigit():
            out.append(int(v))
    return out


def experience_entries(profile):
    """Full experience history, normalized dicts. Never truncates."""
    raw = profile.get("experience")
    if not isinstance(raw, list) or not raw:
        coll = profile.get("member_experience_collection")
        raw = coll if isinstance(coll, list) else []
    months = {m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"], 1)}

    def iso(e, side):
        # prefer the numeric fields; fall back to "January 2025" strings
        y = e.get("date_%s_year" % side)
        m = e.get("date_%s_month" % side)
        if y:
            return "%04d-%02d" % (int(y), int(m) if m else 1)
        s = e.get("date_%s" % side)
        if not s:
            return None
        s = str(s).strip()
        parts = s.split()
        if len(parts) == 2 and parts[0].lower() in months:
            return "%04d-%02d" % (int(parts[1]), months[parts[0].lower()])
        return s

    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        company = (e.get("company_name") or e.get("company") or "").strip()
        title = (e.get("title") or e.get("position_title") or "").strip()
        if not company and not title:
            continue
        out.append({
            "company": company,
            "title": title,
            "date_from": iso(e, "from"),
            "date_to": iso(e, "to"),
            "raw": e,
        })
    return out


def profile_name(profile):
    for key in ("name", "full_name"):
        v = profile.get(key)
        if v:
            return str(v).strip()
    first = (profile.get("first_name") or "").strip()
    last = (profile.get("last_name") or "").strip()
    return (first + " " + last).strip() or "?"


def parse_year(value):
    """'2005-03-01', '2005-03' or '2005' to a decimal year; None if absent."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    parts = s.split("-")
    try:
        year = int(parts[0][:4])
    except ValueError:
        return None
    month = 1
    if len(parts) > 1 and parts[1].strip()[:2].isdigit():
        month = min(max(int(parts[1].strip()[:2]), 1), 12)
    return year + (month - 1) / 12.0


def now_year():
    today = date.today()
    return today.year + (today.month - 1) / 12.0


def span_years(date_from, date_to):
    """Duration in years; null date_to means current. None if start unknown."""
    start = parse_year(date_from)
    if start is None:
        return None
    end = parse_year(date_to)
    if end is None:
        end = now_year()
    return max(0.0, end - start)


_COMPANY_SUFFIXES = {
    "inc", "llc", "ltd", "corp", "corporation", "company", "co", "plc",
    "lp", "llp", "the", "group", "holdings",
}


def norm_company(name):
    """Normalization for same-company matching across name variants."""
    s = "".join(c if c.isalnum() or c == " " else " " for c in str(name).lower())
    words = [w for w in s.split() if w not in _COMPANY_SUFFIXES]
    return "".join(words)


def same_company(a, b):
    na, nb = norm_company(a), norm_company(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


_TITLE_DROP = {
    "chief", "officer", "executive", "senior", "sr", "jr", "vice", "president",
    "vp", "evp", "svp", "avp", "director", "general", "manager", "managing",
    "head", "lead", "global", "group", "corporate", "division", "divisional",
    "regional", "assistant", "deputy", "associate", "of", "the", "and", "for",
    "to", "at", "ceo", "cio", "coo", "cfo", "cto", "cmo", "chro", "gm", "co",
    "founder", "partner", "principal", "board", "member", "advisor",
}


def title_keywords(title):
    """Function words in a title, seniority and filler removed."""
    words = re.findall(r"[a-z]+", str(title).lower())
    return {w for w in words if len(w) > 1 and w not in _TITLE_DROP}
