from fastapi import APIRouter, Depends

from backend.api.deps import services
from backend.schemas.models import QaRequest
from backend.services.rag_service import answer_question, answer_with_knowledge

router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.post("")
def qa(request: QaRequest, svc=Depends(services)):
    analysis = request.analysis or {
        "summary": "当前还没有可用分析结果，请先选择公司并生成财报卡片。",
        "rag_chunks": [],
        "metrics": {},
        "risks": [],
    }
    if request.company_id:
        company = next((item for item in svc.store.list("watchlists") if item.get("company", {}).get("id") == request.company_id), None)
        if company:
            resolved = company["company"]
        else:
            ticker = request.company_id.split("-")[-1]
            market = "CN" if request.company_id.startswith("CN-") else "US"
            resolved = svc.company_service.resolve(ticker, market)
        blocks = svc.data_service.knowledge_blocks(resolved, request.question, limit=8)
        return answer_with_knowledge(request.question, analysis, blocks)
    return answer_question(request.question, analysis)
