from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status

from app.backend.auth.dependencies import require_user
from app.backend.document_reader import SUPPORTED_EXTENSIONS
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.persona_catalog import (
    PersonaCatalogRecommendedResponse,
    PersonaCatalogSearchResponse,
    UserPersonaBuildArtifactsResponse,
    UserPersonaBuildStatusResponse,
    UserPersonaDraftCreateRequest,
    UserPersonaDetail,
    UserPersonaFileItem,
    UserPersonaFileListResponse,
    UserPersonaListResponse,
    UserPersonaParsedFileResponse,
    UserPersonaWebResearchStatusResponse,
    UserPersonaWebSourceItem,
)
from app.backend.core.config import get_settings
from app.backend.persona_builder.pipeline import (
    PersonaBuildError,
    build_artifacts_summary,
    latest_build_status,
    run_user_persona_build,
    start_user_persona_build,
)
from app.backend.persona_builder.web_research import (
    WebResearchError,
    latest_web_research_payload,
    run_web_research,
)
from app.backend.services.metadata_store import MetadataStore
from app.backend.services.persona_catalog_service import (
    create_draft_user_persona,
    get_user_persona_detail,
    list_my_user_personas,
    publish_user_persona,
    recommended_public_user_personas,
    search_persona_catalog,
    unpublish_user_persona,
)
from app.backend.services.user_persona_upload_service import (
    MAX_FILE_SIZE_BYTES,
    MAX_PERSONA_FILES,
    delete_file,
    get_file,
    list_files,
    parse_uploaded_file,
    parsed_file_payload,
    save_upload_file,
)


router = APIRouter(tags=["persona-catalog"], dependencies=[Depends(require_user)])


@router.get("/persona-catalog/search", response_model=PersonaCatalogSearchResponse)
def search_catalog(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=24, ge=1, le=60),
    user: AuthUser = Depends(require_user),
) -> PersonaCatalogSearchResponse:
    return PersonaCatalogSearchResponse(
        query=q,
        results=search_persona_catalog(query=q, user_id=user.id, limit=limit),
    )


@router.get("/persona-catalog/recommended", response_model=PersonaCatalogRecommendedResponse)
def recommended_catalog(
    limit: int = Query(default=5, ge=1, le=10),
    user: AuthUser = Depends(require_user),
) -> PersonaCatalogRecommendedResponse:
    considered, results = recommended_public_user_personas(user_id=user.id, limit=limit)
    return PersonaCatalogRecommendedResponse(candidates_considered=considered, results=results)


@router.get("/user-personas/mine", response_model=UserPersonaListResponse)
def my_user_personas(user: AuthUser = Depends(require_user)) -> UserPersonaListResponse:
    return UserPersonaListResponse(personas=list_my_user_personas(user_id=user.id))


@router.post("/user-personas/drafts", response_model=UserPersonaDetail)
def create_user_persona_draft(
    payload: UserPersonaDraftCreateRequest,
    user: AuthUser = Depends(require_user),
) -> UserPersonaDetail:
    try:
        return create_draft_user_persona(
            user_id=user.id,
            name=payload.name,
            description=payload.description,
            web_search_enabled=payload.web_search_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/user-personas/{persona_id}", response_model=UserPersonaDetail)
def user_persona_detail(persona_id: str, user: AuthUser = Depends(require_user)) -> UserPersonaDetail:
    detail = get_user_persona_detail(persona_id=persona_id, user_id=user.id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="虚拟分身不存在或不可访问。")
    return detail


@router.post("/user-personas/{persona_id}/build", response_model=UserPersonaBuildStatusResponse)
def start_user_persona_build_endpoint(
    persona_id: str,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_user),
) -> UserPersonaBuildStatusResponse:
    try:
        started = start_user_persona_build(owner_user_id=user.id, persona_id=persona_id)
    except PersonaBuildError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    background_tasks.add_task(
        run_user_persona_build,
        owner_user_id=user.id,
        persona_id=persona_id,
        build_id=started.build["build_id"],
    )
    return _build_response(started.build, user_id=user.id)


@router.post("/user-personas/{persona_id}/rebuild", response_model=UserPersonaBuildStatusResponse)
def rebuild_user_persona_endpoint(
    persona_id: str,
    background_tasks: BackgroundTasks,
    user: AuthUser = Depends(require_user),
) -> UserPersonaBuildStatusResponse:
    return start_user_persona_build_endpoint(persona_id=persona_id, background_tasks=background_tasks, user=user)


@router.get("/user-personas/{persona_id}/build", response_model=UserPersonaBuildStatusResponse)
def get_user_persona_build_endpoint(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaBuildStatusResponse:
    build = latest_build_status(owner_user_id=user.id, persona_id=persona_id)
    if build is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="还没有构建记录。")
    return _build_response(build, user_id=user.id)


@router.get("/user-personas/{persona_id}/build-artifacts", response_model=UserPersonaBuildArtifactsResponse)
def get_user_persona_build_artifacts_endpoint(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaBuildArtifactsResponse:
    try:
        payload = build_artifacts_summary(owner_user_id=user.id, persona_id=persona_id)
    except PersonaBuildError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return UserPersonaBuildArtifactsResponse(
        build=_build_response(payload["build"], user_id=user.id),
        source_bundle=payload["source_bundle"],
        quality_summary=payload["quality_summary"],
        generated_files=payload["generated_files"],
        report_markdown=payload["report_markdown"],
    )


@router.post(
    "/user-personas/{persona_id}/web-research/start",
    response_model=UserPersonaWebResearchStatusResponse,
)
def start_user_persona_web_research_endpoint(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaWebResearchStatusResponse:
    settings = get_settings()
    store = MetadataStore(settings.sqlite_path)
    persona = store.get_user_persona(persona_id)
    if persona is None or persona["owner_user_id"] != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="虚拟分身不存在或不可访问。")
    if not settings.web_research_enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="联网资料搜索当前未启用。")
    try:
        run = run_web_research(owner_user_id=user.id, persona_id=persona_id, settings=settings)
    except WebResearchError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _web_research_response(run, user_id=user.id)


@router.get(
    "/user-personas/{persona_id}/web-research",
    response_model=UserPersonaWebResearchStatusResponse,
)
def get_user_persona_web_research_endpoint(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaWebResearchStatusResponse:
    payload = latest_web_research_payload(owner_user_id=user.id, persona_id=persona_id)
    run = payload["run"]
    if run is None:
        return UserPersonaWebResearchStatusResponse(persona_id=persona_id)
    return _web_research_response(run, user_id=user.id)


@router.post(
    "/user-personas/{persona_id}/web-sources/{source_id}/include",
    response_model=UserPersonaWebSourceItem,
)
def include_user_persona_web_source_endpoint(
    persona_id: str,
    source_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaWebSourceItem:
    row = MetadataStore(get_settings().sqlite_path).set_user_persona_web_source_status(
        owner_user_id=user.id,
        persona_id=persona_id,
        source_id=source_id,
        status="included",
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="联网来源不存在。")
    return _web_source_item(row)


@router.post(
    "/user-personas/{persona_id}/web-sources/{source_id}/exclude",
    response_model=UserPersonaWebSourceItem,
)
def exclude_user_persona_web_source_endpoint(
    persona_id: str,
    source_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaWebSourceItem:
    row = MetadataStore(get_settings().sqlite_path).set_user_persona_web_source_status(
        owner_user_id=user.id,
        persona_id=persona_id,
        source_id=source_id,
        status="excluded",
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="联网来源不存在。")
    return _web_source_item(row)


@router.post("/user-personas/{persona_id}/files", response_model=UserPersonaFileItem)
async def upload_user_persona_file(
    persona_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: AuthUser = Depends(require_user),
) -> UserPersonaFileItem:
    try:
        row = await save_upload_file(user_id=user.id, persona_id=persona_id, upload=file)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    background_tasks.add_task(parse_uploaded_file, file_id=row["file_id"])
    return _file_item(row)


@router.get("/user-personas/{persona_id}/files", response_model=UserPersonaFileListResponse)
def list_user_persona_files(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaFileListResponse:
    try:
        rows = list_files(user_id=user.id, persona_id=persona_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return UserPersonaFileListResponse(
        files=[_file_item(row) for row in rows],
        max_files=MAX_PERSONA_FILES,
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
        supported_extensions=sorted(SUPPORTED_EXTENSIONS),
    )


@router.get(
    "/user-personas/{persona_id}/files/{file_id}/parsed",
    response_model=UserPersonaParsedFileResponse,
)
def get_user_persona_parsed_file(
    persona_id: str,
    file_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaParsedFileResponse:
    try:
        row = get_file(user_id=user.id, persona_id=persona_id, file_id=file_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在。")
    payload = parsed_file_payload(row)
    return UserPersonaParsedFileResponse(file=_file_item(row), **{k: v for k, v in payload.items() if k != "file"})


@router.delete("/user-personas/{persona_id}/files/{file_id}")
def delete_user_persona_file(
    persona_id: str,
    file_id: str,
    user: AuthUser = Depends(require_user),
) -> dict[str, str]:
    try:
        deleted = delete_file(user_id=user.id, persona_id=persona_id, file_id=file_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在。")
    return {"message": "文件已删除。"}


@router.post("/user-personas/{persona_id}/publish", response_model=UserPersonaDetail)
def publish_user_persona_endpoint(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaDetail:
    detail = publish_user_persona(persona_id=persona_id, user_id=user.id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="虚拟分身不存在。")
    if detail.runtime_status != "ready":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="这个分身还没有准备好，暂时不能公开。")
    return detail


@router.post("/user-personas/{persona_id}/unpublish", response_model=UserPersonaDetail)
def unpublish_user_persona_endpoint(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> UserPersonaDetail:
    detail = unpublish_user_persona(persona_id=persona_id, user_id=user.id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="虚拟分身不存在。")
    return detail


def _file_item(row: dict) -> UserPersonaFileItem:
    return UserPersonaFileItem(
        file_id=row["file_id"],
        persona_id=row["persona_id"],
        original_filename=row["original_filename"],
        mime_type=row["mime_type"],
        extension=row["extension"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        upload_status=row["upload_status"],
        parse_status=row["parse_status"],
        parser_chain=row["parser_chain"],
        quality_score=row["quality_score"],
        warnings=row["warnings"],
        error_message=row["error_message"],
        page_count=row["page_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _build_response(row: dict, *, user_id: str) -> UserPersonaBuildStatusResponse:
    detail = get_user_persona_detail(persona_id=row["persona_id"], user_id=user_id)
    return UserPersonaBuildStatusResponse(
        build_id=row["build_id"],
        persona_id=row["persona_id"],
        status=row["status"],
        phase=row["phase"],
        progress=row["progress"],
        model=row["model"],
        artifact_dir=row["artifact_dir"],
        source_depth=row["source_depth"],
        evidence_card_count=row["evidence_card_count"],
        error=row["error"],
        quality_summary=row.get("quality_summary", {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
        persona=detail,
    )


def _web_research_response(row: dict, *, user_id: str) -> UserPersonaWebResearchStatusResponse:
    sources = MetadataStore(get_settings().sqlite_path).list_user_persona_web_sources(
        owner_user_id=user_id,
        persona_id=row["persona_id"],
        run_id=row["run_id"],
    )
    return UserPersonaWebResearchStatusResponse(
        run_id=row["run_id"],
        persona_id=row["persona_id"],
        status=row["status"],
        phase=row["phase"],
        progress=row["progress"],
        provider=row["provider"],
        query_count=row["query_count"],
        source_count=row["source_count"],
        included_source_count=row["included_source_count"],
        error=row["error"],
        quality_summary=row.get("quality_summary", {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
        sources=[_web_source_item(source) for source in sources],
    )


def _web_source_item(row: dict) -> UserPersonaWebSourceItem:
    return UserPersonaWebSourceItem(
        source_id=row["source_id"],
        run_id=row["run_id"],
        persona_id=row["persona_id"],
        url=row["url"],
        canonical_url=row["canonical_url"],
        title=row["title"],
        source_family=row["source_family"],
        channel=row["channel"],
        trust_level=row["trust_level"],
        score=row["score"],
        status=row["status"],
        content_hash=row["content_hash"],
        locator=row["locator"],
        warning=row["warning"],
        metadata=row.get("metadata", {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
