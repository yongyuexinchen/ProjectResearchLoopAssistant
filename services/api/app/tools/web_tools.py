from html.parser import HTMLParser
from ipaddress import ip_address
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 4
DEFAULT_MAX_BYTES = 1_000_000
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
Resolver = Callable[[str, int], list[str]]


class WebFetchSafetyError(ValueError):
    """The requested page crosses a network or size boundary."""


class ReadableHTMLParser(HTMLParser):
    """提取网页标题和正文文本，忽略 script/style 这类不可作为证据的内容。"""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self._in_title = False
        self._ignored_depth = 0
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            self.title = " ".join(part.strip() for part in self._title_parts if part.strip()) or None
        if tag in {"script", "style", "noscript"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if not stripped:
            return
        if self._in_title:
            self._title_parts.append(stripped)
            return
        if self._ignored_depth == 0:
            self._text_parts.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._text_parts)


def _system_resolver(host: str, port: int) -> list[str]:
    import socket

    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _ensure_public_target(url: str, resolver: Resolver, allow_private_hosts: bool) -> None:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise WebFetchSafetyError("网页地址格式不正确。") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise WebFetchSafetyError("网页地址必须是 http 或 https URL。")
    if parsed.username or parsed.password:
        raise WebFetchSafetyError("网页地址不能包含账号或密码。")
    if allow_private_hosts:
        return
    try:
        addresses = resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise WebFetchSafetyError("无法解析网页域名。") from exc
    if not addresses:
        raise WebFetchSafetyError("网页域名没有可解析的地址。")
    for raw in addresses:
        try:
            address = ip_address(raw.split("%", 1)[0])
        except ValueError as exc:
            raise WebFetchSafetyError("网页域名解析结果不是有效 IP 地址。") from exc
        if not address.is_global:
            raise WebFetchSafetyError("网页地址指向内网、回环或非公网地址，已拒绝采集。")


def _read_response_text(response: httpx.Response, max_bytes: int) -> tuple[str, str]:
    content_type = response.headers.get("content-type", "")
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise WebFetchSafetyError(f"网页响应超过 {max_bytes} 字节预算，已停止采集。")
        chunks.append(chunk)
    body = b"".join(chunks)
    encoding = response.encoding or "utf-8"
    return body.decode(encoding, errors="replace"), content_type


def fetch_web_url(
    url: str,
    timeout_seconds: float,
    excerpt_chars: int,
    transport: httpx.BaseTransport | None = None,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_private_hosts: bool = False,
    resolver: Resolver | None = None,
) -> dict:
    """读取公开网页并提取短摘要；不执行页面脚本。

    DNS 与每一跳 redirect 都重新检查目标是否为公网地址，并限制响应字节数。
    这不是对 DNS rebinding 的完整防护；生产部署仍应在网络层限制 worker 出站。
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    resolve = resolver or _system_resolver
    with httpx.Client(
        follow_redirects=False,
        timeout=timeout_seconds,
        transport=transport,
    ) as client:
        current_url = url
        for _ in range(MAX_REDIRECTS + 1):
            _ensure_public_target(current_url, resolve, allow_private_hosts)
            with client.stream("GET", current_url) as streamed:
                if streamed.status_code in REDIRECT_STATUSES:
                    location = streamed.headers.get("location")
                    if not location:
                        raise WebFetchSafetyError("网页返回重定向但缺少 Location。")
                    current_url = urljoin(str(streamed.url), location)
                    continue
                streamed.raise_for_status()
                response = streamed
                text, content_type = _read_response_text(streamed, max_bytes)
                final_url = str(streamed.url)
                status_code = streamed.status_code
                break
        else:
            raise WebFetchSafetyError("网页重定向次数过多，已停止采集。")

    title: str | None = None
    if "html" in content_type.lower():
        parser = ReadableHTMLParser()
        parser.feed(text)
        title = parser.title
        text = parser.text

    return {
        "status": "collected",
        "title": title,
        "content_excerpt": text[:excerpt_chars],
        "metadata": {
            "content_type": content_type,
            "final_url": final_url,
            "status_code": status_code,
            "excerpt_chars": min(len(text), excerpt_chars),
        },
        "skipped_items": [],
    }
