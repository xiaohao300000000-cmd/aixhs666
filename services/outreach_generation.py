from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from storage.models import LeadScreeningResult


DEFAULT_OUTREACH_MODEL_NAME = "deepseek-v4-flash"
DEFAULT_API_URL = "https://api.deepseek.com"


@dataclass(frozen=True, slots=True)
class OutreachDraft:
    text: str
    model_name: str | None = None


class OutreachGenerator(Protocol):
    def generate(self, screening: LeadScreeningResult) -> OutreachDraft:
        """Generate one Xiaohongshu direct-message draft."""


class OpenAICompatibleOutreachGenerator:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        api_url: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("OUTREACH_GENERATION_API_KEY")
            or os.getenv("LLM_LEAD_SCREENING_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.model = model or os.getenv("OUTREACH_GENERATION_MODEL") or os.getenv("LLM_LEAD_SCREENING_MODEL", DEFAULT_OUTREACH_MODEL_NAME)
        self.api_url = _chat_completions_url(api_url or os.getenv("OUTREACH_GENERATION_API_URL") or os.getenv("LLM_LEAD_SCREENING_API_URL", DEFAULT_API_URL))
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise RuntimeError("OUTREACH_GENERATION_API_KEY, LLM_LEAD_SCREENING_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY is required")

    def generate(self, screening: LeadScreeningResult) -> OutreachDraft:
        body = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是教育咨询私信话术助手。只输出 JSON，不要输出 Markdown。"
                        "生成一条小红书私信，语气自然、克制、礼貌，不夸大承诺，不索要隐私。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "输出字段 message。长度 80-180 个中文字符，只问一个轻量问题，便于人工确认后发送。",
                            "context": _screening_payload(screening),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"outreach LLM request failed: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"outreach LLM request failed: {exc.reason}") from exc

        content = payload["choices"][0]["message"]["content"]
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"outreach LLM returned invalid JSON content: {str(content)[:200]!r}") from exc
        message = str(raw.get("message") or "").strip()
        if not message:
            raise RuntimeError("outreach LLM returned empty message")
        return OutreachDraft(text=message[:500], model_name=self.model)


def _screening_payload(screening: LeadScreeningResult) -> dict[str, Any]:
    context = screening.context_json or {}
    return {
        "current_comment": context.get("current_comment") or "",
        "post_title": context.get("post_title") or "",
        "post_body": context.get("post_body") or "",
        "parent_comment": context.get("parent_comment") or "",
        "demand_type": screening.demand_type or "",
        "intent_strength": screening.intent_strength or "",
        "status_reason": screening.status_reason or "",
        "qualification_decision": screening.qualification_decision or "",
        "qualification_reason": screening.qualification_human_reason or "",
        "location": screening.qualification_location_json or {},
    }


def _chat_completions_url(api_url: str) -> str:
    base = api_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"
