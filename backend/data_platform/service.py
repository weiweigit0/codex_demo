from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread
from typing import Optional

from backend.company_profile.wikipedia_client import EncyclopediaClient
from backend.data_platform.knowledge_repository import KnowledgeRepository
from backend.data_platform.knowledge_schema import source_authority
from backend.data_platform.document_processor import DocumentProcessor
from backend.data_platform.financial_quality import assess_record, fact_id
from backend.data_platform.repository import DataRepository, json_hash, utc_now
from backend.data_sources.ashare_source import AShareSource
from backend.repositories.sqlite_store import SQLiteStore
from backend.services.sec_client import SecClient, SecClientError


DOCUMENT_INDEX_TTL = timedelta(days=1)
ENCYCLOPEDIA_TTL = timedelta(days=45)
PROFILE_TTL = timedelta(days=30)


class DataService:
    """Cache-first access to public disclosures, reference pages and derived artifacts."""

    def __init__(self, storage_dir: Path, sqlite_store: SQLiteStore):
        self.storage_dir = storage_dir
        self.assets_dir = storage_dir / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.repository = DataRepository(sqlite_store)
        self.knowledge = KnowledgeRepository(sqlite_store)
        self.document_processor = DocumentProcessor()
        self.sec_client = SecClient()
        self.ashare_source = AShareSource()
        self.encyclopedia_client = EncyclopediaClient()

    def search_companies(self, query: str, market: str = "ALL") -> list[dict]:
        normalized = _market(market)
        cached = self.repository.search_companies(query, normalized)
        if cached:
            return cached
        results = []
        if normalized in {"ALL", "US"}:
            try:
                results.extend(self.sec_client.search_companies(query))
            except SecClientError:
                pass
        if normalized in {"ALL", "CN"}:
            results.extend(self.ashare_source.search_companies(query))
        return [self._remember_company(_normalize_company(item)) for item in results]

    def resolve_company(self, ticker_or_name: str, market: str = "US", force: bool = False) -> dict:
        normalized = _market(market)
        if normalized == "ALL":
            normalized = "CN" if _looks_cn_ticker(ticker_or_name) else "US"
        if not force:
            cached = self.repository.get_company(ticker_or_name, normalized)
            if cached:
                return cached
        if normalized == "CN":
            return self._remember_company(_normalize_company(self.ashare_source.resolve_company(ticker_or_name)))
        return self._remember_company(_normalize_company(self.sec_client.resolve_company(ticker_or_name)))

    def top_companies(self, market: str = "ALL") -> list[dict]:
        results = []
        normalized = _market(market)
        if normalized in {"ALL", "US"}:
            results.extend(_local_top_us())
        if normalized in {"ALL", "CN"}:
            results.extend(self.ashare_source.top_companies(limit=80))
        return [self._remember_company(_normalize_company(item)) for item in results]

    def list_report_options(self, company: dict, force: bool = False) -> dict:
        # A-share report selection must not depend on PDF metric extraction. A
        # scanned or unusual PDF can be unavailable for analysis while still
        # remaining a valid, user-selectable disclosure document.
        if company["market"] == "CN":
            reports = self.list_disclosure_reports(company, force=force)
            annual = [item["period"] for item in reports if item.get("report_type") == "annual"]
            quarterly = [item["period"] for item in reports if item.get("report_type") == "quarterly"]
            return {"annual": annual, "quarterly": quarterly, "reports": reports}
        dataset = self.get_financial_dataset(company, period_type="annual", force=force)
        records = dataset.get("records", {})
        annual = sorted([period for period in records if period.endswith("-FY")], reverse=True)[:12]
        quarterly = sorted([period for period in records if not period.endswith("-FY")], reverse=True)[:24]
        return {"annual": annual, "quarterly": quarterly, "reports": self.list_financial_documents(company, annual, quarterly)}

    def list_disclosure_reports(self, company: dict, force: bool = False) -> list[dict]:
        existing = [] if force else self.repository.list_documents(company["id"], {"annual", "quarterly"})
        if existing:
            return existing
        reports = self.ashare_source.list_reports(company)
        expiry = _expiry(DOCUMENT_INDEX_TTL)
        for report in reports:
            report.update({"market": "CN", "source_platform": "CNINFO", "index_expires_at": expiry})
            self.repository.upsert_document(report, expires_at=expiry)
            self._sync_canonical_document(report)
        return self.repository.list_documents(company["id"], {"annual", "quarterly"})

    def get_financial_dataset(
        self,
        company: dict,
        periods: Optional[list[str]] = None,
        period_type: str = "annual",
        force: bool = False,
    ) -> dict:
        key = company["id"]
        cached = None if force else self.repository.get_snapshot("financial_dataset", key, allow_stale=True)
        if cached:
            dataset = cached["payload"]
            available = set(dataset.get("records", {}))
            requested = set(periods or [])
            if not requested or requested.issubset(available):
                self._persist_financial_facts(company, dataset)
                return self._validated_dataset(company, dataset)
        if company["market"] == "CN":
            fresh = self.ashare_source.fetch_financial_dataset(company, periods=periods, period_type=period_type)
        else:
            fresh = self.sec_client.fetch_financial_dataset(company["cik"])
        if cached:
            fresh = _merge_dataset(cached["payload"], fresh)
        self.repository.save_snapshot("financial_dataset", key, fresh, company_id=key, source_version="financial_parser_v1")
        self._store_financial_documents(company, fresh)
        self._persist_financial_facts(company, fresh)
        return self._validated_dataset(company, fresh)

    def list_profile_documents(self, company: dict, year: Optional[int] = None, force: bool = False) -> list[dict]:
        existing = [] if force else self.repository.list_documents(company["id"], {"annual", "prospectus", "quarterly"})
        fresh_enough = existing and all(not _expired(item.get("index_expires_at")) for item in existing[:1])
        if not fresh_enough:
            documents = self._fetch_profile_document_index(company)
            expiry = _expiry(DOCUMENT_INDEX_TTL)
            for document in documents:
                document["index_expires_at"] = expiry
                self.repository.upsert_document(document, expires_at=expiry)
                self._sync_canonical_document(document)
            existing = self.repository.list_documents(company["id"], {"annual", "prospectus", "quarterly"})
        annual = [item for item in existing if item.get("report_type") == "annual"]
        if year:
            annual = [item for item in annual if str(item.get("period", ""))[:4].isdigit() and int(item["period"][:4]) <= year]
        prospectuses = [item for item in existing if item.get("report_type") == "prospectus"]
        return annual[:3] + prospectuses[:1]

    def get_document_text(self, document: dict, force: bool = False) -> str:
        key = document["id"]
        cached = None if force else self.repository.get_snapshot("document_text", key, allow_stale=True)
        if cached:
            document["content_hash"] = cached["content_hash"]
            return str(cached["payload"].get("text", ""))
        if document.get("market") == "US" or document.get("source_platform") == "SEC EDGAR":
            raw_content = self.sec_client.download_filing_html(document["source_url"])
            text = self.sec_client.extract_filing_text_from_html(raw_content)
            extension = ".html"
        else:
            raw_content = self.ashare_source.cninfo.download_pdf(document["source_url"])
            text = self.ashare_source.cninfo.extract_pdf_text_from_bytes(raw_content)
            extension = ".pdf"
        content_hash = hashlib.sha256(raw_content).hexdigest()
        asset_path = self._write_asset("documents", key, raw_content, extension)
        payload = {"text": text, "asset_path": str(asset_path.relative_to(self.storage_dir)), "raw_sha256": content_hash}
        self.repository.save_snapshot("document_text", key, payload, company_id=document["company_id"], source_version="text_extractor_v1")
        document["content_hash"] = content_hash
        self.repository.upsert_document(document)
        self._sync_canonical_document(document)
        return text

    def get_parsed_document(self, document: dict, parse_fn, parser_version: str, force: bool = False) -> dict:
        """Persist parser output without making the data platform depend on a parser implementation."""
        key = document["id"]
        cached = None if force else self.repository.get_snapshot("parsed_document", key, allow_stale=True)
        if cached and cached.get("source_version") == parser_version:
            return cached["payload"]
        text = self.get_document_text(document, force=force)
        parsed = parse_fn(text)
        self.repository.save_snapshot("parsed_document", key, parsed, company_id=document["company_id"], source_version=parser_version)
        return parsed

    def materialize_document(self, document: dict, force: bool = False) -> dict:
        """Persist canonical pages and evidence blocks for one official document."""
        text = self.get_document_text(document, force=force)
        cached = None if force else self.repository.get_snapshot("canonical_materialization", document["id"], allow_stale=True)
        if cached and cached.get("source_version") == self.document_processor.version:
            return cached["payload"]
        snapshot = self.repository.get_snapshot("document_text", document["id"], allow_stale=True) or {}
        relative_path = snapshot.get("payload", {}).get("asset_path")
        asset_path = self.storage_dir / relative_path if relative_path else None
        self._sync_canonical_document(document)
        processed = self.document_processor.process(document, asset_path, text)
        self.knowledge.replace_pages_and_blocks(document, processed["pages"], processed["blocks"])
        summary = {"document_id": document["id"], "page_count": len(processed["pages"]), "block_count": len(processed["blocks"]), "processor_version": processed["processor_version"]}
        self.repository.save_snapshot("canonical_materialization", document["id"], summary, company_id=document["company_id"], source_version=self.document_processor.version)
        return summary

    def get_encyclopedia(self, company: dict, force: bool = False) -> Optional[dict]:
        key = company["id"]
        cached = None if force else self.repository.get_snapshot("encyclopedia", key, allow_stale=False)
        if cached:
            context = cached["payload"].get("context")
            if context:
                self._materialize_encyclopedia(company, context)
            return context
        context = self.encyclopedia_client.fetch_company_context(company)
        payload = {"context": context}
        self.repository.save_snapshot("encyclopedia", key, payload, company_id=key, source_version="encyclopedia_v1", expires_at=_expiry(ENCYCLOPEDIA_TTL))
        if context:
            self._materialize_encyclopedia(company, context)
        return context

    def profile_cache_key(self, company: dict, documents: list[dict], encyclopedia: Optional[dict], agent_version: str) -> str:
        source_versions = []
        for document in documents:
            snapshot = self.repository.get_snapshot("document_text", document["id"], allow_stale=True)
            source_versions.append({"id": document["id"], "hash": (snapshot or {}).get("content_hash") or document.get("content_hash")})
        payload = {"company": company["id"], "documents": source_versions, "encyclopedia": json_hash(encyclopedia or {}), "agent": agent_version}
        return json_hash(payload)

    def get_profile_cache(self, cache_key: str) -> Optional[dict]:
        cached = self.repository.get_snapshot("company_profile", cache_key, allow_stale=False)
        return cached["payload"] if cached else None

    def save_profile_cache(self, company: dict, cache_key: str, payload: dict, agent_version: str) -> None:
        self.repository.save_snapshot("company_profile", cache_key, payload, company_id=company["id"], source_version=agent_version, expires_at=_expiry(PROFILE_TTL))

    def request_refresh(self, resource_type: str, company: dict, payload: Optional[dict] = None) -> dict:
        job_id = "refresh_%s" % uuid.uuid4().hex[:16]
        job = {"job_id": job_id, "resource_type": resource_type, "company_id": company["id"], "payload": payload or {}, "status": "PENDING", "progress": 0, "error_message": None, "created_at": utc_now(), "updated_at": utc_now()}
        self.repository.create_job(job)
        Thread(target=self._run_refresh_job, args=(job_id, company), daemon=True).start()
        return job

    def get_refresh_job(self, job_id: str) -> Optional[dict]:
        return self.repository.get_job(job_id)

    def resource_status(self, company: dict) -> dict:
        resources = {}
        for resource_type, key in {
            "financial_dataset": company["id"],
            "encyclopedia": company["id"],
        }.items():
            snapshot = self.repository.get_snapshot(resource_type, key, allow_stale=True)
            resources[resource_type] = {
                "status": "missing" if not snapshot else ("stale" if snapshot["is_stale"] else "ready"),
                "updated_at": snapshot.get("updated_at") if snapshot else None,
                "expires_at": snapshot.get("expires_at") if snapshot else None,
                "source_version": snapshot.get("source_version") if snapshot else None,
            }
        documents = self.repository.list_documents(company["id"])
        resources["documents"] = {"status": "ready" if documents else "missing", "count": len(documents)}
        return {"company": company, "resources": resources}

    def request_prewarm(self, market: str = "ALL", resources: Optional[list[str]] = None, limit: int = 20) -> list[dict]:
        allowed = {"financial_dataset", "documents", "encyclopedia"}
        requested = [item for item in (resources or ["financial_dataset", "documents"]) if item in allowed]
        jobs = []
        for company in self.top_companies(market)[: max(1, min(limit, 100))]:
            for resource in requested:
                jobs.append(self.request_refresh(resource, company, {"trigger": "prewarm"}))
        return jobs

    def _run_refresh_job(self, job_id: str, company: dict) -> None:
        job = self.repository.update_job(job_id, status="RUNNING", progress=15)
        try:
            resource_type = job["resource_type"] if job else ""
            if resource_type == "financial_dataset":
                self.get_financial_dataset(company, force=True)
            elif resource_type == "documents":
                documents = self.list_profile_documents(company, force=True)
                for index, document in enumerate(documents, start=1):
                    self.materialize_document(document, force=True)
                    self.repository.update_job(job_id, status="RUNNING", progress=min(90, 15 + index * 70 // max(1, len(documents))))
            elif resource_type == "encyclopedia":
                self.get_encyclopedia(company, force=True)
            elif resource_type == "company_profile":
                self.repository.delete_snapshots("company_profile", company["id"])
            else:
                raise ValueError("不支持的数据刷新类型：%s" % resource_type)
            self.repository.update_job(job_id, status="COMPLETED", progress=100, error_message=None)
        except Exception as exc:
            self.repository.update_job(job_id, status="FAILED", progress=100, error_message=str(exc)[:500])

    def _fetch_profile_document_index(self, company: dict) -> list[dict]:
        if company["market"] == "CN":
            documents = [item for item in self.ashare_source.list_reports(company) if item["report_type"] == "annual"]
            try:
                documents.extend(self.ashare_source.cninfo.list_prospectuses(company)[:1])
            except Exception:
                pass
            for item in documents:
                item.update({"market": "CN", "source_platform": "CNINFO"})
            return documents
        items = []
        for source in self.sec_client.list_filing_documents(company["cik"]):
            form = source.get("form") or "SEC filing"
            report_type = "annual" if form in {"10-K", "20-F"} else ("prospectus" if form in {"S-1", "F-1"} else "quarterly")
            if report_type not in {"annual", "prospectus"} or not source.get("url"):
                continue
            year = str(source.get("report_date") or source.get("filing_date") or "")[:4]
            period = "%s-FY" % year if report_type == "annual" else "%s-PROSPECTUS" % year
            items.append({"id": "SEC-%s-%s-%s" % (company["ticker"], period, source["accession"]), "company_id": company["id"], "report_type": report_type, "period": period, "publish_date": source.get("filing_date"), "source_url": source["url"], "title": "%s %s %s" % (company["name"], period, form), "form": form, "source_platform": "SEC EDGAR", "market": "US"})
        return sorted(items, key=lambda item: item["period"], reverse=True)

    def list_financial_documents(self, company: dict, annual: list[str], quarterly: list[str]) -> list[dict]:
        existing = {item["period"]: item for item in self.repository.list_documents(company["id"])}
        documents = []
        for period in annual + quarterly:
            item = existing.get(period)
            if item:
                documents.append(item)
            else:
                documents.append({"id": "%s-%s" % (company["id"], period), "company_id": company["id"], "report_type": "annual" if period.endswith("-FY") else "quarterly", "period": period, "publish_date": None, "source_url": None, "parse_status": "structured"})
        return documents

    def _store_financial_documents(self, company: dict, dataset: dict) -> None:
        for period, record in dataset.get("records", {}).items():
            source = _filing_for_record(record, dataset.get("filings", {}))
            document = {"id": "%s-%s" % (company["id"], period), "company_id": company["id"], "report_type": "annual" if period.endswith("-FY") else "quarterly", "period": period, "publish_date": source.get("filing_date") or record.get("filed"), "source_url": source.get("url"), "parse_status": "structured", "source_platform": "SEC EDGAR" if company["market"] == "US" else "CNINFO", "market": company["market"], "form": source.get("form") or record.get("form")}
            self.repository.upsert_document(document)
            self._sync_canonical_document(document)

    def _persist_financial_facts(self, company: dict, dataset: dict) -> None:
        for period, record in dataset.get("records", {}).items():
            document_id = "%s-%s" % (company["id"], period)
            status, reasons = assess_record(record, company["market"])
            facts = []
            for metric_key, metric in record.get("metrics", {}).items():
                value = metric.get("value")
                if not isinstance(value, (int, float)):
                    continue
                facts.append({
                    "fact_id": fact_id(company["id"], document_id, metric_key),
                    "metric_key": metric_key,
                    "value": value,
                    "unit": metric.get("unit"),
                    "source_block_id": None,
                    "page_number": None,
                    "table_name": None,
                    "row_label": metric.get("label"),
                    "column_label": period,
                    "quality_status": status,
                    "parser_version": "financial_quality_v1",
                    "validation_reasons": reasons,
                    "source_accn": metric.get("accn") or metric.get("source_accn"),
                })
            self.knowledge.replace_financial_facts(company["id"], document_id, period, facts)

    def _validated_dataset(self, company: dict, dataset: dict) -> dict:
        if company["market"] == "US":
            return dataset
        valid_records = {}
        rejected = []
        for period, record in dataset.get("records", {}).items():
            status, reasons = assess_record(record, company["market"])
            if status == "validated":
                valid_records[period] = record
            else:
                rejected.append({"period": period, "reasons": reasons})
        if not valid_records and dataset.get("records"):
            detail = "；".join("%s：%s" % (item["period"], "、".join(item["reasons"])) for item in rejected[:3])
            raise ValueError("A 股 PDF 数据质量校验未通过，已阻止生成不可靠分析。%s" % detail)
        return {"records": valid_records, "filings": dataset.get("filings", {}), "rejected_periods": rejected}

    def _remember_company(self, company: dict) -> dict:
        return self.repository.upsert_company(company)

    def _sync_canonical_document(self, document: dict) -> None:
        self.knowledge.upsert_document(document, source_authority(document.get("report_type", "unknown")))

    def _materialize_encyclopedia(self, company: dict, context: dict) -> None:
        source_type = context.get("source_type") or "encyclopedia"
        document = {
            "id": "ENC-%s-%s" % (company["id"], source_type),
            "company_id": company["id"],
            "report_type": source_type,
            "period": "reference",
            "source_url": context.get("url"),
            "title": context.get("title") or company["name"],
            "source_platform": source_type,
            "market": company.get("market"),
            "allowed_usage": context.get("allowed_usage"),
        }
        text = context.get("summary") or ""
        asset_path = self._write_asset("encyclopedia", document["id"], text.encode("utf-8"), ".txt")
        document["asset_path"] = str(asset_path.relative_to(self.storage_dir))
        document["content_hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self._sync_canonical_document(document)
        processed = self.document_processor.process(document, asset_path, text)
        self.knowledge.replace_pages_and_blocks(document, processed["pages"], processed["blocks"])

    def knowledge_documents(self, company: dict, source_type: str = "") -> list[dict]:
        return self.knowledge.list_documents(company["id"], source_type)

    def knowledge_blocks(self, company: dict, query: str = "", limit: int = 20) -> list[dict]:
        direct = self.knowledge.list_blocks(company["id"], query, limit) if query else []
        if direct or not query:
            return direct or self.knowledge.list_blocks(company["id"], "", limit)
        merged = []
        seen = set()
        for term in _knowledge_terms(query):
            for item in self.knowledge.list_blocks(company["id"], term, limit):
                if item["block_id"] not in seen:
                    merged.append(item)
                    seen.add(item["block_id"])
                if len(merged) >= limit:
                    return merged
        return merged

    def canonical_document_blocks(self, document: dict, force: bool = False) -> list[dict]:
        self.materialize_document(document, force=force)
        return self.knowledge.list_document_blocks(document["id"])

    def knowledge_financial_facts(self, company: dict, periods: Optional[list[str]] = None) -> list[dict]:
        return self.knowledge.list_financial_facts(company["id"], periods, validated_only=False)

    def persist_company_facts(self, company: dict, profile: dict, evidences: dict, extractor_version: str) -> None:
        def block_ids(refs):
            return [evidences[ref]["location"]["text_block_id"] for ref in refs if ref in evidences and evidences[ref].get("location", {}).get("text_block_id")]

        candidates = [
            ("basic_info", profile.get("company_profile", {}).get("main_business"), profile.get("company_profile", {}), profile.get("company_profile", {}).get("evidence_refs", [])),
            ("business_model", profile.get("business_model", {}).get("business_summary"), profile.get("business_model", {}), profile.get("business_model", {}).get("evidence_refs", [])),
            ("ownership", profile.get("ownership", {}).get("plain_explanation"), profile.get("ownership", {}), profile.get("ownership", {}).get("evidence_refs", [])),
            ("industry_chain", profile.get("industry_chain", {}).get("company_position"), profile.get("industry_chain", {}), profile.get("industry_chain", {}).get("evidence_refs", [])),
            ("capital_actions", profile.get("capital_actions", {}).get("summary"), profile.get("capital_actions", {}), profile.get("capital_actions", {}).get("evidence_refs", [])),
        ]
        facts = []
        for category, claim, value, refs in candidates:
            if not claim or str(claim).strip() in {"未披露", "无法确认"}:
                continue
            ids = block_ids(refs)
            fingerprint = hashlib.sha1((company["id"] + category + str(claim)).encode("utf-8")).hexdigest()[:16]
            facts.append({"fact_id": "cf_%s" % fingerprint, "category": category, "claim": str(claim), "value": value, "source_block_ids": ids, "source_authority": "official_filing" if ids else "model_derived", "quality_status": "validated" if ids else "needs_review", "extractor_version": extractor_version})
        self.knowledge.upsert_company_facts(company["id"], facts)

    def _write_asset(self, category: str, identity: str, content: bytes, extension: str) -> Path:
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        directory = self.assets_dir / category
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (digest + extension)
        path.write_bytes(content)
        return path


def _merge_dataset(old: dict, fresh: dict) -> dict:
    return {"records": {**old.get("records", {}), **fresh.get("records", {})}, "filings": {**old.get("filings", {}), **fresh.get("filings", {})}}


def _filing_for_record(record: dict, filings: dict) -> dict:
    for accession in record.get("sources", []):
        if accession in filings:
            return filings[accession]
    return {}


def _expiry(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _expired(value: Optional[str]) -> bool:
    return bool(value and value <= utc_now())


def _market(value: str) -> str:
    upper = (value or "US").upper()
    return "CN" if upper in {"CN", "A"} else upper


def _looks_cn_ticker(value: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", (value or "").strip()))


def _knowledge_terms(query: str) -> list[str]:
    normalized = (query or "").lower()
    terms = []
    synonyms = {
        "主营业务": ["主营业务", "主要业务", "业务情况", "业务模式", "产品"],
        "收入": ["营业收入", "收入", "营收"],
        "利润": ["净利润", "利润总额", "利润"],
        "风险": ["风险因素", "风险", "诉讼", "处罚"],
        "股东": ["控股股东", "实际控制人", "股东"],
    }
    for key, values in synonyms.items():
        if key in normalized or any(value in normalized for value in values):
            terms.extend(values)
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+", normalized))
    return list(dict.fromkeys(term for term in terms if len(term) >= 2))


def _normalize_company(item: dict) -> dict:
    market = item.get("market", "US")
    ticker = item.get("ticker", "")
    return {"id": item.get("id") or f"{market}-{ticker}", "cik": item.get("cik"), "ticker": ticker, "name": item.get("name", ""), "short_name": item.get("short_name"), "market": market, "exchange": item.get("exchange"), "industry": item.get("industry") or _infer_industry(item.get("name", ""), ticker), "source": item.get("source"), "org_id": item.get("org_id")}


def _infer_industry(name: str, ticker: str) -> str:
    upper = ticker.upper()
    if upper in {"AAPL", "MSFT", "GOOGL", "GOOG", "META", "NVDA"}:
        return "科技"
    if upper in {"TSLA", "F", "GM"}:
        return "汽车"
    if upper in {"JPM", "BAC", "GS", "MS"}:
        return "金融"
    if "apple" in name.lower() or "microsoft" in name.lower():
        return "科技"
    return "待识别行业"


def _local_top_us() -> list[dict]:
    return [
        {"id": "US-AAPL", "ticker": "AAPL", "name": "Apple Inc.", "market": "US", "industry": "科技"},
        {"id": "US-MSFT", "ticker": "MSFT", "name": "Microsoft", "market": "US", "industry": "科技"},
        {"id": "US-NVDA", "ticker": "NVDA", "name": "NVIDIA", "market": "US", "industry": "科技"},
        {"id": "US-GOOGL", "ticker": "GOOGL", "name": "Alphabet", "market": "US", "industry": "科技"},
        {"id": "US-META", "ticker": "META", "name": "Meta Platforms", "market": "US", "industry": "科技"},
        {"id": "US-BIDU", "ticker": "BIDU", "name": "Baidu, Inc.", "market": "US", "industry": "互联网"},
        {"id": "US-TSLA", "ticker": "TSLA", "name": "Tesla", "market": "US", "industry": "汽车"},
        {"id": "US-AMZN", "ticker": "AMZN", "name": "Amazon", "market": "US", "industry": "互联网零售"},
        {"id": "US-JPM", "ticker": "JPM", "name": "JPMorgan Chase", "market": "US", "industry": "金融"},
    ]
