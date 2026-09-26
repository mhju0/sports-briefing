"""One reviewed, pinned Wikinews article; no discovery or article extraction."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .evidence import EvidenceBatch, EvidenceError, ReviewedDocument


PAGE_ID = 2790899
REVISION_ID = 5024729
TITLE = "Arsenal signs Mönchengladbach captain Granit Xhaka"
CANONICAL_URL = "https://en.wikinews.org/wiki/Arsenal_signs_M%C3%B6nchengladbach_captain_Granit_Xhaka"
MAIN_SHA256 = "8575a8f639f0fec1c262965d27df160ef7801578accf511d47010768554c5dc8"
API_URL = (
    "https://en.wikinews.org/w/api.php?action=query&format=json&formatversion=2"
    "&prop=info%7Crevisions&inprop=url&rvprop=ids%7Ctimestamp%7Ccontent"
    "&rvslots=main&pageids=2790899"
)
MAX_RESPONSE_BYTES = 64 * 1024
LICENSE_URL = "https://creativecommons.org/licenses/by/2.5/"
COPYRIGHT_URL = "https://en.wikinews.org/wiki/Wikinews:Copyright"


def fetch_article(*, timeout: float = 15.0) -> EvidenceBatch:
    request = Request(API_URL, headers={"User-Agent": "SportsBriefing/0.1 (bounded manual archive proof)", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise EvidenceError(f"Wikinews API returned HTTP {response.status}")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise EvidenceError(f"Wikinews API request failed: {exc}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise EvidenceError("Wikinews API response exceeds 64 KiB")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("Wikinews API response is not UTF-8 JSON") from exc
    return normalize_article(payload)


def normalize_article(payload: object) -> EvidenceBatch:
    try:
        if not isinstance(payload, dict) or "error" in payload:
            raise ValueError("API error or invalid response")
        pages = payload["query"]["pages"]
        if not isinstance(pages, list) or len(pages) != 1:
            raise ValueError("expected exactly one requested page")
        page = pages[0]
        revision = page["revisions"][0]
        main = revision["slots"]["main"]["content"]
        if not isinstance(main, str):
            raise ValueError("missing main-slot text")
        if (page["pageid"], page["title"], page["canonicalurl"], page["lastrevid"],
            revision["revid"], page["ns"], page["contentmodel"],
            revision["slots"]["main"]["contentmodel"]) != (
            PAGE_ID, TITLE, CANONICAL_URL, REVISION_ID, REVISION_ID, 0, "wikitext", "wikitext"
        ):
            raise ValueError("page identity or revision changed")
        if hashlib.sha256(main.encode("utf-8")).hexdigest() != MAIN_SHA256:
            raise ValueError("reviewed main-slot SHA-256 changed")
        if not main.startswith("{{date|May 25, 2016}}\n") or "{{Publish}}" not in main or "{{Archived-cc-2.5}}" not in main:
            raise ValueError("reviewed publication or license markers changed")
        if "Today<!-- On Wednesday-->," not in main or "announced signing" not in main or "contract in force from July 1" not in main:
            raise ValueError("reviewed signing distinction changed")
        date.fromisoformat("2016-05-25")
        revision_time = revision["timestamp"]
        if revision_time != "2026-05-04T03:20:02Z":
            raise ValueError("reviewed revision timestamp changed")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise EvidenceError(f"Wikinews reviewed article mismatch: {exc}") from exc
    metadata = {
        "page_id": PAGE_ID,
        "revision_id": REVISION_ID,
        "revision_time": revision_time,
        "revision_url": f"https://en.wikinews.org/w/index.php?oldid={REVISION_ID}",
        "main_slot_sha256": MAIN_SHA256,
        "license": "CC BY 2.5",
        "license_url": LICENSE_URL,
        "copyright_url": COPYRIGHT_URL,
        "attribution": f"Wikinews contributors, {TITLE}, revision {REVISION_ID}",
        "change_note": "Reviewed normalization of signing announcement; no article text or images stored.",
        "date_template": "May 25, 2016",
        "publication_markers": ["Publish", "Archived-cc-2.5"],
    }
    document = ReviewedDocument(
        canonical_url=CANONICAL_URL, external_id=f"wikinews:{PAGE_ID}:{REVISION_ID}",
        title=TITLE, author="Wikinews contributors", published_at=None,
        content_hash=hashlib.sha256(" ".join(main.casefold().split()).encode("utf-8")).hexdigest(),
        subject_key="player:granit-xhaka", subject_name="Granit Xhaka",
        effective_date="2016-05-25", placement_qualifier=None,
        published_date="2016-05-25", source_metadata_json=json.dumps(metadata, sort_keys=True),
        entity_id="arsenal", action="signing_announced",
    )
    return EvidenceBatch("live-reviewed", (document,), source="wikinews")
