from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from storage.models import LeadScreeningResult


DEFAULT_COMMENT_REPLY_MODEL_NAME = "deepseek-v4-flash"
DEFAULT_API_URL = "https://api.deepseek.com"
_WHITESPACE_RE = re.compile(r"\s+")
_REPEATED_PUNCTUATION_RE = re.compile(r"([，。！？；：,.!?;:])\1+")
_CONTACT_PATTERNS = (
    re.compile(r"(?:加|留|给|发)?微信(?:号)?"),
    re.compile(r"(?:v|w)[xX信]\s*[:：]?[\w-]*"),
    re.compile(r"(?:加|留(?:个|下)?|给|发)(?:v|V)(?:号)?"),
    re.compile(r"(?:v|V)信(?:发|给|留|加|联系)"),
    re.compile(r"(?:手机号|手机号码|电话(?:号码)?|联系方式|联系我)"),
    re.compile(r"1[3-9]\d{9}"),
    re.compile(r"(?:家庭)?住址(?:发|给|告诉|留)(?:我|下)?"),
    re.compile(r"(?:发|给|告诉|留(?:下)?)(?:一下)?(?:家庭)?住址"),
    re.compile(r"(?:地址)(?:发|给|告诉|留)(?:我|下)?"),
    re.compile(r"留(?:下)?地址"),
)
_GUARANTEE_PATTERNS = (
    re.compile(r"保证(?:提分|通过|考过|拿证|成功|结果)"),
    re.compile(r"包(?:过|通过|提分|拿证)"),
    re.compile(r"百分百(?:通过|提分|考过|成功)"),
    re.compile(r"一定(?:通过|提分|考过|成功)"),
    re.compile(r"稳(?:过|通过|提分|考过|拿证)"),
)


@dataclass(frozen=True, slots=True)
class CommentReplyDraft:
    text: str
    model_name: str | None = None


class CommentReplyGenerator(Protocol):
    def generate(self, screening: LeadScreeningResult) -> CommentReplyDraft:
        """Generate one public Xiaohongshu comment reply draft."""


class OpenAICompatibleCommentReplyGenerator:
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
            or os.getenv("COMMENT_REPLY_GENERATION_API_KEY")
            or os.getenv("LLM_LEAD_SCREENING_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        self.model = model or os.getenv("COMMENT_REPLY_GENERATION_MODEL") or os.getenv(
            "LLM_LEAD_SCREENING_MODEL", DEFAULT_COMMENT_REPLY_MODEL_NAME
        )
        self.api_url = _chat_completions_url(
            api_url
            or os.getenv("COMMENT_REPLY_GENERATION_API_URL")
            or os.getenv("LLM_LEAD_SCREENING_API_URL", DEFAULT_API_URL)
        )
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise RuntimeError(
                "COMMENT_REPLY_GENERATION_API_KEY, LLM_LEAD_SCREENING_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY is required"
            )

    def generate(self, screening: LeadScreeningResult) -> CommentReplyDraft:
        body = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是教育咨询评论回复助手。只输出 JSON，不要输出 Markdown。"
                        "先提供对公开评论有帮助的具体回答，再按需附上一句可选的、轻量的私信邀请。"
                        "语气自然、克制、礼貌，不夸大承诺，不索要隐私，不引导添加微信或留下联系方式。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": "输出字段 message。长度不超过 300 个中文字符，适合公开评论区回复。",
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
                outer_content = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"comment reply LLM request failed: HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"comment reply LLM request failed: {exc.reason}") from exc

        try:
            payload = json.loads(outer_content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"comment reply LLM returned invalid outer JSON: {outer_content[:200]!r}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("comment reply LLM returned non-object outer JSON")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("comment reply LLM returned missing choices")
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise RuntimeError("comment reply LLM returned malformed choice")
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("comment reply LLM returned malformed message")
        content = message.get("content")
        if not isinstance(content, str):
            raise RuntimeError("comment reply LLM returned non-string content")

        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"comment reply LLM returned invalid JSON content: {content[:200]!r}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("comment reply LLM returned non-object JSON content")
        generated_message = raw.get("message")
        if not isinstance(generated_message, str) or not generated_message.strip():
            raise RuntimeError("comment reply LLM returned empty message")
        try:
            text = validate_comment_reply_text(generated_message)
        except ValueError as exc:
            raise RuntimeError(f"comment reply LLM returned unsafe message: {exc}") from exc
        return CommentReplyDraft(text=text, model_name=self.model)


def validate_comment_reply_text(text: str) -> str:
    normalized = _normalize_reply_text(text)
    if not normalized:
        raise ValueError("comment reply text is empty")
    if len(normalized) > 300:
        raise ValueError("comment reply text exceeds 300 characters")
    compact = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE).lower()
    if any(pattern.search(compact) for pattern in _CONTACT_PATTERNS) or any(
        pattern.search(compact) for pattern in _GUARANTEE_PATTERNS
    ):
        raise ValueError("comment reply text contains blocked marketing or privacy language")
    return normalized


def _normalize_reply_text(text: str) -> str:
    normalized = _WHITESPACE_RE.sub("", text.strip())
    return _REPEATED_PUNCTUATION_RE.sub(r"\1", normalized)


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
