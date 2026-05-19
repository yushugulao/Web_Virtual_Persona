from __future__ import annotations

import argparse
import imaplib
import json
import os
import re
import shutil
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.header import decode_header
from email.message import Message
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional live external checks for evidence collection.")
    parser.add_argument("--artifact-dir", required=True)
    args = parser.parse_args()
    artifact_dir = Path(args.artifact_dir)
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    live_data = artifact_dir / "live_external_data"
    if live_data.exists():
        shutil.rmtree(live_data)
    (live_data / "sqlite").mkdir(parents=True, exist_ok=True)
    os.environ["PERSONA_RAG_DATA_DIR"] = str(live_data)
    os.environ["PERSONA_RAG_SQLITE_PATH"] = str(live_data / "sqlite" / "persona_rag.sqlite3")
    os.environ["PERSONA_RAG_AUTH_REQUIRED"] = "false"
    os.environ["PERSONA_RAG_AUTH_CHALLENGE_REQUIRED"] = "false"
    os.environ.setdefault("PERSONA_RAG_DEEPSEEK_MODEL", "deepseek-v4-pro")
    os.environ.setdefault("PERSONA_RAG_DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    from fastapi.testclient import TestClient

    from app.backend.core.config import get_settings
    from app.backend.persona_builder.pipeline import run_user_persona_build, start_user_persona_build
    from app.backend.services.metadata_store import MetadataStore
    from app.backend.services.user_persona_upload_service import create_draft_persona, save_generated_markdown_file
    from app.rag.indexes.memory_store import clear_corpus_cache

    get_settings.cache_clear()
    clear_corpus_cache()
    settings = get_settings()
    results: list[dict[str, Any]] = []

    email_address = os.getenv("PERSONA_RAG_SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("PERSONA_RAG_SMTP_PASSWORD", "").strip()
    imap_host = os.getenv("PERSONA_RAG_IMAP_HOST", "imap.163.com").strip()
    imap_port = int(os.getenv("PERSONA_RAG_IMAP_PORT", "993"))
    imap_ssl = os.getenv("PERSONA_RAG_IMAP_SSL", "true").lower() not in {"0", "false", "no", "off"}

    if settings.smtp_host and email_address and smtp_password:
        try:
            code = _send_and_read_verification_code(
                settings=settings,
                email_address=email_address,
                imap_password=smtp_password,
                imap_host=imap_host,
                imap_port=imap_port,
                imap_ssl=imap_ssl,
            )
            import app.backend.main as main_app

            main_app.settings = get_settings()
            with TestClient(main_app.app) as client:
                verify_response = client.post("/auth/verify-email", json={"email": email_address, "code": code})
            if verify_response.status_code != 200:
                raise RuntimeError(f"verify-email returned HTTP {verify_response.status_code}")
            results.append(
                {
                    "name": "smtp_imap_email_verification",
                    "status": "PASS",
                    "email": _mask_email(email_address),
                    "code_found": True,
                }
            )
        except Exception as exc:
            status = "SKIPPED" if _is_external_mail_block(str(exc)) else "FAIL"
            results.append(
                {
                    "name": "smtp_imap_email_verification",
                    "status": status,
                    "smtp_send_attempted": True,
                    "reason" if status == "SKIPPED" else "error": str(exc),
                }
            )
    else:
        results.append({"name": "smtp_imap_email_verification", "status": "SKIPPED", "reason": "SMTP/IMAP env missing"})

    store = MetadataStore(settings.sqlite_path)
    if settings.smtp_host and email_address and smtp_password:
        try:
            import app.backend.main as main_app

            main_app.settings = get_settings()
            with TestClient(main_app.app) as client:
                draft = client.post(
                    "/user-personas/drafts",
                    json={
                        "name": "邮箱来源 live 测试",
                        "description": "验证邮箱来源导入和脱敏。",
                        "web_search_enabled": False,
                    },
                ).json()
                response = client.post(
                    f"/user-personas/{draft['id']}/email/import",
                    json={
                        "email_address": email_address,
                        "password": smtp_password,
                        "imap_host": imap_host,
                        "imap_port": imap_port,
                        "use_ssl": imap_ssl,
                        "mailbox": "INBOX",
                        "subject_filter": "Persona-RAG 注册验证码",
                        "since_days": 1,
                        "max_messages": 1,
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError(f"email import returned HTTP {response.status_code}: {response.text[:160]}")
                payload = response.json()
            results.append(
                {
                    "name": "email_source_import_live",
                    "status": "PASS",
                    "imported_records": payload["imported_records"],
                    "redacted_items": payload["redacted_items"],
                    "file_id": payload["file"]["file_id"],
                }
            )
        except Exception as exc:
            status = "SKIPPED" if _is_external_mail_block(str(exc)) else "FAIL"
            results.append({"name": "email_source_import_live", "status": status, "reason" if status == "SKIPPED" else "error": str(exc)})
    else:
        results.append({"name": "email_source_import_live", "status": "SKIPPED", "reason": "SMTP/IMAP env missing"})

    try:
        import app.backend.main as main_app

        main_app.settings = get_settings()
        with TestClient(main_app.app) as client:
            draft = client.post(
                "/user-personas/drafts",
                json={
                    "name": "QQ来源 live 测试",
                    "description": "验证 QQ 合成样例导入。",
                    "web_search_enabled": False,
                },
            ).json()
            response = client.post(
                f"/user-personas/{draft['id']}/qq/import",
                files=[
                    (
                        "files",
                        (
                            "qq-fixture.txt",
                            "2026-05-19 10:00 同学A: 这个分身测试能保护 QQ:12345678 吗？\n我: 可以，先脱敏再入库。\n".encode(),
                            "text/plain",
                        ),
                    )
                ],
            )
            if response.status_code != 200:
                raise RuntimeError(f"qq import returned HTTP {response.status_code}: {response.text[:160]}")
            payload = response.json()
        results.append(
            {
                "name": "qq_source_import_fixture",
                "status": "PASS",
                "imported_records": payload["imported_records"],
                "redacted_items": payload["redacted_items"],
                "file_id": payload["file"]["file_id"],
            }
        )
    except Exception as exc:
        results.append({"name": "qq_source_import_fixture", "status": "FAIL", "error": str(exc)})

    if settings.deepseek_api_key:
        try:
            persona = create_draft_persona(
                user_id="dev-auth-disabled",
                name="DeepSeek live 构建测试",
                description="一个用于课程设计验收的最小虚拟分身，关注隐私边界、表达风格和证据卡。",
                web_search_enabled=False,
            )
            save_generated_markdown_file(
                user_id="dev-auth-disabled",
                persona_id=persona["persona_id"],
                filename="deepseek_live_material.md",
                markdown=(
                    "# DeepSeek live 构建测试材料\n\n"
                    "这个测试分身说话清楚、温和，喜欢先确认事实再回答。"
                    "它应该避免引用私密原文，并在不确定时说明边界。"
                ),
                parser_chain=["live_external_fixture"],
            )
            started = start_user_persona_build(owner_user_id="dev-auth-disabled", persona_id=persona["persona_id"])
            final = run_user_persona_build(
                owner_user_id="dev-auth-disabled",
                persona_id=persona["persona_id"],
                build_id=started.build["build_id"],
                settings=settings,
            )
            built = store.get_user_persona(persona["persona_id"])
            generated_files = sorted(Path(final["artifact_dir"]).glob("*.json")) if final.get("artifact_dir") else []
            if final["status"] != "succeeded" or not built or built["runtime_status"] != "ready":
                raise RuntimeError(f"DeepSeek build did not succeed: {final.get('status')} {final.get('error')}")
            results.append(
                {
                    "name": "deepseek_live_build",
                    "status": "PASS",
                    "build_id": final["build_id"],
                    "model": final["model"],
                    "persona_id": persona["persona_id"],
                    "runtime_status": built["runtime_status"],
                    "evidence_card_count": final["evidence_card_count"],
                    "artifact_json_files": [path.name for path in generated_files],
                }
            )
        except Exception as exc:
            results.append({"name": "deepseek_live_build", "status": "FAIL", "error": str(exc)})
    else:
        results.append({"name": "deepseek_live_build", "status": "SKIPPED", "reason": "DeepSeek API key missing"})

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "artifact_dir": str(artifact_dir),
        "results": results,
    }
    out_path = artifact_dir / "api" / "live_external_checks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=True, indent=2))
    return 1 if any(result["status"] == "FAIL" for result in results) else 0


def _send_and_read_verification_code(
    *,
    settings: Any,
    email_address: str,
    imap_password: str,
    imap_host: str,
    imap_port: int,
    imap_ssl: bool,
) -> str:
    from app.backend.auth.auth_store import AuthStore
    from app.backend.auth.email import send_verification_email

    store = AuthStore(settings.sqlite_path)
    store.initialize()
    user = store.create_user(
        email=email_address,
        username=f"live-email-{uuid.uuid4().hex[:8]}",
        password=f"Pw-{uuid.uuid4().hex}",
        status="pending_verification",
        email_verified=False,
    )
    code = store.create_email_code(user.id, purpose="register", ttl_minutes=settings.email_verification_ttl_minutes)
    send_verification_email(settings, email_address, code)
    deadline = time.time() + 90
    last_error = ""
    while time.time() < deadline:
        try:
            found = _read_latest_code_from_imap(
                email_address=email_address,
                password=imap_password,
                host=imap_host,
                port=imap_port,
                use_ssl=imap_ssl,
                expected_code=code,
            )
            if found:
                return found
        except Exception as exc:
            last_error = str(exc)
        time.sleep(5)
    raise RuntimeError(f"未能通过 IMAP 读取到本次验证码邮件。{last_error}")


def _read_latest_code_from_imap(
    *,
    email_address: str,
    password: str,
    host: str,
    port: int,
    use_ssl: bool,
    expected_code: str,
) -> str:
    client: imaplib.IMAP4 | imaplib.IMAP4_SSL
    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    try:
        client.login(email_address, password)
        status, select_payload = client.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("IMAP SELECT failed: " + _imap_payload_text(select_payload))
        since = (datetime.now(UTC) - timedelta(days=1)).strftime("%d-%b-%Y")
        status, payload = client.search(None, "SINCE", since)
        if status != "OK":
            return ""
        ids = (payload[0].split() if payload and payload[0] else [])[-20:]
        for message_id in reversed(ids):
            fetch_status, data = client.fetch(message_id, "(RFC822)")
            if fetch_status != "OK":
                continue
            raw = _message_bytes(data)
            if not raw:
                continue
            msg = message_from_bytes(raw)
            subject = _decode_header(msg.get("Subject", ""))
            if "Persona-RAG 注册验证码" not in subject:
                continue
            body = _message_text(msg)
            if expected_code in body:
                return expected_code
            match = re.search(r"(?<!\d)(\d{6})(?!\d)", body)
            if match:
                return match.group(1)
        return ""
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _message_bytes(data: list[Any]) -> bytes:
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return b""


def _imap_payload_text(payload: list[bytes] | tuple[bytes, ...] | None) -> str:
    if not payload:
        return ""
    return " ".join(item.decode("utf-8", errors="replace") for item in payload if isinstance(item, bytes))


def _is_external_mail_block(message: str) -> bool:
    lowered = message.lower()
    return "unsafe login" in lowered or "imap select failed" in lowered or "无法打开邮箱目录" in message


def _decode_header(value: str) -> str:
    parts: list[str] = []
    for raw, charset in decode_header(value or ""):
        if isinstance(raw, bytes):
            parts.append(raw.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(raw)
    return "".join(parts)


def _message_text(msg: Message) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_maintype() == "multipart" or part.get_filename():
                continue
            payload = part.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        return "\n".join(parts)
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace") if payload else ""


def _mask_email(email_address: str) -> str:
    if "@" not in email_address:
        return "<email>"
    name, domain = email_address.split("@", 1)
    if len(name) <= 2:
        return f"{name[:1]}***@{domain}"
    return f"{name[:2]}***@{domain}"


if __name__ == "__main__":
    raise SystemExit(main())
