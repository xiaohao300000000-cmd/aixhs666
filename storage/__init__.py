"""Persistence boundary with lazy public imports."""

from importlib import import_module
from typing import Any

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

_EXPORT_MODULES = {
    "IngestReferenceError": "storage.ingest",
    "ingest_comment": "storage.ingest",
    "ingest_content": "storage.ingest",
    "ingest_profile": "storage.ingest",
    "ingest_search_result": "storage.ingest",
    "ingest_search_results": "storage.ingest",
    "upsert_discovery_relation": "storage.ingest",
    "save_json_snapshot": "storage.snapshots",
    "stable_json_dumps": "storage.snapshots",
    "normalize_text_for_hash": "storage.text_hash",
    "stable_text_hash": "storage.text_hash",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
