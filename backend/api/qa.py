from fastapi import APIRouter

from backend.schemas.models import QaRequest
from backend.services.rag_service import answer_question

router = APIRouter(prefix="/api/qa", tags=["qa"])


@router.post("")
def qa(request: QaRequest):
    analysis = request.analysis or {
        "summary": "当前还没有可用分析结果，请先选择公司并生成财报卡片。",
        "rag_chunks": [],
        "metrics": {},
        "risks": [],
    }
    return answer_question(request.question, analysis)
