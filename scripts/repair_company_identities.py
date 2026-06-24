#!/usr/bin/env python3
"""Repair incomplete cached company identities from their authoritative market source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.data_platform.company_identity import CompanyIdentityError
from backend.data_platform.service import DataService
from backend.repositories.sqlite_store import SQLiteStore


def parse_args():
    parser = argparse.ArgumentParser(description="Repair incomplete cached company identities.")
    parser.add_argument("--market", default="US", choices=["US"], help="Market to inspect; the current repair flow targets SEC-listed companies.")
    parser.add_argument("--ticker", default="", help="Restrict repair to one ticker.")
    parser.add_argument("--storage-dir", default=str(ROOT_DIR / "backend" / "storage"))
    parser.add_argument("--dry-run", action="store_true", help="Validate source matches without writing companies or audit records.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    storage_dir = Path(args.storage_dir)
    service = DataService(storage_dir, SQLiteStore(storage_dir))
    candidates = service.repository.list_incomplete_companies(args.market, args.ticker)
    summary = {"market": args.market, "candidates": len(candidates), "succeeded": 0, "failed": 0, "dry_run": args.dry_run}
    for company in candidates:
        try:
            repaired = service.repair_company_identity(company, persist=not args.dry_run)
            summary["succeeded"] += 1
            print(json.dumps({"status": "SUCCEEDED", "ticker": company.get("ticker"), "cik": repaired.get("cik"), "dry_run": args.dry_run}, ensure_ascii=False))
        except CompanyIdentityError as exc:
            summary["failed"] += 1
            print(json.dumps({"status": "FAILED", "ticker": company.get("ticker"), "error": str(exc), "dry_run": args.dry_run}, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not summary["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
