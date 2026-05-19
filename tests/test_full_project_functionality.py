from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.backend.auth.auth_store import AuthStore
from app.backend.auth.dependencies import require_user
from app.backend.core.config import get_settings
from app.backend.document_reader.reader import read_document
from app.backend.persona_builder.pipeline import _build_source_bundle
from app.backend.persona_builder.web_research import build_web_sources_for_deepseek, run_web_research
from app.backend.persona_builder.web_research.adapters import CrawledPage, SearchCandidate, sha256_text
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.chat import ChatRequest, ChatResponse
from app.backend.schemas.common import Citation, TimingBreakdown
from app.backend.schemas.retrieval import RetrievalTrace
from app.backend.services.communication_source_service import parse_qq_export, redact_sensitive
from app.backend.services.metadata_store import MetadataStore
from app.rag.indexes.memory_store import clear_corpus_cache


@pytest.fixture()
def isolated_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    corpus_dir = tmp_path / "corpus"
    data_dir = tmp_path / "data"
    sqlite_path = data_dir / "sqlite" / "persona_rag.sqlite3"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "profile.md").write_text(
        """---
title: "Local Persona Project"
doc_id: "local_persona_profile"
source_type: "profile"
trust_level: "reviewed"
privacy_level: "public"
---

# 项目概览

Web虚拟分身 是一个本地 Persona-RAG 课程设计项目，包含登录、检索、聊天、记忆、反馈、分身创建和社区公开功能。

# 检索锚点

课程设计验收需要能够检索到这个确定性锚点：全项目功能点测试。
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("PERSONA_RAG_CORPUS_DIR", str(corpus_dir))
    monkeypatch.setenv("PERSONA_RAG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("PERSONA_RAG_SQLITE_PATH", str(sqlite_path))
    monkeypatch.setenv("PERSONA_RAG_AUTH_REQUIRED", "false")
    monkeypatch.setenv("PERSONA_RAG_AUTH_CHALLENGE_REQUIRED", "false")
    monkeypatch.setenv("PERSONA_RAG_OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PERSONA_RAG_RETRIEVAL_MODE", "sparse")
    monkeypatch.setenv("PERSONA_RAG_QUERY_REWRITE_ENABLED", "false")
    monkeypatch.setenv("PERSONA_RAG_SOURCE_SELECTOR_ENABLED", "false")
    monkeypatch.setenv("PERSONA_RAG_RERANKER_ENABLED", "false")
    monkeypatch.setenv("PERSONA_RAG_DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("PERSONA_RAG_WEB_RESEARCH_MAX_QUERIES", "4")
    monkeypatch.setenv("PERSONA_RAG_WEB_RESEARCH_MAX_SOURCES", "4")
    monkeypatch.setenv("PERSONA_RAG_WEB_RESEARCH_MAX_INCLUDED_SOURCES", "2")

    get_settings.cache_clear()
    clear_corpus_cache()

    import app.backend.main as main

    main.settings = get_settings()
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as client:
        yield SimpleNamespace(
            client=client,
            settings=get_settings(),
            data_dir=data_dir,
            corpus_dir=corpus_dir,
            sqlite_path=sqlite_path,
            app=main.app,
        )
    main.app.dependency_overrides.clear()
    get_settings.cache_clear()
    clear_corpus_cache()


def test_system_ingest_corpus_retrieval_evidence_and_traces(isolated_app: SimpleNamespace) -> None:
    client = isolated_app.client

    assert client.get("/health").json() == {"status": "ok"}
    status = client.get("/status")
    assert status.status_code == 200
    assert status.json()["deepseek_api_key_configured"] is False

    ingest = client.post("/ingest", json={"rebuild": True})
    assert ingest.status_code == 200
    assert ingest.json()["document_count"] == 1
    assert ingest.json()["chunk_count"] >= 1

    documents = client.get("/documents")
    assert documents.status_code == 200
    assert documents.json()[0]["doc_id"] == "local_persona_profile"

    chunks = client.get("/chunks")
    assert chunks.status_code == 200
    chunk_id = chunks.json()[0]["chunk_id"]
    assert client.get(f"/chunks/{chunk_id}").json()["chunk_id"] == chunk_id

    retrieved = client.post(
        "/retrieve",
        json={"query": "全项目功能点测试", "top_k": 3, "persona_id": "local_persona"},
    )
    assert retrieved.status_code == 200
    retrieved_body = retrieved.json()
    assert retrieved_body["citations"]
    assert retrieved_body["trace"]["selected_chunk_ids"]

    evidence_stats = client.get("/evidence/stats")
    assert evidence_stats.status_code == 200
    assert "total_cards" in evidence_stats.json()
    assert client.post("/evidence/rebuild").status_code == 200

    counts = client.get("/traces/counts").json()
    assert counts["documents"] == 1
    assert counts["chunks"] >= 1
    assert counts["retrieval_events"] >= 1
    assert client.get("/traces/retrievals").json()["rows"]


def test_auth_admin_theme_memory_and_feedback_workflow(isolated_app: SimpleNamespace) -> None:
    client = isolated_app.client
    auth_store = AuthStore(isolated_app.sqlite_path)

    challenge = client.get("/auth/challenge?purpose=login")
    assert challenge.status_code == 200
    assert challenge.json()["purpose"] == "login"

    created = client.post(
        "/admin/users",
        json={
            "email": "report-user@example.test",
            "username": "report-user",
            "password": "Password123!",
            "role": "user",
            "status": "active",
            "email_verified": True,
            "send_verification": False,
        },
    )
    assert created.status_code == 200
    user_id = created.json()["id"]
    assert any(user["id"] == user_id for user in client.get("/admin/users").json()["users"])

    login = client.post(
        "/auth/login",
        json={"login": "report-user", "password": "Password123!"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    logged_in_user = AuthUser.model_validate(login.json()["user"])
    assert auth_store.get_user_by_token(token, client_ip="testclient") is not None

    isolated_app.app.dependency_overrides[require_user] = lambda: logged_in_user
    theme = client.put("/auth/theme-preference", json={"theme": "klee_bomb"})
    assert theme.status_code == 200
    assert theme.json()["theme"] == "klee_bomb"
    isolated_app.app.dependency_overrides.clear()

    disabled = client.post(f"/admin/users/{user_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    enabled = client.post(f"/admin/users/{user_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"
    reset = client.post(
        f"/admin/users/{user_id}/reset-password",
        json={"password": "Password456!", "must_change_password": True},
    )
    assert reset.status_code == 200
    assert reset.json()["must_change_password"] is True

    assert client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert auth_store.get_user_by_token(token, client_ip="testclient") is None

    proposed = client.post(
        "/memory/propose",
        json={
            "persona_id": "local_persona",
            "session_id": "session-memory",
            "content": "用户希望测试报告保留本地证据路径。",
            "tags": ["report"],
        },
    )
    assert proposed.status_code == 200
    memory_id = proposed.json()["item"]["id"]
    assert client.post(f"/memory/{memory_id}/approve").json()["item"]["status"] == "approved"
    assert client.get("/memory/items?scope=all").json()["items"]
    assert client.get("/memory/stats?scope=all").json()["total"] >= 1
    assert client.post("/memory/rebuild-index").status_code == 200

    feedback = client.post(
        "/feedback/persona-turn",
        json={
            "persona_id": "local_persona",
            "persona_name": "Local Persona",
            "session_id": "session-memory",
            "request_id": f"req-{uuid.uuid4().hex}",
            "user_message": "请说明项目功能。",
            "assistant_answer": "项目包含登录、检索、聊天、记忆、反馈与分身创建。",
            "issue": "good",
            "severity": "low",
        },
    )
    assert feedback.status_code == 200
    assert client.get("/feedback/stats").json()["total"] >= 1
    assert client.get("/feedback/persona-turns").json()["records"]
    assert client.get("/feedback/browser-acceptance-matrix").status_code == 200


def test_chat_sessions_stream_release_and_messages(
    isolated_app: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = isolated_app.client

    async def fake_opening(_persona):
        return "你好，我们从一个具体问题开始。"

    async def fake_answer_chat(request: ChatRequest, *, diagnostics_enabled=False, user_context=None):
        citation = Citation(
            chunk_id="chunk-test",
            doc_id="local_persona_profile",
            title="Local Persona Project",
            source_path="corpus/profile.md",
            section_path="项目概览",
            preview="项目包含登录、检索、聊天、记忆、反馈、分身创建和社区公开功能。",
            score=0.99,
            trust_level="reviewed",
            privacy_level="public",
        )
        response = ChatResponse(
            answer="这是用于全项目测试的聊天回答。",
            mode="rag",
            confidence="high",
            citations=[citation],
            retrieval_trace=RetrievalTrace(
                original_query=request.message,
                persona_id=request.persona_id,
                candidates=[citation],
                selected_chunk_ids=[citation.chunk_id],
                notes=["fake deterministic chat"],
            ),
            timings=TimingBreakdown(total_ms=1.0),
            model="fake-model",
            request_id=f"req-{uuid.uuid4().hex}",
            session_id=request.session_id or f"session-{uuid.uuid4().hex}",
        )
        MetadataStore(isolated_app.sqlite_path).record_chat(
            request=request,
            response=response,
            user_id=user_context.user_id if user_context else "dev-auth-disabled",
        )
        return response

    async def fake_stream_chat(request: ChatRequest, *, diagnostics_enabled=False, user_context=None):
        response = await fake_answer_chat(
            request,
            diagnostics_enabled=diagnostics_enabled,
            user_context=user_context,
        )
        yield f"data: {json.dumps({'type': 'final', 'value': response.model_dump(mode='json')}, ensure_ascii=False)}\n\n"

    async def fake_release_model_for_effort(_settings, thinking_effort):
        return True, f"fake-{thinking_effort}"

    async def fake_release_runtime_models(_settings, **_kwargs):
        return {
            "released_models": ["fake-low"],
            "still_loaded_models": [],
            "attempted_models": ["fake-low"],
            "elapsed_ms": 1.0,
            "ok": True,
        }

    import app.backend.api.chat as chat_api

    monkeypatch.setattr(chat_api, "generate_session_opening", fake_opening)
    monkeypatch.setattr(chat_api, "answer_chat", fake_answer_chat)
    monkeypatch.setattr(chat_api, "stream_chat", fake_stream_chat)
    monkeypatch.setattr(chat_api, "release_model_for_effort", fake_release_model_for_effort)
    monkeypatch.setattr(chat_api, "release_runtime_models", fake_release_runtime_models)

    created = client.post("/chat/sessions", json={"persona_id": "local_persona", "title": "验收会话"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    assert created.json()["opening_message"]

    chat = client.post(
        "/chat",
        json={"message": "请说明全项目测试", "session_id": session_id, "persona_id": "local_persona"},
    )
    assert chat.status_code == 200
    assert chat.json()["citations"]

    streamed = client.post(
        "/chat/stream",
        json={"message": "继续说明", "session_id": session_id, "persona_id": "local_persona"},
    )
    assert streamed.status_code == 200
    assert "final" in streamed.text

    messages = client.get(f"/chat/sessions/{session_id}/messages").json()["messages"]
    assert [message["role"] for message in messages].count("user") >= 2
    assert [message["role"] for message in messages].count("assistant") >= 2

    assert client.post("/chat/release-effort-model", json={"thinking_effort": "low"}).json()["released"] is True
    assert client.post(
        "/chat/release-runtime-models",
        json={"thinking_effort": "low", "include_embedding": True},
    ).json()["ok"] is True

    assert client.post(f"/chat/sessions/{session_id}/archive").json()["status"] == "archived"
    assert client.post(f"/chat/sessions/{session_id}/restore").json()["status"] == "active"
    assert client.post(f"/chat/sessions/{session_id}/archive").status_code == 200
    assert client.delete(f"/chat/sessions/{session_id}").status_code == 200


def test_user_persona_upload_build_guard_web_research_and_public_catalog(
    isolated_app: SimpleNamespace,
) -> None:
    client = isolated_app.client
    settings = isolated_app.settings
    store = MetadataStore(isolated_app.sqlite_path)

    draft = client.post(
        "/user-personas/drafts",
        json={
            "name": "雷军测试分身",
            "description": "用于验证联网搜索和分身创建流程的测试分身。",
            "web_search_enabled": True,
        },
    )
    assert draft.status_code == 200
    persona_id = draft.json()["id"]
    assert draft.json()["web_search_enabled"] is True
    assert any(row["id"] == persona_id for row in client.get("/user-personas/mine").json()["personas"])

    uploaded = client.post(
        f"/user-personas/{persona_id}/files",
        files={"file": ("notes.txt", b"Lei Jun and Xiaomi public profile test notes.", "text/plain")},
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()["file_id"]
    files = client.get(f"/user-personas/{persona_id}/files").json()["files"]
    assert any(item["file_id"] == file_id for item in files)
    parsed = client.get(f"/user-personas/{persona_id}/files/{file_id}/parsed")
    assert parsed.status_code == 200
    assert parsed.json()["markdown"]

    build = client.post(f"/user-personas/{persona_id}/build")
    assert build.status_code == 400
    assert "DeepSeek" in build.json()["detail"]

    class FakeSearchProvider:
        def search(self, query: str, *, limit: int) -> list[SearchCandidate]:
            return [
                SearchCandidate(
                    url="https://www.mi.com/about/leijun",
                    title="雷军 - 小米官方资料",
                    snippet=f"{query} founder chairman CEO",
                    channel="fake_search",
                )
            ][:limit]

    class FakeCrawler:
        def crawl(self, url: str) -> CrawledPage:
            text = (
                "雷军 是小米集团创始人、董事长兼 CEO。"
                "这是一段用于全项目测试的公开网页资料，包含足够长的正文来验证联网搜索入库、去重、"
                "来源评分、网页证据摘要和 DeepSeek 构建输入隔离。"
                "雷军 小米 创始人 董事长 CEO 公开资料 访谈 演讲 官方 简介。"
            ) * 3
            return CrawledPage(
                url=url,
                final_url=url,
                title="雷军 - 小米官方资料",
                markdown=f"# 雷军 - 小米官方资料\n\n{text}",
                text=text,
                content_hash=sha256_text(text),
            )

    run = run_web_research(
        owner_user_id="dev-auth-disabled",
        persona_id=persona_id,
        settings=settings,
        search_provider=FakeSearchProvider(),
        crawler=FakeCrawler(),
    )
    assert run["status"] == "succeeded"
    sources = client.get(f"/user-personas/{persona_id}/web-research").json()["sources"]
    assert sources
    assert sources[0]["status"] in {"candidate", "included"}

    included = client.post(f"/user-personas/{persona_id}/web-sources/{sources[0]['source_id']}/include")
    assert included.status_code == 200
    assert included.json()["status"] == "included"
    excluded = client.post(f"/user-personas/{persona_id}/web-sources/{sources[0]['source_id']}/exclude")
    assert excluded.status_code == 200
    assert excluded.json()["status"] == "excluded"
    included = client.post(f"/user-personas/{persona_id}/web-sources/{sources[0]['source_id']}/include")
    assert included.status_code == 200
    assert included.json()["status"] == "included"

    deepseek_sources, web_summary = build_web_sources_for_deepseek(
        owner_user_id="dev-auth-disabled",
        persona_id=persona_id,
        settings=settings,
        auto_run_if_missing=False,
    )
    assert web_summary["web_research_status"] == "succeeded"
    assert deepseek_sources
    assert "document_md" in deepseek_sources[0]

    ready = store.update_user_persona_after_build(
        owner_user_id="dev-auth-disabled",
        persona_id=persona_id,
        runtime_status="ready",
        short_description="公开目录测试分身",
        identity_tags=["联网资料", "测试"],
        source_depth="web",
        evidence_card_count=1,
        corpus_path=str(isolated_app.corpus_dir / "user_personas" / persona_id),
    )
    assert ready is not None
    published = client.post(f"/user-personas/{persona_id}/publish")
    assert published.status_code == 200
    assert published.json()["is_public"] is True

    public_catalog = client.get("/persona-catalog/public?q=公开目录&limit=10&sort=published_at")
    assert public_catalog.status_code == 200
    assert any(item["id"] == persona_id for item in public_catalog.json()["results"])
    assert client.post(f"/user-personas/{persona_id}/unpublish").json()["is_public"] is False
    assert client.delete(f"/user-personas/{persona_id}/files/{file_id}").status_code == 200


def test_communication_source_imports_enter_persona_materials(
    isolated_app: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = isolated_app.client
    store = MetadataStore(isolated_app.sqlite_path)

    draft = client.post(
        "/user-personas/drafts",
        json={
            "name": "通信来源测试分身",
            "description": "用于验证邮箱和 QQ 来源导入。",
            "web_search_enabled": False,
        },
    ).json()
    persona_id = draft["id"]

    message = EmailMessage()
    message["From"] = "sender@example.test"
    message["To"] = "report-user@example.test"
    message["Subject"] = "Persona-RAG live verification marker"
    message["Date"] = "Tue, 19 May 2026 01:00:00 +0800"
    message.set_content("验证码 123456，联系手机 13800138000。请用这封测试邮件验证邮箱导入。")

    class FakeIMAP:
        def __init__(self, host: str, port: int):
            self.host = host
            self.port = port

        def login(self, email: str, password: str) -> tuple[str, list[bytes]]:
            assert email == "report-user@example.test"
            assert password == "authorization-code"
            return "OK", []

        def select(self, mailbox: str, readonly: bool = True) -> tuple[str, list[bytes]]:
            assert mailbox == "INBOX"
            assert readonly is True
            return "OK", [b"1"]

        def search(self, charset: None, *criteria: str) -> tuple[str, list[bytes]]:
            assert charset is None
            assert "SINCE" in criteria
            return "OK", [b"1"]

        def fetch(self, message_id: bytes, query: str) -> tuple[str, list[tuple[bytes, bytes]]]:
            assert message_id == b"1"
            assert query == "(RFC822)"
            return "OK", [(b"RFC822", message.as_bytes())]

        def logout(self) -> tuple[str, list[bytes]]:
            return "OK", []

    monkeypatch.setattr("app.backend.services.communication_source_service.imaplib.IMAP4_SSL", FakeIMAP)

    email_import = client.post(
        f"/user-personas/{persona_id}/email/import",
        json={
            "email_address": "report-user@example.test",
            "password": "authorization-code",
            "imap_host": "imap.example.test",
            "imap_port": 993,
            "subject_filter": "Persona-RAG live verification marker",
            "max_messages": 1,
        },
    )
    assert email_import.status_code == 200
    assert email_import.json()["source_kind"] == "email"
    assert email_import.json()["imported_records"] == 1
    assert email_import.json()["redacted_items"] >= 2
    parsed_email = client.get(
        f"/user-personas/{persona_id}/files/{email_import.json()['file']['file_id']}/parsed"
    ).json()
    assert "[邮箱]" in parsed_email["markdown"]
    assert "[手机号]" in parsed_email["markdown"]
    assert "[验证码]" in parsed_email["markdown"]

    qq_import = client.post(
        f"/user-personas/{persona_id}/qq/import",
        files=[
            (
                "files",
                (
                    "chat.txt",
                    "2026-05-19 09:00 同学A: 这个方案今天能跑通吗？\n我: 可以，先保护隐私再建索引。\n".encode(),
                    "text/plain",
                ),
            ),
            (
                "files",
                (
                    "chat.csv",
                    "time,sender,message\n2026-05-19 09:01,我,QQ:12345678 不要入库原文\n".encode(),
                    "text/csv",
                ),
            ),
        ],
    )
    assert qq_import.status_code == 200
    assert qq_import.json()["source_kind"] == "qq"
    assert qq_import.json()["imported_records"] >= 2
    parsed_qq = client.get(f"/user-personas/{persona_id}/files/{qq_import.json()['file']['file_id']}/parsed").json()
    assert "QQ聊天风格材料" in parsed_qq["markdown"]
    assert "QQ:[QQ号]" in parsed_qq["markdown"]

    persona = store.get_user_persona(persona_id)
    assert persona is not None
    bundle = _build_source_bundle(store, "dev-auth-disabled", persona, settings=isolated_app.settings)
    filenames = {item["filename"] for item in bundle["parsed_files"]}
    assert email_import.json()["file"]["original_filename"] in filenames
    assert qq_import.json()["file"]["original_filename"] in filenames


def test_qq_parser_formats_and_redaction() -> None:
    redacted, count = redact_sensitive(
        "邮箱 a@example.com 手机 13800138000 QQ:12345678 验证码 123456 token abcdefghijklmnopqrstuvwxyz123456"
    )
    assert count >= 5
    assert "a@example.com" not in redacted
    assert "13800138000" not in redacted
    assert "12345678" not in redacted

    samples = [
        ("chat.json", b'[{"time":"2026-05-19","sender":"A","message":"json message"}]'),
        ("chat.csv", "time,sender,message\n2026-05-19,A,csv message\n".encode()),
        ("chat.html", "<p>2026-05-19 10:00 A: html message</p>".encode()),
        ("chat.txt", "2026-05-19 10:00 A: txt message\n".encode()),
    ]
    for filename, content in samples:
        records, skipped = parse_qq_export(filename=filename, content=content)
        assert records, filename
        assert skipped == 0


def test_document_reader_basic_files_and_capability_scripts(tmp_path: Path) -> None:
    raw = tmp_path / "sample.csv"
    raw.write_text("name,value\nWebVirtualPersona,full-project-test\n", encoding="utf-8")
    output = tmp_path / "parsed"

    result = read_document(
        raw,
        output,
        original_filename="sample.csv",
        mime_type="text/csv",
        file_id="file-report",
    )

    assert Path(result.markdown_path).is_file()
    assert Path(result.blocks_path).is_file()
    assert Path(result.provenance_path).is_file()
    assert Path(result.diagnostics_path).is_file()
    assert result.quality_score > 0
    assert "WebVirtualPersona" in Path(result.markdown_path).read_text(encoding="utf-8")

    for script in [
        Path("scripts/document_reader/check_backends.py"),
        Path("scripts/security/scan_secrets.py"),
        Path("scripts/release/create_public_export.py"),
        Path("scripts/deploy/portable_deploy.py"),
    ]:
        source = script.read_text(encoding="utf-8")
        compile(source, str(script), "exec")

    assert sys.version_info >= (3, 11)
