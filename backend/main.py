from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api import analysis, auth, companies, metrics, qa, reports, watchlists
from backend.company_profile.router import router as company_profile_router
from backend.schemas.models import AnalyzeRequest, QaRequest
from backend.services.analysis_engine import analyze_periods
from backend.services.container import ServiceContainer
from backend.services.rag_service import answer_question
from backend.support.router import router as support_router


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "app"
STORAGE_DIR = ROOT_DIR / "backend" / "storage"

app = FastAPI(title="财报掘金 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.services = ServiceContainer(STORAGE_DIR)

app.include_router(companies.router)
app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(analysis.router)
app.include_router(qa.router)
app.include_router(metrics.router)
app.include_router(watchlists.router)
app.include_router(support_router)
app.include_router(company_profile_router)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "1.0.0"}


# Compatibility endpoints for the current frontend and earlier MVP.
@app.get("/api/companies/search")
def legacy_search_companies(q: str, market: str = "ALL"):
    return {"items": app.state.services.company_service.search(q, market)}


@app.get("/api/reports/options")
def legacy_report_options(ticker: str, market: str = "US"):
    try:
        company = app.state.services.company_service.resolve(ticker, market)
        periods = app.state.services.report_service.list_options(company)
        return {"company": company, "periods": periods}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/reports/analyze")
def legacy_analyze_report(request: AnalyzeRequest):
    try:
        company = app.state.services.company_service.resolve(request.ticker, request.market)
        dataset = app.state.services.report_service.fetch_financial_dataset(
            company,
            periods=request.periods,
            period_type=request.period_type,
        )
        return analyze_periods(company, dataset, request.periods, request.period_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/qa")
def legacy_qa(request: QaRequest):
    analysis_payload = request.analysis or {}
    return answer_question(request.question, analysis_payload)


if APP_DIR.exists():
    app.mount("/", StaticFiles(directory=str(APP_DIR), html=True), name="frontend")
