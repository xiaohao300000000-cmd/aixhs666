from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from collectors.base import (
    CollectedComment,
    CollectedContent,
    CollectedProfile,
    CollectedSearchResult,
    CommentPage,
    PageCursor,
    SearchPage,
)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class MediaCrawlerAdapterError(RuntimeError):
    """Raised when the optional MediaCrawler backend cannot complete a collection request."""


@dataclass(frozen=True, slots=True)
class MediaCrawlerConfig:
    home: Path
    python_executable: Path
    output_root: Path
    login_type: str
    headless: bool
    get_comments: bool
    get_sub_comments: bool
    max_comments_per_note: int
    max_concurrency: int
    timeout_seconds: int
    assume_has_more: bool
    proxy_server: str | None
    log_dir: Path | None
    enable_cdp_mode: bool
    cdp_connect_existing: bool
    cdp_host: str
    cdp_debug_port: int
    auto_close_browser: bool
    save_login_state: bool
    user_data_dir: str
    custom_browser_path: str | None

    @property
    def persistent_profile_dir(self) -> Path:
        profile_name = self.user_data_dir % "xhs"
        if self.enable_cdp_mode:
            profile_name = f"cdp_{profile_name}"
        return self.home / "browser_data" / profile_name

    @classmethod
    def from_env(cls) -> "MediaCrawlerConfig":
        default_home = Path(__file__).resolve().parents[2] / "third_party" / "MediaCrawler"
        home = _absolute_path(Path(os.getenv("MEDIACRAWLER_HOME", str(default_home))).expanduser())
        python_executable = _absolute_path(Path(
            os.getenv("MEDIACRAWLER_PYTHON", str(home / ".venv" / "bin" / "python"))
        ).expanduser())
        log_dir_raw = _empty_to_none(os.getenv("MEDIACRAWLER_LOG_DIR", ".runtime/mediacrawler-logs"))
        return cls(
            home=home,
            python_executable=python_executable,
            output_root=_absolute_path(Path(os.getenv("MEDIACRAWLER_OUTPUT_ROOT", ".runtime/mediacrawler-runs")).expanduser()),
            login_type=os.getenv("MEDIACRAWLER_LOGIN_TYPE", "qrcode"),
            headless=_env_bool("MEDIACRAWLER_HEADLESS", default=False),
            get_comments=_env_bool("MEDIACRAWLER_GET_COMMENTS", default=True),
            get_sub_comments=_env_bool("MEDIACRAWLER_GET_SUB_COMMENTS", default=False),
            max_comments_per_note=int(os.getenv("MEDIACRAWLER_MAX_COMMENTS_PER_NOTE", "3")),
            max_concurrency=int(os.getenv("MEDIACRAWLER_MAX_CONCURRENCY", "1")),
            timeout_seconds=int(os.getenv("MEDIACRAWLER_TIMEOUT_SECONDS", "600")),
            assume_has_more=_env_bool("MEDIACRAWLER_ASSUME_HAS_MORE", default=False),
            proxy_server=_empty_to_none(os.getenv("MEDIACRAWLER_PROXY_SERVER")),
            log_dir=_absolute_path(Path(log_dir_raw).expanduser()) if log_dir_raw else None,
            enable_cdp_mode=_env_bool("MEDIACRAWLER_ENABLE_CDP_MODE", default=True),
            cdp_connect_existing=_env_bool("MEDIACRAWLER_CDP_CONNECT_EXISTING", default=False),
            cdp_host=os.getenv("MEDIACRAWLER_CDP_HOST", "localhost"),
            cdp_debug_port=int(os.getenv("MEDIACRAWLER_CDP_DEBUG_PORT", "9222")),
            auto_close_browser=_env_bool("MEDIACRAWLER_AUTO_CLOSE_BROWSER", default=False),
            save_login_state=_env_bool("MEDIACRAWLER_SAVE_LOGIN_STATE", default=True),
            user_data_dir=os.getenv("MEDIACRAWLER_USER_DATA_DIR", "aixhs_%s_user_data_dir"),
            custom_browser_path=_empty_to_none(os.getenv("MEDIACRAWLER_CUSTOM_BROWSER_PATH")),
        )


class MediaCrawlerXiaohongshuAdapter:
    """Adapter that runs MediaCrawler as an optional subprocess backend.

    MediaCrawler's XHS search mode fetches search results, details, and optional
    comments in one run. This adapter caches those normalized JSONL files so
    later detail/comment worker tasks can reuse the same run instead of hitting
    Xiaohongshu again.
    """

    def __init__(
        self,
        *,
        config: MediaCrawlerConfig | None = None,
        runner: CommandRunner = subprocess.run,
    ) -> None:
        self.config = config or MediaCrawlerConfig.from_env()
        self._runner = runner
        self._contents_by_id: dict[str, dict[str, Any]] = {}
        self._comments_by_content_id: dict[str, list[dict[str, Any]]] = {}
        self._profiles_by_id: dict[str, CollectedProfile] = {}
        self._load_existing_cache()

    @property
    def platform(self) -> str:
        return "xhs"

    def close(self) -> None:
        return None

    def search(self, query_text: str, *, cursor: str | None = None, limit: int = 20) -> SearchPage:
        page_number = _cursor_page(cursor)
        run_dir = self._run_search(query_text=query_text, page_number=page_number, limit=limit)
        contents = self._read_jsonl_files(run_dir, "search_contents_*.jsonl")
        comments = self._read_jsonl_files(run_dir, "search_comments_*.jsonl")
        self._cache_contents(contents)
        self._cache_comments(comments)

        limited_contents = contents[: max(limit, 0)]
        items = tuple(
            _search_result_from_content(item, rank_position=index + 1, result_page=page_number)
            for index, item in enumerate(limited_contents)
        )
        has_more = self.config.assume_has_more and len(contents) >= max(limit, 1)
        return SearchPage(
            query_text=query_text,
            items=items,
            cursor=PageCursor(next_cursor=f"page:{page_number + 1}" if has_more else None, has_more=has_more),
        )

    def get_content(self, platform_content_id: str) -> CollectedContent:
        self._load_existing_cache()
        item = self._contents_by_id.get(platform_content_id)
        if item is None:
            raise MediaCrawlerAdapterError(
                f"MediaCrawler content {platform_content_id} is not in the local cache. "
                "Run a MediaCrawler-backed search first, or provide a cached output root."
            )
        return _content_from_item(item)

    def list_comments(
        self,
        platform_content_id: str,
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CommentPage:
        self._load_existing_cache()
        comments = self._comments_by_content_id.get(platform_content_id, [])
        offset = _cursor_offset(cursor)
        bounded_limit = max(limit, 0)
        page_items = comments[offset : offset + bounded_limit]
        next_offset = offset + len(page_items)
        has_more = next_offset < len(comments)
        return CommentPage(
            platform_content_id=platform_content_id,
            items=tuple(_comment_from_item(item) for item in page_items),
            cursor=PageCursor(next_cursor=f"offset:{next_offset}" if has_more else None, has_more=has_more),
        )

    def get_profile(self, platform_user_id: str) -> CollectedProfile:
        self._load_existing_cache()
        profile = self._profiles_by_id.get(platform_user_id)
        if profile is not None:
            return profile
        return CollectedProfile(
            platform="xhs",
            platform_user_id=platform_user_id,
            display_name=None,
            profile_url=None,
            bio=None,
            region_text=None,
            public_contact_text=None,
        )

    def _run_search(self, *, query_text: str, page_number: int, limit: int) -> Path:
        self._validate_runtime()
        run_dir = (
            self.config.output_root / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        ).resolve()
        run_dir.mkdir(parents=True, exist_ok=True)

        crawler_count = max(1, limit)
        command = [
            str(self.config.python_executable),
            "main.py",
            "--platform",
            "xhs",
            "--lt",
            self.config.login_type,
            "--type",
            "search",
            "--start",
            str(page_number),
            "--keywords",
            query_text,
            "--crawler_max_notes_count",
            str(crawler_count),
            "--get_comment",
            _bool_arg(self.config.get_comments),
            "--max_comments_count_singlenotes",
            str(self.config.max_comments_per_note),
            "--get_sub_comment",
            _bool_arg(self.config.get_sub_comments),
            "--save_data_option",
            "jsonl",
            "--save_data_path",
            str(run_dir),
            "--headless",
            _bool_arg(self.config.headless),
            "--max_concurrency_num",
            str(self.config.max_concurrency),
        ]
        if self.config.proxy_server:
            command.extend(
                [
                    "--enable_ip_proxy",
                    "true",
                    "--ip_proxy_provider_name",
                    "static",
                    "--static_proxy_url",
                    self.config.proxy_server,
                ]
            )

        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env["MEDIACRAWLER_ENABLE_CDP_MODE"] = _bool_arg(self.config.enable_cdp_mode)
        env["MEDIACRAWLER_CDP_CONNECT_EXISTING"] = _bool_arg(self.config.cdp_connect_existing)
        env["MEDIACRAWLER_CDP_HOST"] = self.config.cdp_host
        env["MEDIACRAWLER_CDP_DEBUG_PORT"] = str(self.config.cdp_debug_port)
        env["MEDIACRAWLER_AUTO_CLOSE_BROWSER"] = _bool_arg(self.config.auto_close_browser)
        env["MEDIACRAWLER_SAVE_LOGIN_STATE"] = _bool_arg(self.config.save_login_state)
        env["MEDIACRAWLER_USER_DATA_DIR"] = self.config.user_data_dir
        if self.config.custom_browser_path:
            env["MEDIACRAWLER_CUSTOM_BROWSER_PATH"] = self.config.custom_browser_path
        result = self._runner(
            command,
            cwd=self.config.home,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=self.config.timeout_seconds,
            env=env,
        )
        self._write_log(run_dir.name, command=command, result=result)
        if result.returncode != 0:
            raise MediaCrawlerAdapterError(
                f"MediaCrawler search failed with exit code {result.returncode}; "
                f"run_dir={run_dir}; stderr={_summarize_text(result.stderr)}"
            )
        return run_dir

    def _validate_runtime(self) -> None:
        if not self.config.home.exists():
            raise MediaCrawlerAdapterError(f"MEDIACRAWLER_HOME does not exist: {self.config.home}")
        if not (self.config.home / "main.py").exists():
            raise MediaCrawlerAdapterError(f"MediaCrawler main.py was not found in {self.config.home}")
        if not self.config.python_executable.exists():
            raise MediaCrawlerAdapterError(f"MediaCrawler Python executable does not exist: {self.config.python_executable}")

    def _write_log(self, run_name: str, *, command: Sequence[str], result: subprocess.CompletedProcess[str]) -> None:
        if self.config.log_dir is None:
            return
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        safe_command = " ".join(_sanitize_text(part) for part in command)
        log_text = (
            f"command: {safe_command}\n"
            f"returncode: {result.returncode}\n"
            f"\n[stdout]\n{_sanitize_text(result.stdout)}\n"
            f"\n[stderr]\n{_sanitize_text(result.stderr)}\n"
        )
        (self.config.log_dir / f"{run_name}.log").write_text(log_text, encoding="utf-8")

    def _load_existing_cache(self) -> None:
        if not self.config.output_root.exists():
            return
        self._cache_contents(self._read_jsonl_files(self.config.output_root, "search_contents_*.jsonl"))
        self._cache_comments(self._read_jsonl_files(self.config.output_root, "search_comments_*.jsonl"))

    def _cache_contents(self, contents: Sequence[dict[str, Any]]) -> None:
        for item in contents:
            note_id = _clean_str(item.get("note_id"))
            if note_id is None:
                continue
            self._contents_by_id[note_id] = item
            creator_hash = _clean_str(item.get("creator_hash"))
            if creator_hash:
                self._profiles_by_id[creator_hash] = CollectedProfile(
                    platform="xhs",
                    platform_user_id=creator_hash,
                    display_name=_clean_str(item.get("nickname")),
                    profile_url=None,
                    bio=None,
                    region_text=_public_region_text(item),
                    public_contact_text=None,
                )

    def _cache_comments(self, comments: Sequence[dict[str, Any]]) -> None:
        for item in comments:
            note_id = _clean_str(item.get("note_id"))
            comment_id = _clean_str(item.get("comment_id"))
            if note_id is None or comment_id is None:
                continue
            bucket = self._comments_by_content_id.setdefault(note_id, [])
            if all(existing.get("comment_id") != comment_id for existing in bucket):
                bucket.append(item)
            creator_hash = _clean_str(item.get("creator_hash"))
            if creator_hash:
                self._profiles_by_id.setdefault(
                    creator_hash,
                    CollectedProfile(
                        platform="xhs",
                        platform_user_id=creator_hash,
                        display_name=_clean_str(item.get("nickname")),
                        profile_url=None,
                        bio=None,
                        region_text=_public_region_text(item),
                        public_contact_text=None,
                    ),
                )

    def _read_jsonl_files(self, root: Path, pattern: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(root.glob(f"**/{pattern}")):
            records.extend(_read_jsonl(path))
        return records


def _search_result_from_content(item: dict[str, Any], *, rank_position: int, result_page: int) -> CollectedSearchResult:
    note_id = _required_str(item, "note_id")
    return CollectedSearchResult(
        platform="xhs",
        platform_content_id=note_id,
        platform_author_id=_clean_str(item.get("creator_hash")),
        content_type=_content_type(item),
        title=_clean_str(item.get("title")),
        body_text=_clean_str(item.get("desc")),
        published_at=_datetime_from_ms(item.get("time")),
        url=_safe_note_url(note_id),
        region_text=_public_region_text(item),
        like_count=_parse_count(item.get("liked_count")),
        comment_count=_parse_count(item.get("comment_count")),
        collect_count=_parse_count(item.get("collected_count")),
        rank_position=rank_position,
        result_page=result_page,
    )


def _content_from_item(item: dict[str, Any]) -> CollectedContent:
    note_id = _required_str(item, "note_id")
    return CollectedContent(
        platform="xhs",
        platform_content_id=note_id,
        platform_author_id=_clean_str(item.get("creator_hash")),
        content_type=_content_type(item),
        title=_clean_str(item.get("title")),
        body_text=_clean_str(item.get("desc")),
        published_at=_datetime_from_ms(item.get("time")),
        url=_safe_note_url(note_id),
        region_text=_public_region_text(item),
        like_count=_parse_count(item.get("liked_count")),
        comment_count=_parse_count(item.get("comment_count")),
        collect_count=_parse_count(item.get("collected_count")),
        tags=tuple(_split_csv(item.get("tag_list"))),
        image_urls=tuple(_split_csv(item.get("image_list"))),
    )


def _comment_from_item(item: dict[str, Any]) -> CollectedComment:
    return CollectedComment(
        platform="xhs",
        platform_comment_id=_required_str(item, "comment_id"),
        platform_content_id=_required_str(item, "note_id"),
        platform_author_id=_clean_str(item.get("creator_hash")),
        parent_platform_comment_id=_clean_str(item.get("parent_comment_id")),
        body_text=_clean_str(item.get("content")),
        published_at=_datetime_from_ms(item.get("create_time")),
        like_count=_parse_count(item.get("like_count")),
        reply_count=_parse_count(item.get("sub_comment_count")),
        region_text=_public_region_text(item),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _required_str(item: dict[str, Any], key: str) -> str:
    value = _clean_str(item.get(key))
    if value is None:
        raise MediaCrawlerAdapterError(f"MediaCrawler record is missing {key}: {item}")
    return value


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _absolute_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _public_region_text(item: dict[str, Any]) -> str | None:
    for key in ("ip_location", "ipLocation", "location", "region", "ip_location_text", "ip_location_name"):
        value = _clean_str(item.get(key))
        if value is not None:
            return value
    return None


def _content_type(item: dict[str, Any]) -> str:
    raw_type = _clean_str(item.get("type"))
    if raw_type == "video":
        return "video"
    return "note"


def _datetime_from_ms(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    return datetime.fromtimestamp(numeric / 1000, tz=UTC)


def _parse_count(value: Any) -> int:
    if value in (None, ""):
        return 0
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10_000
        text = text[:-1]
    elif text.endswith("千"):
        multiplier = 1_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def _split_csv(value: Any) -> list[str]:
    text = _clean_str(value)
    if text is None:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def _safe_note_url(note_id: str) -> str:
    return f"https://www.xiaohongshu.com/explore/{note_id}"


def _cursor_page(cursor: str | None) -> int:
    if cursor is None:
        return 1
    if cursor.startswith("page:"):
        return max(1, int(cursor.split(":", 1)[1]))
    return max(1, int(cursor))


def _cursor_offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if cursor.startswith("offset:"):
        return max(0, int(cursor.split(":", 1)[1]))
    return max(0, int(cursor))


def _bool_arg(value: bool) -> str:
    return "true" if value else "false"


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _sanitize_text(value: str) -> str:
    value = re.sub(r"(https?://)[^:/\s]+:[^@\s]+@", r"\1<redacted>@", value)
    value = re.sub(r"(xsec_token=)[^&\s'\"]+", r"\1<redacted>", value)
    value = re.sub(r"('xsec_token':\s*')[^']+", r"\1<redacted>", value)
    value = re.sub(r'("xsec_token":\s*")[^"]+', r'\1<redacted>', value)
    value = re.sub(r"(a1=)[^;\s]+", r"\1<redacted>", value)
    value = re.sub(r"(web_session=)[^;\s]+", r"\1<redacted>", value)
    return value


def _summarize_text(value: str, *, limit: int = 500) -> str:
    sanitized = _sanitize_text(value).strip()
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[:limit] + "...<truncated>"
