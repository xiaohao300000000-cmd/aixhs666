from __future__ import annotations

from integrations.feishu.comment_replies import CommentReplyPreSubmitError


class XiaohongshuAdapterError(RuntimeError):
    """Base error for Xiaohongshu collection failures."""


class LoginRequiredError(XiaohongshuAdapterError):
    """Raised when the page requires a valid manual login session."""


class PageTimeoutError(XiaohongshuAdapterError):
    """Raised when Xiaohongshu does not finish loading within the configured timeout."""


class PageExpiredError(XiaohongshuAdapterError):
    """Raised when a loaded page is expired or invalid."""


class XiaohongshuNetworkError(XiaohongshuAdapterError):
    """Raised when the browser cannot reach Xiaohongshu over the current network."""


class ContentNotFoundError(XiaohongshuAdapterError):
    """Raised when a requested note or profile does not exist or is unavailable."""


class SelectorChangedError(XiaohongshuAdapterError):
    """Raised when expected page structures or selectors are no longer present."""


class XiaohongshuCommentReplyDefiniteFailure(CommentReplyPreSubmitError):
    """Raised when an XHS comment reply definitely was not submitted."""
