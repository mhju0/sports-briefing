from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewedDocument:
    canonical_url: str
    external_id: str | None
    title: str
    author: str | None
    published_at: str | None
    content_hash: str
    subject_key: str
    subject_name: str
    effective_date: str
    placement_qualifier: str | None
    published_date: str | None = None
    source_metadata_json: str | None = None
    entity_id: str = "texans"
    action: str = "placed_on_ir"

    @property
    def topic_key(self) -> str:
        return f"{self.entity_id}:{self.action}:{self.subject_key}:{self.effective_date}"


@dataclass(frozen=True)
class EvidenceBatch:
    mode: str
    documents: tuple[ReviewedDocument, ...]
    source: str = "texans"


def normalize_batch(value: object) -> EvidenceBatch:
    if not isinstance(value, dict) or set(value) - {"evidence_mode", "source_use_authorized", "documents"}:
        raise EvidenceError("evidence must contain only evidence_mode, source_use_authorized, documents")
    mode = value.get("evidence_mode")
    if not isinstance(mode, str) or mode not in {"synthetic", "reviewed"}:
        raise EvidenceError("evidence_mode must be synthetic or reviewed")
    if mode == "reviewed" and value.get("source_use_authorized") is not True:
        raise EvidenceError("reviewed official evidence requires source_use_authorized=true")
    if mode == "synthetic" and value.get("source_use_authorized") is True:
        raise EvidenceError("synthetic evidence cannot attest official source use")
    documents = value.get("documents")
    if not isinstance(documents, list) or not documents or len(documents) > 20:
        raise EvidenceError("documents must contain 1 to 20 records")
    return EvidenceBatch(mode, tuple(_normalize_document(item, mode, index) for index, item in enumerate(documents)))


def _normalize_document(value: object, mode: str, index: int) -> ReviewedDocument:
    label = f"documents[{index}]"
    fields = {
        "canonical_url", "external_id", "title", "author", "published_at", "text",
        "subject_key", "subject_name", "action", "effective_date", "placement_qualifier",
    }
    if not isinstance(value, dict) or set(value) - fields:
        raise EvidenceError(f"{label} has an unexpected shape")
    url = _url(value.get("canonical_url"), mode, label)
    title = _short_text(value.get("title"), f"{label}.title", 300)
    text = _short_text(value.get("text"), f"{label}.text", 16_384)
    author = _optional_text(value.get("author"), f"{label}.author", 200)
    external_id = _optional_text(value.get("external_id"), f"{label}.external_id", 200)
    published = value.get("published_at")
    published_at = _timestamp(published, f"{label}.published_at") if published is not None else None
    subject_key = _short_text(value.get("subject_key"), f"{label}.subject_key", 100)
    if not re.fullmatch(r"player:[a-z0-9][a-z0-9-]*", subject_key):
        raise EvidenceError(f"{label}.subject_key must be an explicit player:<stable-key>")
    subject_name = _short_text(value.get("subject_name"), f"{label}.subject_name", 100)
    if value.get("action") != "placed_on_ir":
        raise EvidenceError(f"{label}.action must be placed_on_ir")
    effective_date = value.get("effective_date")
    try:
        if not isinstance(effective_date, str) or date.fromisoformat(effective_date).isoformat() != effective_date:
            raise ValueError
    except ValueError as exc:
        raise EvidenceError(f"{label}.effective_date must be YYYY-MM-DD") from exc
    qualifier = value.get("placement_qualifier")
    if qualifier not in (None, "designated_for_return"):
        raise EvidenceError(f"{label}.placement_qualifier is unsupported")
    # A reviewed human supplies normalized facts. Text is used only for exact-content
    # deduplication; publication content itself is not retained in SQLite.
    normalized_text = " ".join(text.casefold().split())
    content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    return ReviewedDocument(
        url, external_id, title, author, published_at, content_hash,
        subject_key, subject_name, effective_date, qualifier,
    )


def _url(raw: object, mode: str, label: str) -> str:
    if not isinstance(raw, str) or len(raw) > 2_000:
        raise EvidenceError(f"{label}.canonical_url is required")
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    allowed = {"example.test"} if mode == "synthetic" else {"houstontexans.com", "www.houstontexans.com"}
    try:
        port = parts.port
    except ValueError as exc:
        raise EvidenceError(f"{label}.canonical_url has an invalid port") from exc
    if parts.scheme != "https" or host not in allowed or port is not None or not parts.path or parts.username or parts.password or parts.query or parts.fragment:
        raise EvidenceError(f"{label}.canonical_url must be an allowed HTTPS source URL")
    if mode == "reviewed" and not re.fullmatch(r"/news/[a-z0-9-]+", parts.path):
        raise EvidenceError(f"{label}.canonical_url must be a reviewed official article URL")
    if mode == "reviewed" and host == "houstontexans.com":
        host = "www.houstontexans.com"
    return urlunsplit(("https", host, parts.path.rstrip("/") or "/", "", ""))


def _short_text(raw: object, label: str, limit: int) -> str:
    if not isinstance(raw, str):
        raise EvidenceError(f"{label} must be non-empty text")
    value = " ".join(raw.split())
    if not value or len(value) > limit:
        raise EvidenceError(f"{label} must be 1 to {limit} characters")
    return value


def _optional_text(raw: object, label: str, limit: int) -> str | None:
    return None if raw is None else _short_text(raw, label, limit)


def _timestamp(raw: object, label: str) -> str:
    if not isinstance(raw, str):
        raise EvidenceError(f"{label} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError(f"{label} must be a timezone-aware timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_batch(path: str) -> EvidenceBatch:
    with open(path, "rb") as stream:
        raw = stream.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise EvidenceError("evidence file exceeds 512 KiB")
    try:
        return normalize_batch(json.loads(raw))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("evidence file must be UTF-8 JSON") from exc
