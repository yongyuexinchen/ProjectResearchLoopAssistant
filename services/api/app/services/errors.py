"""User-facing error text without SQL dumps or driver internals."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError


def user_error_message(exc: BaseException) -> str:
    text = str(exc).strip()
    if isinstance(exc, OperationalError) or "Lost connection to MySQL server" in text:
        return "数据库连接中断，采集/分析结果未能保存。请确认 MySQL 可用后重试。"
    # SQLAlchemy appends the statement and bound parameters after this marker.
    summary = text.split("\n[SQL:", 1)[0].strip()
    return summary[:800] or type(exc).__name__
