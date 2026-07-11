from __future__ import annotations

from dataclasses import dataclass


BASE_URL = "https://www.xiaohongshu.com"
SEARCH_URL = f"{BASE_URL}/search_result/"
CONTENT_URL_TEMPLATE = f"{BASE_URL}/explore/{{platform_content_id}}"
PROFILE_URL_TEMPLATE = f"{BASE_URL}/user/profile/{{platform_user_id}}"


@dataclass(frozen=True, slots=True)
class PageSelectors:
    page_name: str
    required_css: tuple[str, ...]
    data_markers: tuple[str, ...]
    login_markers: tuple[str, ...] = ("login-container", "验证码", "登录后查看", "手机号登录")
    expired_markers: tuple[str, ...] = ("页面不存在", "内容无法查看", "笔记不存在", "该内容已无法查看")


SEARCH = PageSelectors(
    page_name="search",
    required_css=(".feeds-container", ".note-item", "[data-xhs-role='search-result']"),
    data_markers=("note_card", "noteCard", "items", "feeds"),
)

CONTENT = PageSelectors(
    page_name="content",
    required_css=(".note-content", ".interaction-container", "[data-xhs-role='note-detail']"),
    data_markers=("note", "note_card", "noteCard", "imageList"),
)

COMMENTS = PageSelectors(
    page_name="comments",
    required_css=(".comments-container", ".comment-item", "[data-xhs-role='comment']"),
    data_markers=("comments", "comment_id", "commentId", "sub_comments"),
)

PROFILE = PageSelectors(
    page_name="profile",
    required_css=(".user", ".user-info", "[data-xhs-role='profile']"),
    data_markers=("user", "userInfo", "nickname", "desc"),
)


XHS_RESPONSE_URL_MARKERS = (
    "/api/",
    "/web_api/",
    "/api/sns/",
    "/web/v1/",
    "/search/",
    "/note/",
    "/comment/",
    "/user/",
)

COMMENT_REPLY_BUTTONS = (
    ".reply-button",
    "[data-xhs-role='comment-reply']",
    "[aria-label='回复']",
)
COMMENT_REPLY_EDITORS = (
    "textarea",
    "[contenteditable='true']",
    "input[type='text']",
)
COMMENT_REPLY_SUBMITS = (
    "[data-xhs-role='comment-reply-submit']",
    ".comment-reply-submit",
    "button[type='submit']",
)
COMMENT_REPLY_LOGIN_OR_CAPTCHA_MARKERS = (
    "login-container",
    "验证码",
    "滑块验证",
    "登录后查看",
    "手机号登录",
)
COMMENT_REPLY_REJECTION_MARKERS = (
    "操作频繁，请稍后再试",
    "发布失败",
    "评论失败",
    "内容不符合社区规范",
    "暂时无法回复",
)
COMMENT_REPLY_SUCCESS_MARKERS = (
    "回复成功",
    "发布成功",
    "评论成功",
)
