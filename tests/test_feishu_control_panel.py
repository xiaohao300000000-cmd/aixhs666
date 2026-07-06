from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from apps.cli import _build_control_panel_actions, _run_summary
from services.feishu_control_panel import ControlPanelRecord, run_control_panel_once


@dataclass
class FakeControlPanelClient:
    records: list[ControlPanelRecord]
    updates: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def list_requested_records(self) -> list[ControlPanelRecord]:
        return self.records

    def update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        self.updates.append((record_id, fields))


def test_control_panel_does_nothing_without_human_start() -> None:
    client = FakeControlPanelClient(
        [
            ControlPanelRecord(
                record_id="rec_1",
                fields={
                    "指令名称": "找新客户",
                    "我要做什么": "找新客户",
                    "开始执行": "否",
                    "现在状态": "等待开始",
                },
            )
        ]
    )

    result = run_control_panel_once(client, actions={"找新客户": lambda record: {"message": "should not run"}})

    assert result == {"checked": 1, "started": 0, "completed": 0, "failed": 0, "skipped": 1}
    assert client.updates == []


def test_control_panel_runs_one_human_started_record_and_writes_plain_result() -> None:
    client = FakeControlPanelClient(
        [
            ControlPanelRecord(
                record_id="rec_1",
                fields={
                    "指令名称": "找福州PET客户",
                    "我要做什么": "找新客户",
                    "开始执行": "是，开始",
                    "现在状态": "等待开始",
                    "要找什么": "福州 PET",
                    "最多看多少条": 20,
                },
            )
        ]
    )

    result = run_control_panel_once(client, actions={"找新客户": lambda record: {"message": "已开始查找新客户"}})

    assert result == {"checked": 1, "started": 1, "completed": 1, "failed": 0, "skipped": 0}
    assert client.updates[0][0] == "rec_1"
    assert client.updates[0][1]["现在状态"] == "正在处理"
    assert client.updates[-1][0] == "rec_1"
    assert client.updates[-1][1]["开始执行"] == "否"
    assert client.updates[-1][1]["现在状态"] == "已完成"
    assert client.updates[-1][1]["结果"] == "已开始查找新客户"
    assert "完成时间" in client.updates[-1][1]


def test_control_panel_writes_error_in_plain_language() -> None:
    client = FakeControlPanelClient(
        [
            ControlPanelRecord(
                record_id="rec_1",
                fields={
                    "指令名称": "刷新客户表",
                    "我要做什么": "刷新客户表",
                    "开始执行": "是，开始",
                    "现在状态": "等待开始",
                },
            )
        ]
    )

    def fail(_record: ControlPanelRecord) -> dict[str, Any]:
        raise RuntimeError("database is unavailable")

    result = run_control_panel_once(client, actions={"刷新客户表": fail})

    assert result == {"checked": 1, "started": 1, "completed": 0, "failed": 1, "skipped": 0}
    assert client.updates[-1][1]["开始执行"] == "否"
    assert client.updates[-1][1]["现在状态"] == "出错了"
    assert client.updates[-1][1]["哪里出错了"] == "database is unavailable"


def test_control_panel_rejects_unknown_action() -> None:
    client = FakeControlPanelClient(
        [
            ControlPanelRecord(
                record_id="rec_1",
                fields={
                    "指令名称": "未知操作",
                    "我要做什么": "删除所有数据",
                    "开始执行": "是，开始",
                    "现在状态": "等待开始",
                },
            )
        ]
    )

    result = run_control_panel_once(client, actions={})

    assert result["failed"] == 1
    assert client.updates[-1][1]["现在状态"] == "出错了"
    assert client.updates[-1][1]["哪里出错了"] == "这个操作还不支持：删除所有数据"


def test_control_panel_status_action_uses_plain_counts_when_some_counts_are_missing() -> None:
    class FakeRunner:
        def status(self) -> dict[str, Any]:
            return {"counts": {"contents": 3, "comments": 4, "profiles": 5}}

    actions = _build_control_panel_actions(FakeRunner())  # type: ignore[arg-type]

    result = actions["查看系统状态"](ControlPanelRecord(record_id="rec_1", fields={}))

    assert result == {"message": "系统正常。现在有 3 篇内容、4 条评论、5 个用户。"}


def test_control_panel_run_summary_uses_real_collection_counts() -> None:
    result = _run_summary(
        "已经找完新客户",
        {
            "result_data": {
                "collection": {
                    "new_contents": 2,
                    "updated_contents": 3,
                    "new_comments": 4,
                    "updated_comments": 5,
                }
            }
        },
    )

    assert result == "已经找完新客户：找到内容 5 条，找到评论 9 条。"
