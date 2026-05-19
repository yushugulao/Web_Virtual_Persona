from __future__ import annotations

import csv
import email
import html
import imaplib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from io import StringIO
from typing import Any

from app.backend.services.user_persona_upload_service import save_generated_markdown_file


@dataclass(slots=True)
class CommunicationRecord:
    source_kind: str
    record_id: str
    timestamp: str
    sender_role: str
    participants: list[str]
    subject: str
    text: str


@dataclass(slots=True)
class CommunicationImportResult:
    source_kind: str
    imported_records: int
    redacted_items: int
    skipped_records: int
    file: dict
    stats: dict[str, Any]


def import_email_source(
    *,
    user_id: str,
    persona_id: str,
    email_address: str,
    password: str,
    imap_host: str = "imap.163.com",
    imap_port: int = 993,
    use_ssl: bool = True,
    mailbox: str = "INBOX",
    subject_filter: str = "",
    since_days: int = 1,
    max_messages: int = 5,
) -> CommunicationImportResult:
    clean_address = email_address.strip()
    if not clean_address or not password:
        raise ValueError("邮箱地址和授权码不能为空。")
    if max_messages < 1 or max_messages > 50:
        raise ValueError("单次邮箱导入数量必须在 1 到 50 之间。")
    since_days = max(1, min(since_days, 30))
    records: list[CommunicationRecord] = []
    skipped = 0
    client: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
    try:
        client = imaplib.IMAP4_SSL(imap_host, imap_port) if use_ssl else imaplib.IMAP4(imap_host, imap_port)
        client.login(clean_address, password)
        status, select_payload = client.select(mailbox, readonly=True)
        if status != "OK":
            detail = _imap_payload_text(select_payload)
            raise ValueError(f"无法打开邮箱目录：{mailbox}。{detail}")
        since = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%d-%b-%Y")
        status, payload = client.search(None, "SINCE", since)
        if status != "OK":
            raise ValueError("IMAP 搜索失败。")
        message_ids = (payload[0].split() if payload and payload[0] else [])[-max_messages * 10 :]
        for message_id in reversed(message_ids):
            if len(records) >= max_messages:
                break
            fetch_status, data = client.fetch(message_id, "(RFC822)")
            if fetch_status != "OK" or not data:
                skipped += 1
                continue
            raw_bytes = _message_bytes(data)
            if not raw_bytes:
                skipped += 1
                continue
            record = _email_record(raw_bytes, record_id=message_id.decode("ascii", errors="ignore"))
            if subject_filter and subject_filter not in record.subject:
                skipped += 1
                continue
            if not record.text.strip():
                skipped += 1
                continue
            records.append(record)
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                pass
    return _persist_records(
        user_id=user_id,
        persona_id=persona_id,
        source_kind="email",
        records=records,
        skipped_records=skipped,
        filename=f"email_import_{int(time.time())}.md",
        parser_chain=["email_source", "communication_redactor"],
    )


async def import_qq_source(
    *,
    user_id: str,
    persona_id: str,
    files: list[Any],
) -> CommunicationImportResult:
    records: list[CommunicationRecord] = []
    skipped = 0
    for upload in files:
        filename = upload.filename or "qq_chat.txt"
        try:
            raw = await upload.read()
        finally:
            await upload.close()
        parsed, file_skipped = parse_qq_export(filename=filename, content=raw)
        records.extend(parsed)
        skipped += file_skipped
    unique_records = _dedupe_records(records)
    skipped += len(records) - len(unique_records)
    return _persist_records(
        user_id=user_id,
        persona_id=persona_id,
        source_kind="qq",
        records=unique_records,
        skipped_records=skipped,
        filename=f"qq_import_{int(time.time())}.md",
        parser_chain=["qq_chat_source", "communication_redactor"],
    )


def parse_qq_export(*, filename: str, content: bytes) -> tuple[list[CommunicationRecord], int]:
    text = content.decode("utf-8-sig", errors="replace")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    if extension == "json":
        return _parse_qq_json(text)
    if extension == "csv":
        return _parse_qq_csv(text)
    if extension in {"html", "htm"}:
        text = _html_to_text(text)
    return _parse_qq_text(text)


def redact_sensitive(text: str) -> tuple[str, int]:
    count = 0

    def replace(pattern: str, repl: str, value: str, flags: int = 0) -> str:
        nonlocal count
        value, replaced = re.subn(pattern, repl, value, flags=flags)
        count += replaced
        return value

    redacted = text
    redacted = replace(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[邮箱]", redacted)
    redacted = replace(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)", "[手机号]", redacted)
    redacted = replace(r"(?i)\b(?:qq|q\s*q|企鹅号)\s*[:：]?\s*[1-9]\d{4,11}\b", "QQ:[QQ号]", redacted)
    redacted = replace(r"(?<!\d)(?:验证码|校验码|code)\s*[:：]?\s*\d{4,8}(?!\d)", "[验证码]", redacted)
    redacted = replace(r"(?<![A-Za-z0-9])[A-Za-z0-9_./+=-]{28,}(?![A-Za-z0-9])", "[敏感令牌]", redacted)
    return redacted, count


def _persist_records(
    *,
    user_id: str,
    persona_id: str,
    source_kind: str,
    records: list[CommunicationRecord],
    skipped_records: int,
    filename: str,
    parser_chain: list[str],
) -> CommunicationImportResult:
    if not records:
        raise ValueError("没有找到可导入的通信记录。")
    markdown, redacted_items = _records_to_markdown(source_kind=source_kind, records=records)
    row = save_generated_markdown_file(
        user_id=user_id,
        persona_id=persona_id,
        filename=filename,
        markdown=markdown,
        parser_chain=parser_chain,
        quality_score=0.9,
        warnings=[],
    )
    return CommunicationImportResult(
        source_kind=source_kind,
        imported_records=len(records),
        redacted_items=redacted_items,
        skipped_records=skipped_records,
        file=row,
        stats={
            "source_kind": source_kind,
            "record_count": len(records),
            "redacted_items": redacted_items,
            "skipped_records": skipped_records,
        },
    )


def _records_to_markdown(*, source_kind: str, records: list[CommunicationRecord]) -> tuple[str, int]:
    title = "邮箱通信风格材料" if source_kind == "email" else "QQ聊天风格材料"
    lines = [
        "---",
        f'title: "{title}"',
        f'source_kind: "{source_kind}"',
        'privacy_level: "private"',
        'trust_level: "inferred"',
        "---",
        "",
        f"# {title}",
        "",
        "这些材料来自用户主动导入的通信记录。系统只使用脱敏后的表达风格、互动习惯和场景线索，不应直接引用私密原文。",
        "",
    ]
    total_redactions = 0
    for index, record in enumerate(records, 1):
        subject, subject_redactions = redact_sensitive(record.subject)
        text, text_redactions = redact_sensitive(record.text.strip())
        participants = []
        for participant in record.participants:
            clean, redactions = redact_sensitive(participant)
            total_redactions += redactions
            participants.append(clean)
        total_redactions += subject_redactions + text_redactions
        lines.extend(
            [
                f"## 记录 {index}",
                "",
                f"- 来源：{record.source_kind}",
                f"- 时间：{record.timestamp or '未知'}",
                f"- 发送方：{record.sender_role or '未知'}",
                f"- 参与者：{', '.join(participants) if participants else '未知'}",
                f"- 主题：{subject or '无'}",
                "",
                text,
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n", total_redactions


def _message_bytes(data: list[Any]) -> bytes:
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return b""


def _imap_payload_text(payload: list[bytes] | tuple[bytes, ...] | None) -> str:
    if not payload:
        return ""
    return " ".join(item.decode("utf-8", errors="replace") for item in payload if isinstance(item, bytes))


def _email_record(raw: bytes, *, record_id: str) -> CommunicationRecord:
    msg = email.message_from_bytes(raw)
    subject = _decode_header(msg.get("Subject", ""))
    timestamp = _email_date(msg)
    sender = _decode_header(msg.get("From", ""))
    recipients = _decode_header(msg.get("To", ""))
    return CommunicationRecord(
        source_kind="email",
        record_id=record_id,
        timestamp=timestamp,
        sender_role="self_or_contact",
        participants=[part for part in [sender, recipients] if part],
        subject=subject,
        text=_extract_message_text(msg),
    )


def _decode_header(value: str) -> str:
    parts: list[str] = []
    for raw, charset in decode_header(value or ""):
        if isinstance(raw, bytes):
            parts.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(raw)
    return "".join(parts).strip()


def _email_date(msg: Message) -> str:
    try:
        parsed = parsedate_to_datetime(msg.get("Date", ""))
    except Exception:
        parsed = None
    return parsed.isoformat() if parsed else ""


def _extract_message_text(msg: Message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart" or part.get_filename():
                continue
            _append_message_part(part, plain_parts, html_parts)
    else:
        _append_message_part(msg, plain_parts, html_parts)
    if plain_parts:
        return "\n\n".join(part.strip() for part in plain_parts if part.strip())
    return "\n\n".join(_html_to_text(part).strip() for part in html_parts if part.strip())


def _append_message_part(part: Message, plain_parts: list[str], html_parts: list[str]) -> None:
    content_type = part.get_content_type()
    if content_type not in {"text/plain", "text/html"}:
        return
    payload = part.get_payload(decode=True)
    if payload is None:
        return
    charset = part.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="replace")
    if content_type == "text/plain":
        plain_parts.append(text)
    else:
        html_parts.append(text)


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def _parse_qq_json(text: str) -> tuple[list[CommunicationRecord], int]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [], 1
    if isinstance(payload, dict):
        items = payload.get("messages") or payload.get("records") or []
    else:
        items = payload
    records: list[CommunicationRecord] = []
    skipped = 0
    for index, item in enumerate(items if isinstance(items, list) else [], 1):
        if not isinstance(item, dict):
            skipped += 1
            continue
        message = str(item.get("message") or item.get("content") or item.get("text") or "").strip()
        if not message:
            skipped += 1
            continue
        records.append(
            CommunicationRecord(
                source_kind="qq",
                record_id=f"json-{index}",
                timestamp=str(item.get("timestamp") or item.get("time") or item.get("date") or ""),
                sender_role=str(item.get("sender") or item.get("from") or item.get("name") or "unknown"),
                participants=[str(item.get("sender") or item.get("from") or item.get("name") or "unknown")],
                subject=str(item.get("thread") or item.get("group") or "QQ聊天记录"),
                text=message,
            )
        )
    return records, skipped


def _parse_qq_csv(text: str) -> tuple[list[CommunicationRecord], int]:
    reader = csv.DictReader(StringIO(text))
    records: list[CommunicationRecord] = []
    skipped = 0
    for index, row in enumerate(reader, 1):
        message = _first_value(row, "message", "content", "text", "消息", "内容")
        if not message:
            skipped += 1
            continue
        sender = _first_value(row, "sender", "from", "name", "发送者", "昵称") or "unknown"
        records.append(
            CommunicationRecord(
                source_kind="qq",
                record_id=f"csv-{index}",
                timestamp=_first_value(row, "timestamp", "time", "date", "时间") or "",
                sender_role=sender,
                participants=[sender],
                subject=_first_value(row, "thread", "group", "群名", "会话") or "QQ聊天记录",
                text=message,
            )
        )
    return records, skipped


def _parse_qq_text(text: str) -> tuple[list[CommunicationRecord], int]:
    records: list[CommunicationRecord] = []
    skipped = 0
    current_sender = "unknown"
    current_time = ""
    pattern = re.compile(
        r"^\s*(?:\[?(?P<time>\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:日)?\s+\d{1,2}:\d{2}(?::\d{2})?)\]?\s*)?"
        r"(?P<sender>[^:：]{1,40})[:：]\s*(?P<text>.+?)\s*$"
    )
    for index, line in enumerate(text.splitlines(), 1):
        clean = line.strip()
        if not clean:
            continue
        match = pattern.match(clean)
        if match:
            current_sender = match.group("sender").strip()
            current_time = (match.group("time") or current_time).strip()
            message = match.group("text").strip()
        else:
            message = clean
        if not message:
            skipped += 1
            continue
        records.append(
            CommunicationRecord(
                source_kind="qq",
                record_id=f"text-{index}",
                timestamp=current_time,
                sender_role=current_sender,
                participants=[current_sender],
                subject="QQ聊天记录",
                text=message,
            )
        )
    return records, skipped


def _first_value(row: dict[str, Any], *names: str) -> str:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = row.get(name)
        if value is None:
            value = lowered.get(name.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _dedupe_records(records: list[CommunicationRecord]) -> list[CommunicationRecord]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[CommunicationRecord] = []
    for record in records:
        key = (record.timestamp, record.sender_role, record.text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique
