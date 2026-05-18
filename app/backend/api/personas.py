from fastapi import APIRouter, Depends, HTTPException, status

from app.backend.auth.dependencies import require_user
from app.backend.schemas.auth import AuthUser
from app.backend.schemas.personas import PersonaMaterialsResponse, PersonaProfile
from app.backend.services.persona_material_service import get_persona_materials
from app.backend.services.persona_service import list_personas


router = APIRouter(tags=["personas"], dependencies=[Depends(require_user)])


@router.get("/personas", response_model=list[PersonaProfile])
def list_persona_profiles() -> list[PersonaProfile]:
    return list_personas()


@router.get("/personas/{persona_id}/materials", response_model=PersonaMaterialsResponse)
def persona_materials(
    persona_id: str,
    user: AuthUser = Depends(require_user),
) -> PersonaMaterialsResponse:
    try:
        return get_persona_materials(persona_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="虚拟分身不存在或不可访问。",
        ) from exc
