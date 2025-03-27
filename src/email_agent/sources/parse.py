"""RFC 822 -> (from, subject, body text). Stdlib only."""

from __future__ import annotations

import email
import email.policy
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from html.parser import HTMLParser


@dataclass(slots=True)
class ParsedEmail:
    from_addr: str
    from_name: str
    subject: str
    body_text: str
    date: str | None


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "head", "title"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "br":
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        lines = [ln.strip() for ln in "".join(self._chunks).splitlines()]
        return "\n".join(ln for ln in lines if ln)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.text()


def _decode(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _header(msg: Message, name: str) -> str:
    val = msg.get(name)
    if not val:
        return ""
    try:
        return str(make_header(decode_header(val)))
    except Exception:  # noqa: BLE001 - malformed headers are common in the wild
        return str(val)


def parse_raw(raw: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(raw, policy=email.policy.compat32)
    name, addr = parseaddr(_header(msg, "From"))
    plain: list[str] = []
    html: list[str] = []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ct = part.get_content_type()
        if ct == "text/plain":
            plain.append(_decode(part))
        elif ct == "text/html":
            html.append(_decode(part))
    body = "\n".join(plain).strip() or html_to_text("\n".join(html))
    return ParsedEmail(
        from_addr=addr.lower(),
        from_name=name,
        subject=_header(msg, "Subject"),
        body_text=body.strip(),
        date=msg.get("Date"),
    )
