#!/usr/bin/env bash
# Verify a running public-mode deployment. Usage: smoke_check.sh [base_url]
set -euo pipefail

base="${1:-http://127.0.0.1:8000}"
python3 - "$base" <<'PY'
import json
import sys
from urllib.request import urlopen
from urllib.error import HTTPError

base = sys.argv[1].rstrip("/")


def get(path):
    with urlopen(base + path, timeout=10) as response:
        return json.load(response)


def require(condition, message):
    if not condition:
        raise SystemExit("smoke check failed: " + message)


require(get("/health") == {"status": "ok"}, "health")
meta = get("/meta")
require(meta["public_mode"] is True, "public mode is not enabled")
require(meta["entities"] == {"arsenal": "unavailable", "texans": "demo", "scheffler": "demo"},
        "unexpected source status")
for path, mode in (("/timeline", "hide_results"), ("/timeline?hide_results=false", "show_results")):
    timeline = get(path)
    items = timeline["items"]
    require(timeline["spoiler_mode"] == mode, "unexpected spoiler mode")
    require(timeline["unavailable_entities"] == ["arsenal"], "unexpected unavailable entities")
    require({item["entity"]["id"] for item in items} == {"texans", "scheffler"},
            "missing demo entity or unexpected entity")
    for item in items:
        require(item["data_mode"] == "demo", "non-demo item in public timeline")
        require(item["source"]["provider"] == "synthetic-demo", "unexpected demo provider")
        require(item["title"].endswith(" (demo)") and item["summary"].startswith("Demo data")
                and item["source"]["attribution"].startswith("Demo data"), "missing demo label")
        if mode == "hide_results":
            require("result" not in item, "result exposed in default spoiler mode")

for path in ("/briefings/arsenal", "/briefings/texans"):
    try:
        get(path)
    except HTTPError as exc:
        require(exc.code == 404, "unexpected briefing status")
    else:
        raise SystemExit("smoke check failed: restricted briefing is exposed")
print(f"smoke check passed: {base} ({len(items)} demo items, both spoiler modes, briefings blocked)")
PY
