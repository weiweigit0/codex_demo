from fastapi import APIRouter, Depends, HTTPException, Request

from backend.financial_agent.schema import FinancialAgentRequest


router = APIRouter(prefix="/api/financial-agent", tags=["financial-agent"])


def orchestrator(request: Request):
    return request.app.state.financial_agent_orchestrator


@router.post("/analyses")
def create_analysis(request: FinancialAgentRequest, financial_orchestrator=Depends(orchestrator)):
    return financial_orchestrator.create_analysis(request.ticker, request.market, request.periods, request.period_type, request.include_peer_context)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, financial_orchestrator=Depends(orchestrator)):
    try:
        return financial_orchestrator.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, financial_orchestrator=Depends(orchestrator)):
    try:
        return financial_orchestrator.get_analysis(analysis_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
