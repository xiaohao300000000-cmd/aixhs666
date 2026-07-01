"""Persistence boundary."""

from storage.ingest import (
    IngestReferenceError,
    ingest_comment,
    ingest_content,
    ingest_profile,
    ingest_search_result,
    ingest_search_results,
    upsert_discovery_relation,
)
from storage.snapshots import save_json_snapshot, stable_json_dumps
from storage.text_hash import normalize_text_for_hash, stable_text_hash

__all__ = [
    "IngestReferenceError",
    "ingest_comment",
    "ingest_content",
    "ingest_profile",
    "ingest_search_result",
    "ingest_search_results",
    "normalize_text_for_hash",
    "save_json_snapshot",
    "stable_json_dumps",
    "stable_text_hash",
    "upsert_discovery_relation",
]
