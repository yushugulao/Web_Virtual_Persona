from fastapi import APIRouter, Depends, HTTPException, Query

from app.backend.auth.dependencies import require_admin
from app.backend.schemas.evals import EvalCaseResult, EvalRunListItem, EvalRunRequest, EvalRunResponse
from app.backend.services.eval_service import eval_run_results, recent_eval_runs, run_eval


router = APIRouter(tags=["evals"], dependencies=[Depends(require_admin)])


@router.post("/eval/run", response_model=EvalRunResponse)
async def run_eval_endpoint(request: EvalRunRequest) -> EvalRunResponse:
    try:
        return await run_eval(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/eval/runs", response_model=list[EvalRunListItem])
def list_eval_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[EvalRunListItem]:
    return recent_eval_runs(limit=limit)


@router.get("/eval/runs/{run_id}/results", response_model=list[EvalCaseResult])
def get_eval_run_results(run_id: str) -> list[EvalCaseResult]:
    return eval_run_results(run_id)
