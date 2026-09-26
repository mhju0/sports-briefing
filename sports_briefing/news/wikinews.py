"""Two reviewed, pinned Wikinews articles for one historical signing topic."""
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
BACKGROUND_PAGE_ID = 2793763
BACKGROUND_REVISION_ID = 4813539
BACKGROUND_TITLE = "Arsenal signs Japanese Takuma; Chelsea signs Batshuayi"
BACKGROUND_URL = "https://en.wikinews.org/wiki/Arsenal_signs_Japanese_Takuma;_Chelsea_signs_Batshuayi"
BACKGROUND_SHA256 = "8ad53fca316f2845d02f62230a52d2f5d6a7b8c1abd09d5115ef54bba26a02cd"
API_URL = (
    "https://en.wikinews.org/w/api.php?action=query&format=json&formatversion=2"
    "&prop=info%7Crevisions&inprop=url&rvprop=ids%7Ctimestamp%7Ccontent"
    "&rvslots=main&pageids=2790899%7C2793763"
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
        if not isinstance(pages, list) or len(pages) != 2:
            raise ValueError("expected exactly two requested pages")
        by_id = {page["pageid"]: page for page in pages}
        if set(by_id) != {PAGE_ID, BACKGROUND_PAGE_ID}:
            raise ValueError("requested page IDs changed or repeated")
        documents = (_reviewed_document(by_id[PAGE_ID]), _reviewed_document(by_id[BACKGROUND_PAGE_ID]))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise EvidenceError(f"Wikinews reviewed article mismatch: {exc}") from exc
    return EvidenceBatch("live-reviewed", documents, source="wikinews")


def _reviewed_document(page: dict) -> ReviewedDocument:
    background = page["pageid"] == BACKGROUND_PAGE_ID
    page_id, revision_id, title, canonical_url, expected_hash, revision_time, date_label, published_date = (
        (BACKGROUND_PAGE_ID, BACKGROUND_REVISION_ID, BACKGROUND_TITLE, BACKGROUND_URL, BACKGROUND_SHA256,
         "2024-12-18T03:28:56Z", "July 6, 2016", "2016-07-06") if background else
        (PAGE_ID, REVISION_ID, TITLE, CANONICAL_URL, MAIN_SHA256,
         "2026-05-04T03:20:02Z", "May 25, 2016", "2016-05-25")
    )
    try:
        revisions = page["revisions"]
        if not isinstance(revisions, list) or len(revisions) != 1:
            raise ValueError("expected one reviewed revision")
        revision = page["revisions"][0]
        main = revision["slots"]["main"]["content"]
        if not isinstance(main, str):
            raise ValueError("missing main-slot text")
        if (page["pageid"], page["title"], page["canonicalurl"], page["lastrevid"],
            revision["revid"], revision["timestamp"], page["ns"], page["contentmodel"],
            revision["slots"]["main"]["contentmodel"]) != (
            page_id, title, canonical_url, revision_id, revision_id, revision_time, 0, "wikitext", "wikitext"
        ):
            raise ValueError("page identity or revision changed")
        if hashlib.sha256(main.encode("utf-8")).hexdigest() != expected_hash:
            raise ValueError("reviewed main-slot SHA-256 changed")
        if not main.startswith(f"{{{{date|{date_label}}}}}\n") or "{{Publish}}" not in main or "{{Archived-cc-2.5}}" not in main:
            raise ValueError("reviewed publication or license markers changed")
        if not background and ("Today<!-- On Wednesday-->," not in main or "announced signing" not in main or "contract in force from July 1" not in main):
            raise ValueError("reviewed signing distinction changed")
        if background and ("second summer signing of 2016 after [[Switzerland|Swiss]] midfielder {{w|Granit Xhaka}} from {{w|Borussia Mönchengladbach}}" not in main
                           or "|title  = Arsenal signs Mönchengladbach captain Granit Xhaka\n|date   = May 25, 2016" not in main):
            raise ValueError("reviewed background confirmation changed")
        date.fromisoformat(published_date)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise EvidenceError(f"Wikinews reviewed article mismatch: {exc}") from exc
    metadata = {
        "page_id": page_id,
        "revision_id": revision_id,
        "revision_time": revision_time,
        "revision_url": f"https://en.wikinews.org/w/index.php?oldid={revision_id}",
        "main_slot_sha256": expected_hash,
        "license": "CC BY 2.5",
        "license_url": LICENSE_URL,
        "copyright_url": COPYRIGHT_URL,
        "attribution": f"Wikinews contributors, {title}, revision {revision_id}",
        "change_note": "Reviewed normalization of signing announcement; no article text or images stored." if not background else "Reviewed background confirmation of the existing Xhaka signing; no Asano or Chelsea development normalized and no article text or images stored.",
        "date_template": date_label,
        "publication_markers": ["Publish", "Archived-cc-2.5"],
    }
    if background:
        metadata.update({
            "normalization_scope": "background_confirmation_of_existing_xhaka_signing",
            "event_date_basis": f"original reviewed article {PAGE_ID}, May 25, 2016; this page does not establish the announcement date",
            "related_news_page_id": PAGE_ID,
        })
    return ReviewedDocument(
        canonical_url=canonical_url, external_id=f"wikinews:{page_id}:{revision_id}",
        title=title, author="Wikinews contributors", published_at=None,
        content_hash=hashlib.sha256(" ".join(main.casefold().split()).encode("utf-8")).hexdigest(),
        subject_key="player:granit-xhaka", subject_name="Granit Xhaka",
        effective_date="2016-05-25", placement_qualifier=None,
        published_date=published_date, source_metadata_json=json.dumps(metadata, sort_keys=True),
        entity_id="arsenal", action="signing_announced",
    )
