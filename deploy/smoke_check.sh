#!/usr/bin/env bash
# Verify a running public-mode deployment. Usage: smoke_check.sh [base_url]
set -euo pipefail

base="${1:-http://127.0.0.1:8000}"
python3 - "$base" <<'PY'
import json
import sys
from urllib.request import urlopen

base = sys.argv[1].rstrip("/")


def get(path):
    with urlopen(base + path, timeout=10) as response:
        return json.load(response)


assert get("/health") == {"status": "ok"}, "health"
meta = get("/meta")
assert meta["public_mode"] is True, "public mode is not enabled"
assert meta["entities"] == {"arsenal": "unavailable", "texans": "demo", "scheffler": "demo"}, meta
timeline = get("/timeline")
items = timeline["items"]
assert "arsenal" in timeline["unavailable_entities"], "arsenal should be unavailable"
assert all(item["data_mode"] == "demo" for item in items), "non-demo item in public timeline"
assert all(item["entity"]["id"] in {"texans", "scheffler"} for item in items), "unexpected entity"
assert all(item["summary"].startswith("Demo data") for item in items
           if item["source"]["provider"] == "synthetic-demo"), "missing demo label"
print(f"smoke check passed: {base} ({len(items)} demo items, spoiler_mode={timeline['spoiler_mode']})")
PY
