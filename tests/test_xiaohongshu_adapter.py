from __future__ import annotations

import os
from pathlib import Path

import pytest

from collectors.base import CollectedContent, CollectedProfile, CommentPage, SearchPage
from collectors.xiaohongshu import LoginRequiredError, SelectorChangedError, XiaohongshuAdapter, XiaohongshuBrowserConfig
from collectors.xiaohongshu.browser import BrowserCapture
from collectors.xiaohongshu.parsers import parse_comment_page, parse_content_detail, parse_profile, parse_search_page


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "xhs"


def test_adapter_can_be_instantiated_without_launching_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_BROWSER_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("XHS_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("XHS_SCREENSHOT_DIR", str(tmp_path / "screenshots"))

    adapter = XiaohongshuAdapter()

    assert adapter.platform == "xhs"
    adapter.close()


def test_browser_config_reads_runtime_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_BROWSER_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("XHS_HEADLESS", "true")
    monkeypatch.setenv("XHS_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("XHS_SCREENSHOT_DIR", str(tmp_path / "screenshots"))
    monkeypatch.setenv("XHS_PAGE_TIMEOUT_MS", "12345")
    monkeypatch.setenv("XHS_PROXY_SERVER", "http://127.0.0.1:7897")

    config = XiaohongshuBrowserConfig.from_env()

    assert config.profile_dir == tmp_path / "profile"
    assert config.headless is True
    assert config.snapshot_dir == tmp_path / "snapshots"
    assert config.screenshot_dir == tmp_path / "screenshots"
    assert config.page_timeout_ms == 12345
    assert config.proxy_server == "http://127.0.0.1:7897"


def test_browser_config_reuses_mediacrawler_proxy_when_xhs_proxy_is_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XHS_BROWSER_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.delenv("XHS_PROXY_SERVER", raising=False)
    monkeypatch.setenv("MEDIACRAWLER_PROXY_SERVER", "http://127.0.0.1:7897")

    config = XiaohongshuBrowserConfig.from_env()

    assert config.proxy_server == "http://127.0.0.1:7897"


def test_browser_config_reads_browser_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XHS_BROWSER_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("XHS_BROWSER_ENGINE", "webkit")

    config = XiaohongshuBrowserConfig.from_env()

    assert config.browser_engine == "webkit"


def test_login_page_raises_clear_error() -> None:
    with pytest.raises(LoginRequiredError, match="requires manual login"):
        parse_search_page("KET", _fixture("login_page.html"), source_url="https://www.xiaohongshu.com/search_result")


def test_search_result_maps_to_search_page() -> None:
    page = parse_search_page(
        "KET 没过怎么办",
        _fixture("search_page.html"),
        source_url="https://www.xiaohongshu.com/search_result?keyword=KET",
        limit=20,
    )

    assert isinstance(page, SearchPage)
    assert [item.platform_content_id for item in page.items] == ["xhs-note-001", "xhs-note-002"]
    assert page.items[0].platform == "xhs"
    assert page.items[0].platform_author_id == "xhs-user-001"
    assert page.items[0].title == "KET 没过怎么办，复盘比刷题更重要"
    assert page.items[0].like_count == 12000
    assert page.items[0].rank_position == 1
    assert page.cursor.has_more is True
    assert page.cursor.next_cursor == "cursor-next-1"


def test_search_result_maps_real_web_v2_note_wrapper() -> None:
    raw = """
    {
      "code": 0,
      "data": {
        "has_more": true,
        "items": [
          {
            "id": "6a45d7c00000000017008ff4",
            "model_type": "note",
            "note_card": {
              "display_title": "KTE没过，用这三个问题解决",
              "interact_info": {
                "liked_count": "12",
                "comment_count": "3",
                "collected_count": "4"
              },
              "image_list": [
                {
                  "info_list": [
                    {"image_scene": "WB_DFT", "url": "https://sns-webpic-qc.xhscdn.com/example.jpg"}
                  ]
                }
              ],
              "user": {
                "nickname": "说客英语学习中心",
                "user_id": "63326493000000002303aa8d"
              }
            },
            "xsec_token": "token"
          }
        ]
      },
      "success": true
    }
    """

    page = parse_search_page("KET 没过怎么办", raw, source_url="https://www.xiaohongshu.com/search_result/")

    assert page.items[0].platform_content_id == "6a45d7c00000000017008ff4"
    assert page.items[0].platform_author_id == "63326493000000002303aa8d"
    assert page.items[0].title == "KTE没过，用这三个问题解决"
    assert page.items[0].like_count == 12
    assert page.items[0].comment_count == 3
    assert page.items[0].collect_count == 4


def test_content_detail_maps_to_collected_content() -> None:
    content = parse_content_detail(
        "xhs-note-001",
        _fixture("content_page.html"),
        source_url="https://www.xiaohongshu.com/explore/xhs-note-001",
    )

    assert isinstance(content, CollectedContent)
    assert content.platform_content_id == "xhs-note-001"
    assert content.platform_author_id == "xhs-user-001"
    assert content.body_text.startswith("孩子第一次 KET 没过")
    assert content.comment_count == 38
    assert content.collect_count == 420
    assert content.tags == ("KET", "PET", "少儿英语")
    assert content.image_urls == ("https://example.invalid/xhs-note-001-cover.jpg",)


def test_comments_map_to_comment_page() -> None:
    comments = parse_comment_page(
        "xhs-note-001",
        _fixture("comments_page.html"),
        source_url="https://www.xiaohongshu.com/explore/xhs-note-001",
        limit=20,
    )

    assert isinstance(comments, CommentPage)
    assert [comment.platform_comment_id for comment in comments.items] == ["xhs-comment-001", "xhs-comment-002"]
    assert comments.items[0].platform_author_id == "xhs-user-003"
    assert comments.items[1].parent_platform_comment_id == "xhs-comment-001"
    assert comments.cursor.has_more is True
    assert comments.cursor.next_cursor == "comment-cursor-1"


def test_profile_maps_to_collected_profile() -> None:
    profile = parse_profile(
        "xhs-user-001",
        _fixture("profile_page.html"),
        source_url="https://www.xiaohongshu.com/user/profile/xhs-user-001",
    )

    assert isinstance(profile, CollectedProfile)
    assert profile.platform_user_id == "xhs-user-001"
    assert profile.display_name == "福州英语妈妈"
    assert profile.region_text == "福建"
    assert profile.public_contact_text == "公开主页留言"


def test_missing_optional_fields_do_not_break_batch() -> None:
    raw = '{"items":[{"note_card":{"note_id":"xhs-note-minimal","title":"只有标题","user":{"user_id":"u1"}}}]}'

    page = parse_search_page("孩子英语跟不上", raw, source_url="https://www.xiaohongshu.com/search_result")

    assert page.items[0].platform_content_id == "xhs-note-minimal"
    assert page.items[0].body_text is None
    assert page.items[0].comment_count == 0


def test_critical_selector_failure_is_explicit() -> None:
    with pytest.raises(SelectorChangedError, match="structure was not found"):
        parse_search_page("PET 二刷", _fixture("broken_page.html"), source_url="https://www.xiaohongshu.com/search_result")


def test_adapter_maps_browser_capture_to_protocol_objects() -> None:
    adapter = XiaohongshuAdapter(browser=FakeBrowser())

    assert adapter.search("KET").items[0].platform_content_id == "xhs-note-001"
    assert adapter.get_content("xhs-note-001").platform_content_id == "xhs-note-001"
    assert adapter.list_comments("xhs-note-001").items[0].platform_comment_id == "xhs-comment-001"
    assert adapter.get_profile("xhs-user-001").display_name == "福州英语妈妈"


@pytest.mark.live
def test_live_xiaohongshu_search_requires_opt_in() -> None:
    if os.getenv("RUN_XHS_LIVE") != "1":
        pytest.skip("Set RUN_XHS_LIVE=1 after manual Xiaohongshu login to run live collection.")

    adapter = XiaohongshuAdapter()
    try:
        page = adapter.search("KET 没过怎么办", limit=5)
    finally:
        adapter.close()

    assert page.query_text == "KET 没过怎么办"
    assert len(page.items) > 0


class FakeBrowser:
    def close(self) -> None:
        return None

    def fetch_search_page(self, query_text: str, *, cursor: str | None, limit: int) -> BrowserCapture:
        return _capture("search_page.html", "https://www.xiaohongshu.com/search_result")

    def fetch_content_page(self, platform_content_id: str) -> BrowserCapture:
        return _capture("content_page.html", f"https://www.xiaohongshu.com/explore/{platform_content_id}")

    def fetch_comments_page(self, platform_content_id: str, *, cursor: str | None, limit: int) -> BrowserCapture:
        return _capture("comments_page.html", f"https://www.xiaohongshu.com/explore/{platform_content_id}")

    def fetch_profile_page(self, platform_user_id: str) -> BrowserCapture:
        return _capture("profile_page.html", f"https://www.xiaohongshu.com/user/profile/{platform_user_id}")


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _capture(name: str, url: str) -> BrowserCapture:
    return BrowserCapture(body_text=_fixture(name), url=url, json_payloads=(), html_path=None, json_path=None)
