from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from apps.worker.main import load_adapter
from collectors.mediacrawler import MediaCrawlerConfig, MediaCrawlerXiaohongshuAdapter


def test_mediacrawler_search_runs_command_and_maps_outputs(tmp_path: Path) -> None:
    config = _config(tmp_path)
    calls: list[list[str]] = []

    def fake_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        output_dir = Path(command[command.index("--save_data_path") + 1])
        _write_sample_output(output_dir)
        return subprocess.CompletedProcess(command, 0, stdout="xsec_token=secret-token", stderr="")

    adapter = MediaCrawlerXiaohongshuAdapter(config=config, runner=fake_runner)

    page = adapter.search("KET 没过怎么办", limit=20)

    assert page.cursor.has_more is False
    assert len(page.items) == 2
    assert page.items[0].platform_content_id == "note-001"
    assert page.items[0].platform_author_id == "creator-hash-001"
    assert page.items[0].content_type == "note"
    assert page.items[0].region_text == "福建"
    assert page.items[0].like_count == 31_000
    assert page.items[0].collect_count == 56_000
    assert page.items[0].url == "https://www.xiaohongshu.com/explore/note-001"
    assert "secret-token" not in (config.log_dir / next(config.log_dir.iterdir()).name).read_text(encoding="utf-8")
    assert calls[0][calls[0].index("--keywords") + 1] == "KET 没过怎么办"
    assert calls[0][calls[0].index("--get_comment") + 1] == "true"
    assert calls[0][calls[0].index("--crawler_max_notes_count") + 1] == "20"
    assert Path(calls[0][calls[0].index("--save_data_path") + 1]).is_absolute()


def test_mediacrawler_detail_comments_and_profile_reuse_cached_search_output(tmp_path: Path) -> None:
    config = _config(tmp_path)
    cached_run = config.output_root / "cached-run" / "xhs" / "jsonl"
    cached_run.mkdir(parents=True)
    _write_jsonl(cached_run / "search_contents_2026-07-02.jsonl", [_sample_content("note-001")])
    _write_jsonl(
        cached_run / "search_comments_2026-07-02.jsonl",
        [_sample_comment("comment-001", note_id="note-001"), _sample_comment("comment-002", note_id="note-001")],
    )

    adapter = MediaCrawlerXiaohongshuAdapter(config=config, runner=_unexpected_runner)

    detail = adapter.get_content("note-001")
    comments = adapter.list_comments("note-001", limit=1)
    next_comments = adapter.list_comments("note-001", cursor=comments.cursor.next_cursor, limit=1)
    profile = adapter.get_profile("creator-hash-001")

    assert detail.title == "不报班通过KET，考前1个月做什么"
    assert detail.body_text == "完整正文"
    assert detail.region_text == "福建"
    assert detail.tags == ("KET", "英语培训")
    assert detail.image_urls == ("https://img.example/1.jpg", "https://img.example/2.jpg")
    assert comments.items[0].platform_comment_id == "comment-001"
    assert comments.items[0].region_text == "福州"
    assert comments.cursor.has_more is True
    assert next_comments.items[0].platform_comment_id == "comment-002"
    assert next_comments.cursor.has_more is False
    assert profile.platform_user_id == "creator-hash-001"
    assert profile.display_name == "北***爸"
    assert profile.region_text == "福建"


def test_mediacrawler_maps_alternate_public_region_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    cached_run = config.output_root / "cached-run" / "xhs" / "jsonl"
    cached_run.mkdir(parents=True)
    content = _sample_content("note-001")
    content.pop("ip_location")
    content["ipLocation"] = "厦门"
    comment = _sample_comment("comment-001", note_id="note-001")
    comment.pop("ip_location")
    comment["region"] = "泉州"
    _write_jsonl(cached_run / "search_contents_2026-07-02.jsonl", [content])
    _write_jsonl(cached_run / "search_comments_2026-07-02.jsonl", [comment])

    adapter = MediaCrawlerXiaohongshuAdapter(config=config, runner=_unexpected_runner)

    assert adapter.get_content("note-001").region_text == "厦门"
    assert adapter.get_profile("creator-hash-001").region_text == "厦门"
    assert adapter.list_comments("note-001").items[0].region_text == "泉州"


def test_mediacrawler_proxy_and_pagination_flags_are_passed(tmp_path: Path) -> None:
    config = _config(tmp_path, proxy_server="http://127.0.0.1:7897", assume_has_more=True)
    commands: list[list[str]] = []

    def fake_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        output_dir = Path(command[command.index("--save_data_path") + 1])
        _write_jsonl(output_dir / "xhs" / "jsonl" / "search_contents_2026-07-02.jsonl", [_sample_content("note-001")])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    adapter = MediaCrawlerXiaohongshuAdapter(config=config, runner=fake_runner)

    page = adapter.search("PET 二刷", cursor="page:2", limit=1)

    command = commands[0]
    assert command[command.index("--start") + 1] == "2"
    assert command[command.index("--crawler_max_notes_count") + 1] == "1"
    assert command[command.index("--enable_ip_proxy") + 1] == "true"
    assert command[command.index("--static_proxy_url") + 1] == "http://127.0.0.1:7897"
    assert page.cursor.has_more is True
    assert page.cursor.next_cursor == "page:3"


def test_worker_can_load_mediacrawler_adapter(monkeypatch: Any) -> None:
    monkeypatch.setenv("WORKER_ADAPTER", "mediacrawler")

    adapter = load_adapter("xhs")

    assert isinstance(adapter, MediaCrawlerXiaohongshuAdapter)


def test_worker_defaults_to_mediacrawler_adapter(monkeypatch: Any) -> None:
    monkeypatch.delenv("WORKER_ADAPTER", raising=False)

    adapter = load_adapter("xhs")

    assert isinstance(adapter, MediaCrawlerXiaohongshuAdapter)


def test_mediacrawler_config_from_env_resolves_relative_paths(monkeypatch: Any) -> None:
    monkeypatch.setenv("MEDIACRAWLER_HOME", "third_party/MediaCrawler")
    monkeypatch.setenv("MEDIACRAWLER_PYTHON", "third_party/MediaCrawler/.venv/bin/python")
    monkeypatch.setenv("MEDIACRAWLER_OUTPUT_ROOT", ".runtime/mediacrawler-runs")
    monkeypatch.setenv("MEDIACRAWLER_LOG_DIR", ".runtime/mediacrawler-logs")

    config = MediaCrawlerConfig.from_env()

    assert config.home.is_absolute()
    assert config.python_executable.is_absolute()
    assert str(config.python_executable).endswith("third_party/MediaCrawler/.venv/bin/python")
    assert config.output_root.is_absolute()
    assert config.log_dir is not None
    assert config.log_dir.is_absolute()


def test_mediacrawler_login_state_environment_is_passed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    captured_env: dict[str, str] = {}

    def fake_runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_env.update(kwargs["env"])
        output_dir = Path(command[command.index("--save_data_path") + 1])
        _write_sample_output(output_dir)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    MediaCrawlerXiaohongshuAdapter(config=config, runner=fake_runner).search("孩子英语跟不上", limit=20)

    assert captured_env["MEDIACRAWLER_ENABLE_CDP_MODE"] == "true"
    assert captured_env["MEDIACRAWLER_CDP_CONNECT_EXISTING"] == "false"
    assert captured_env["MEDIACRAWLER_AUTO_CLOSE_BROWSER"] == "false"
    assert captured_env["MEDIACRAWLER_SAVE_LOGIN_STATE"] == "true"
    assert captured_env["MEDIACRAWLER_USER_DATA_DIR"] == "aixhs_%s_user_data_dir"


def _config(
    tmp_path: Path,
    *,
    proxy_server: str | None = None,
    assume_has_more: bool = False,
) -> MediaCrawlerConfig:
    home = tmp_path / "MediaCrawler"
    home.mkdir()
    (home / "main.py").write_text("print('fake')\n", encoding="utf-8")
    python_executable = home / ".venv" / "bin" / "python"
    python_executable.parent.mkdir(parents=True)
    python_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    return MediaCrawlerConfig(
        home=home,
        python_executable=python_executable,
        output_root=tmp_path / "runs",
        login_type="qrcode",
        headless=False,
        get_comments=True,
        get_sub_comments=False,
        max_comments_per_note=3,
        max_concurrency=1,
        timeout_seconds=30,
        assume_has_more=assume_has_more,
        proxy_server=proxy_server,
        log_dir=tmp_path / "logs",
        enable_cdp_mode=True,
        cdp_connect_existing=False,
        cdp_debug_port=9222,
        auto_close_browser=False,
        save_login_state=True,
        user_data_dir="aixhs_%s_user_data_dir",
        custom_browser_path=None,
    )


def _write_sample_output(output_dir: Path) -> None:
    jsonl_dir = output_dir / "xhs" / "jsonl"
    _write_jsonl(
        jsonl_dir / "search_contents_2026-07-02.jsonl",
        [_sample_content("note-001"), _sample_content("note-002")],
    )
    _write_jsonl(jsonl_dir / "search_comments_2026-07-02.jsonl", [_sample_comment("comment-001", note_id="note-001")])


def _sample_content(note_id: str) -> dict[str, Any]:
    return {
        "note_id": note_id,
        "type": "normal",
        "title": "不报班通过KET，考前1个月做什么",
        "desc": "完整正文",
        "time": 1719407007000,
        "creator_hash": "creator-hash-001",
        "nickname": "北***爸",
        "ip_location": "福建",
        "liked_count": "3.1万",
        "collected_count": "5.6万",
        "comment_count": "165",
        "share_count": "638",
        "image_list": "https://img.example/1.jpg,https://img.example/2.jpg",
        "tag_list": "KET,英语培训",
        "note_url": f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token=secret",
        "source_keyword": "KET 没过怎么办",
        "xsec_token": "secret",
    }


def _sample_comment(comment_id: str, *, note_id: str) -> dict[str, Any]:
    return {
        "comment_id": comment_id,
        "create_time": 1735605772000,
        "note_id": note_id,
        "content": "写得特别实在",
        "creator_hash": "commenter-hash-001",
        "nickname": "X***姐",
        "ip_location": "福州",
        "sub_comment_count": "27",
        "pictures": "",
        "parent_comment_id": "",
        "like_count": "10",
    }


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n", encoding="utf-8")


def _unexpected_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    raise AssertionError("cached reads must not run MediaCrawler")
