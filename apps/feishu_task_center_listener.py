from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

from integrations.feishu.im import FeishuIMClient
from runtime_env import load_dotenv
from services.feishu_task_center import apply_task_center_callback, is_task_center_callback
from services.feishu_task_center_events import event_to_callback_payload
from storage.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def handle_event(event: dict[str, object]) -> None:
    payload = event_to_callback_payload(event)
    if not is_task_center_callback(payload):
        return
    with SessionLocal() as session:
        try:
            result = apply_task_center_callback(session, payload, verification_token=None, client=FeishuIMClient())
            session.commit()
            logger.info("task center event accepted run_id=%s status=%s", result.get("run_id"), result.get("status"))
        except Exception:
            session.rollback()
            logger.exception("task center event failed")


def main() -> int:
    load_dotenv()
    command = [os.getenv("FEISHU_LARK_CLI_BIN", "lark-cli"), "event", "consume", "card.action.trigger", "--as", "bot"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=sys.stderr, text=True, bufsize=1)
    assert process.stdout is not None
    try:
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("ignored non-JSON card event")
                continue
            if isinstance(event, dict):
                handle_event(event)
    except KeyboardInterrupt:
        process.terminate()
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
