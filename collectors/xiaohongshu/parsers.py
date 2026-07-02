from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Iterable

from collectors.base import (
    CollectedComment,
    CollectedContent,
    CollectedProfile,
    CollectedSearchResult,
    CommentPage,
    PageCursor,
    SearchPage,
)
from collectors.xiaohongshu import selectors
from collectors.xiaohongshu.exceptions import ContentNotFoundError, LoginRequiredError, PageExpiredError, SelectorChangedError


def parse_search_page(
    query_text: str,
    raw_text: str,
    *,
    source_url: str,
    cursor: str | None = None,
    limit: int = 20,
) -> SearchPage:
    _raise_for_blocking_page(raw_text, page=selectors.SEARCH)
    documents = _json_documents(raw_text)
    items = _dedupe_by_id(
        _search_result_from_note(candidate, rank=index + 1, source_url=source_url)
        for index, candidate in enumerate(_note_candidates(documents))
    )
    if not items:
        _raise_selector_changed("search results", raw_text, page=selectors.SEARCH)

    page_items = tuple(items[:limit])
    next_cursor = _extract_cursor(documents)
    has_more = bool(next_cursor) or len(items) > limit
    if not next_cursor and len(items) > limit:
        offset = int(cursor or "0")
        next_cursor = str(offset + limit)
    return SearchPage(query_text=query_text, items=page_items, cursor=PageCursor(next_cursor=next_cursor, has_more=has_more))


def parse_content_detail(platform_content_id: str, raw_text: str, *, source_url: str) -> CollectedContent:
    _raise_for_blocking_page(raw_text, page=selectors.CONTENT)
    documents = _json_documents(raw_text)
    for candidate in _note_candidates(documents):
        content_id = _content_id(candidate)
        if content_id == platform_content_id or content_id is None:
            return _content_from_note(candidate, platform_content_id=platform_content_id, source_url=source_url)

    html_note = _html_meta_note(raw_text, platform_content_id=platform_content_id, source_url=source_url)
    if html_note is not None:
        return html_note
    if _looks_not_found(raw_text):
        raise ContentNotFoundError(f"Xiaohongshu content not found: {platform_content_id}")
    _raise_selector_changed("content detail", raw_text, page=selectors.CONTENT)


def parse_comment_page(
    platform_content_id: str,
    raw_text: str,
    *,
    source_url: str,
    cursor: str | None = None,
    limit: int = 20,
) -> CommentPage:
    del source_url
    _raise_for_blocking_page(raw_text, page=selectors.COMMENTS)
    documents = _json_documents(raw_text)
    comments = _dedupe_comments(
        _comment_from_candidate(candidate, platform_content_id=platform_content_id)
        for candidate in _comment_candidates(documents)
    )
    if not comments and not _comment_container_present(raw_text):
        _raise_selector_changed("comments", raw_text, page=selectors.COMMENTS)

    page_items = tuple(comments[:limit])
    next_cursor = _extract_cursor(documents)
    has_more = bool(next_cursor) or len(comments) > limit
    if not next_cursor and len(comments) > limit:
        offset = int(cursor or "0")
        next_cursor = str(offset + limit)
    return CommentPage(platform_content_id=platform_content_id, items=page_items, cursor=PageCursor(next_cursor=next_cursor, has_more=has_more))


def parse_profile(platform_user_id: str, raw_text: str, *, source_url: str) -> CollectedProfile:
    _raise_for_blocking_page(raw_text, page=selectors.PROFILE)
    documents = _json_documents(raw_text)
    for candidate in _profile_candidates(documents):
        user_id = _first_str(candidate, ("user_id", "userId", "id", "userid"))
        if user_id is None or user_id == platform_user_id:
            return CollectedProfile(
                platform="xhs",
                platform_user_id=platform_user_id,
                display_name=_first_str(candidate, ("nickname", "display_name", "name", "nickName")),
                profile_url=source_url,
                bio=_first_str(candidate, ("desc", "bio", "description", "introduction")),
                region_text=_first_str(candidate, ("ip_location", "ipLocation", "location", "region")),
                public_contact_text=_first_str(candidate, ("contact", "public_contact", "publicContact")),
            )
    _raise_selector_changed("profile", raw_text, page=selectors.PROFILE)


def _search_result_from_note(candidate: dict[str, Any], *, rank: int, source_url: str) -> CollectedSearchResult:
    content = _content_from_note(candidate, platform_content_id=_content_id(candidate), source_url=source_url)
    return CollectedSearchResult(
        platform=content.platform,
        platform_content_id=content.platform_content_id,
        platform_author_id=content.platform_author_id,
        content_type=content.content_type,
        title=content.title,
        body_text=content.body_text,
        published_at=content.published_at,
        url=content.url,
        region_text=content.region_text,
        like_count=content.like_count,
        comment_count=content.comment_count,
        collect_count=content.collect_count,
        rank_position=rank,
        result_page=1,
    )


def _content_from_note(candidate: dict[str, Any], *, platform_content_id: str | None, source_url: str) -> CollectedContent:
    note = _unwrap_note(candidate)
    content_id = platform_content_id or _content_id(note)
    if not content_id:
        raise SelectorChangedError("Xiaohongshu note payload is missing an id field.")
    author = _author_dict(note)
    return CollectedContent(
        platform="xhs",
        platform_content_id=content_id,
        platform_author_id=_first_str(author, ("user_id", "userId", "id", "userid")) if author else _first_str(note, ("user_id", "userId", "userIdStr")),
        content_type=_first_str(note, ("type", "note_type", "noteType", "model_type")) or "note",
        title=_first_str(note, ("title", "display_title", "displayTitle")),
        body_text=_first_str(note, ("desc", "description", "content", "note_content", "noteContent")),
        published_at=_parse_datetime(_first_value(note, ("time", "timestamp", "publish_time", "publishTime", "create_time"))),
        url=_first_str(note, ("url", "note_url", "noteUrl")) or f"{selectors.BASE_URL}/explore/{content_id}",
        region_text=_first_str(note, ("ip_location", "ipLocation", "location", "region")),
        like_count=_count(_first_nested_value(note, ("liked_count", "likedCount", "like_count", "likes"))),
        comment_count=_count(_first_nested_value(note, ("comment_count", "commentCount", "comments"))),
        collect_count=_count(_first_nested_value(note, ("collected_count", "collectedCount", "collect_count", "collects"))),
        tags=tuple(_extract_tags(note)),
        image_urls=tuple(_extract_image_urls(note)),
    )


def _comment_from_candidate(candidate: dict[str, Any], *, platform_content_id: str) -> CollectedComment:
    author = _author_dict(candidate)
    comment_id = _first_str(candidate, ("comment_id", "commentId", "id", "commentid"))
    if not comment_id:
        raise SelectorChangedError("Xiaohongshu comment payload is missing an id field.")
    return CollectedComment(
        platform="xhs",
        platform_comment_id=comment_id,
        platform_content_id=platform_content_id,
        platform_author_id=_first_str(author, ("user_id", "userId", "id", "userid")) if author else _first_str(candidate, ("user_id", "userId")),
        parent_platform_comment_id=_first_str(candidate, ("parent_comment_id", "parentCommentId", "target_comment_id")),
        body_text=_first_str(candidate, ("content", "text", "desc")),
        published_at=_parse_datetime(_first_value(candidate, ("create_time", "createTime", "time", "timestamp"))),
        like_count=_count(_first_value(candidate, ("like_count", "likeCount", "liked_count"))),
        reply_count=_count(_first_value(candidate, ("sub_comment_count", "subCommentCount", "reply_count", "replyCount"))),
        region_text=_first_str(candidate, ("ip_location", "ipLocation", "region")),
    )


def _json_documents(raw_text: str) -> tuple[Any, ...]:
    documents: list[Any] = []
    stripped = raw_text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            documents.append(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    for line in raw_text.splitlines():
        line = line.strip()
        if line == stripped or not line or line[0] not in {"{", "["}:
            continue
        try:
            documents.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    parser = _ScriptJSONParser()
    parser.feed(raw_text)
    for script in parser.scripts:
        documents.extend(_json_from_script(script))

    documents.extend(_json_from_script(raw_text))
    return tuple(documents)


def _json_from_script(script_text: str) -> list[Any]:
    found: list[Any] = []
    for candidate in _raw_json_candidates(script_text):
        try:
            found.append(json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return found


def _raw_json_candidates(text: str) -> Iterable[str]:
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        yield stripped
    for pattern in (
        r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>",
        r"window\.__INITIAL_STATE__\s*=\s*({.*?});",
        r"window\.__INITIAL_STATE__\s*=\s*({.*)$",
        r"__INITIAL_STATE__\s*=\s*({.*?});",
    ):
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            yield match.group(1).strip()


def _note_candidates(documents: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for item in _walk_dicts(documents):
        if "note_card" in item and isinstance(item["note_card"], dict):
            yield item
        elif "noteCard" in item and isinstance(item["noteCard"], dict):
            yield item
        elif _content_id(item) and _looks_like_note(item):
            yield item


def _comment_candidates(documents: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for item in _walk_dicts(documents):
        if _first_str(item, ("comment_id", "commentId")):
            yield item


def _profile_candidates(documents: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for item in _walk_dicts(documents):
        if "userInfo" in item and isinstance(item["userInfo"], dict):
            yield item["userInfo"]
        elif "user" in item and isinstance(item["user"], dict):
            yield item["user"]
        elif _first_str(item, ("nickname", "nickName")) and _first_str(item, ("user_id", "userId", "id")):
            yield item


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            yield from _walk_dicts(nested)


def _unwrap_note(candidate: dict[str, Any]) -> dict[str, Any]:
    if "note_card" in candidate and isinstance(candidate["note_card"], dict):
        return _merge_note_wrapper(candidate, "note_card")
    if "noteCard" in candidate and isinstance(candidate["noteCard"], dict):
        return _merge_note_wrapper(candidate, "noteCard")
    return candidate


def _merge_note_wrapper(candidate: dict[str, Any], note_key: str) -> dict[str, Any]:
    note = dict(candidate[note_key])
    for key in ("id", "note_id", "noteId", "model_type", "xsec_token"):
        value = candidate.get(key)
        if value is not None:
            note.setdefault(key, value)
    if candidate.get("id") is not None:
        note.setdefault("note_id", candidate["id"])
    return note


def _looks_like_note(item: dict[str, Any]) -> bool:
    return any(
        key in item
        for key in (
            "title",
            "display_title",
            "liked_count",
            "imageList",
            "image_list",
            "interact_info",
            "cover",
        )
    )


def _content_id(candidate: dict[str, Any]) -> str | None:
    note = _unwrap_note(candidate)
    return _first_str(note, ("note_id", "noteId", "id", "noteid", "note_id_str"))


def _author_dict(candidate: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("user", "author", "userInfo", "owner"):
        value = candidate.get(key)
        if isinstance(value, dict):
            return value
    return None


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def _first_nested_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    value = _first_value(data, keys)
    if value is not None:
        return value
    interact_info = data.get("interact_info")
    if isinstance(interact_info, dict):
        return _first_value(interact_info, keys)
    return None


def _first_str(data: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    if data is None:
        return None
    value = _first_value(data, keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "")
    multiplier = 1
    if text.endswith("万"):
        multiplier = 10000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _extract_tags(note: dict[str, Any]) -> list[str]:
    tags = _first_value(note, ("tag_list", "tagList", "tags"))
    if not isinstance(tags, list):
        return []
    result = []
    for tag in tags:
        if isinstance(tag, dict):
            tag_name = _first_str(tag, ("name", "tag_name", "tagName"))
        else:
            tag_name = str(tag).strip()
        if tag_name:
            result.append(tag_name)
    return result


def _extract_image_urls(note: dict[str, Any]) -> list[str]:
    images = _first_value(note, ("image_list", "imageList", "images", "image_urls"))
    if not isinstance(images, list):
        return []
    result = []
    for image in images:
        if isinstance(image, dict):
            url = _first_str(image, ("url", "trace_id", "original", "thumbnail"))
            if url is None and isinstance(image.get("info_list"), list):
                for item in image["info_list"]:
                    if isinstance(item, dict):
                        url = _first_str(item, ("url", "image_url"))
                        if url:
                            break
        else:
            url = str(image).strip()
        if url and url.startswith("http"):
            result.append(url)
    return result


def _extract_cursor(documents: Iterable[Any]) -> str | None:
    for item in _walk_dicts(documents):
        cursor = _first_str(item, ("cursor", "next_cursor", "nextCursor", "searchId"))
        if cursor:
            return cursor
    return None


def _dedupe_by_id(items: Iterable[CollectedSearchResult]) -> list[CollectedSearchResult]:
    seen: set[str] = set()
    result: list[CollectedSearchResult] = []
    for item in items:
        if item.platform_content_id in seen:
            continue
        seen.add(item.platform_content_id)
        result.append(item)
    return result


def _dedupe_comments(items: Iterable[CollectedComment]) -> list[CollectedComment]:
    seen: set[str] = set()
    result: list[CollectedComment] = []
    for item in items:
        if item.platform_comment_id in seen:
            continue
        seen.add(item.platform_comment_id)
        result.append(item)
    return result


def _raise_for_blocking_page(raw_text: str, *, page: selectors.PageSelectors) -> None:
    if any(marker in raw_text for marker in page.expired_markers):
        raise PageExpiredError(f"Xiaohongshu {page.page_name} page is expired or unavailable.")
    if any(marker in raw_text for marker in page.login_markers):
        raise LoginRequiredError(f"Xiaohongshu {page.page_name} page requires manual login.")


def _raise_selector_changed(target: str, raw_text: str, *, page: selectors.PageSelectors) -> None:
    if not any(marker in raw_text for marker in page.data_markers + page.required_css):
        raise SelectorChangedError(
            f"Xiaohongshu {target} structure was not found. Expected one of {page.required_css} "
            f"or data markers {page.data_markers}."
        )
    raise SelectorChangedError(f"Xiaohongshu {target} data was present but could not be mapped.")


def _looks_not_found(raw_text: str) -> bool:
    return any(marker in raw_text for marker in selectors.CONTENT.expired_markers)


def _comment_container_present(raw_text: str) -> bool:
    return any(marker in raw_text for marker in selectors.COMMENTS.required_css + selectors.COMMENTS.data_markers)


def _html_meta_note(raw_text: str, *, platform_content_id: str, source_url: str) -> CollectedContent | None:
    parser = _MetaParser()
    parser.feed(raw_text)
    title = parser.meta.get("og:title") or parser.title
    description = parser.meta.get("description") or parser.meta.get("og:description")
    if not title and not description:
        return None
    return CollectedContent(
        platform="xhs",
        platform_content_id=platform_content_id,
        platform_author_id=None,
        content_type="note",
        title=title,
        body_text=description,
        published_at=None,
        url=parser.meta.get("og:url") or source_url,
        region_text=None,
        like_count=0,
        comment_count=0,
        collect_count=0,
    )


class _ScriptJSONParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._buffer: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        attr_map = {key: value or "" for key, value in attrs}
        script_type = attr_map.get("type", "")
        script_id = attr_map.get("id", "")
        if script_type in {"application/json", "application/ld+json"} or "INITIAL_STATE" in script_id:
            self._in_script = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_script:
            self.scripts.append("".join(self._buffer))
            self._in_script = False
            self._buffer = []


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag != "meta":
            return
        name = attr_map.get("name") or attr_map.get("property")
        content = attr_map.get("content")
        if name and content:
            self.meta[name] = content

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = data.strip() or self.title

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
