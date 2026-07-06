from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import os
import subprocess
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ControlPanelRecord:
    record_id: str
    fields: dict[str, Any]


class ControlPanelClient(Protocol):
    def list_requested_records(self) -> list[ControlPanelRecord]:
        pass

    def update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        pass


ControlPanelAction = Callable[[ControlPanelRecord], dict[str, Any]]


CONTROL_PANEL_FIELDS = (
    "指令名称",
    "我要做什么",
    "开始执行",
    "现在状态",
    "要找什么",
    "最多看多少条",
    "结果",
    "哪里出错了",
    "开始时间",
    "完成时间",
    "系统记录编号",
)


class LarkCliControlPanelClient:
    def __init__(self, *, base_token: str | None = None, table_id: str | None = None) -> None:
        self.base_token = base_token or os.getenv("FEISHU_CONTROL_PANEL_BASE_TOKEN") or os.getenv("FEISHU_BITABLE_APP_TOKEN")
        self.table_id = table_id or os.getenv("FEISHU_CONTROL_PANEL_TABLE_ID")
        if not self.base_token:
            raise ValueError("缺少飞书多维表格地址配置：FEISHU_CONTROL_PANEL_BASE_TOKEN")
        if not self.table_id:
            raise ValueError("缺少系统控制台表配置：FEISHU_CONTROL_PANEL_TABLE_ID")

    def list_requested_records(self) -> list[ControlPanelRecord]:
        args = [
            "lark-cli",
            "base",
            "+record-list",
            "--base-token",
            self.base_token,
            "--table-id",
            self.table_id,
            "--limit",
            "200",
            "--filter-json",
            json.dumps({"logic": "and", "conditions": [["开始执行", "intersects", ["是，开始"]]]}, ensure_ascii=False),
            "--as",
            "user",
            "--format",
            "json",
        ]
        for field in CONTROL_PANEL_FIELDS:
            args.extend(("--field-id", field))
        payload = self._run(args)
        data = payload["data"]
        records: list[ControlPanelRecord] = []
        for values, record_id in zip(data["data"], data["record_id_list"], strict=True):
            records.append(ControlPanelRecord(record_id=record_id, fields=dict(zip(data["fields"], values, strict=True))))
        return records

    def update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        self._run(
            [
                "lark-cli",
                "base",
                "+record-upsert",
                "--base-token",
                self.base_token,
                "--table-id",
                self.table_id,
                "--record-id",
                record_id,
                "--json",
                json.dumps(fields, ensure_ascii=False),
                "--as",
                "user",
                "--format",
                "json",
            ]
        )

    def _run(self, args: list[str]) -> dict[str, Any]:
        result = subprocess.run(args, check=True, text=True, capture_output=True)
        payload = json.loads(result.stdout)
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", {}).get("message", "飞书表格操作失败"))
        return payload


def run_control_panel_once(
    client: ControlPanelClient,
    *,
    actions: dict[str, ControlPanelAction],
) -> dict[str, int]:
    records = client.list_requested_records()
    result = {"checked": len(records), "started": 0, "completed": 0, "failed": 0, "skipped": 0}
    for record in records:
        if not _is_requested(record):
            result["skipped"] += 1
            continue
        result["started"] += 1
        client.update_record(record.record_id, {"现在状态": "正在处理", "哪里出错了": None, "开始时间": _now_text()})
        try:
            action_name = _single_text(record.fields.get("我要做什么"))
            action = actions.get(action_name)
            if action is None:
                raise ValueError(f"这个操作还不支持：{action_name}")
            action_result = action(record)
            client.update_record(
                record.record_id,
                {
                    "开始执行": "否",
                    "现在状态": "已完成",
                    "结果": _result_message(action_result),
                    "哪里出错了": None,
                    "完成时间": _now_text(),
                },
            )
            result["completed"] += 1
        except Exception as exc:
            client.update_record(
                record.record_id,
                {
                    "开始执行": "否",
                    "现在状态": "出错了",
                    "哪里出错了": str(exc),
                    "完成时间": _now_text(),
                },
            )
            result["failed"] += 1
    return result


def _is_requested(record: ControlPanelRecord) -> bool:
    start = _single_text(record.fields.get("开始执行"))
    status = _single_text(record.fields.get("现在状态"))
    return start == "是，开始" and status != "正在处理"


def _result_message(result: dict[str, Any]) -> str:
    message = result.get("message")
    if message:
        return str(message)
    return "已经处理完成"


def _single_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        if not value:
            return ""
        return str(value[0])
    return str(value)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
