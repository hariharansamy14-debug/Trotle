from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models.models import Answer, AnswerClaim, AuditLog, Conflict, DataSource, Document, Query, SyncJob, User
from app.services.rag_service import allowed_source_ids_for_user, can_access_source, mask_sensitive_text

router = APIRouter()


def _query_for_user(db: Session, user: User):
    query = db.query(Query)
    if user.role.name != "admin":
        query = query.filter(Query.user_id == user.id)
    return query


@router.get("/reports/summary")
def report_summary(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager"))) -> dict:
    source_ids = allowed_source_ids_for_user(db, user)
    return {
        "connected_sources": db.query(DataSource).filter(DataSource.id.in_(source_ids), DataSource.connection_status == "Ready").count(),
        "ready_documents": db.query(Document).filter(Document.source_id.in_(source_ids), Document.status == "Ready").count(),
        "failed_processing_jobs": db.query(SyncJob).filter(SyncJob.source_id.in_(source_ids), SyncJob.status == "failed").count(),
        "questions_asked": _query_for_user(db, user).count(),
        "evidence_status": {
            "supported": db.query(Answer).join(Answer.query).filter(Answer.verification_status == "Supported", Answer.query.has(user_id=user.id) if user.role.name != "admin" else True).count(),
            "conflicting": db.query(Conflict).join(Conflict.query).filter(Conflict.status == "open", Conflict.query.has(user_id=user.id) if user.role.name != "admin" else True).count(),
        },
    }


@router.get("/reports/sources")
def report_sources(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager"))) -> list[dict]:
    source_ids = allowed_source_ids_for_user(db, user)
    sources = db.query(DataSource).filter(DataSource.id.in_(source_ids)).all()
    return [{
        "id": source.id,
        "name": mask_sensitive_text(source.name),
        "source_type": source.source_type,
        "connection_status": source.connection_status,
        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
    } for source in sources]


@router.get("/reports/evidence")
def report_evidence(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    claims = db.query(AnswerClaim).join(Answer).join(Answer.query)
    if user.role.name != "admin":
        claims = claims.filter(Answer.query.has(user_id=user.id))
    statuses = ("Supported", "Partly Supported", "Conflicting Information", "Not Enough Evidence", "Unsupported")
    counts = {label: claims.filter(AnswerClaim.support_status == label).count() for label in statuses}
    counts["total"] = sum(counts.values())
    counts["coverage_percent"] = round(
        100 * (counts["Supported"] + counts["Partly Supported"]) / counts["total"], 1,
    ) if counts["total"] else 0.0
    return {"claims": counts, "coverage_disclaimer": "Evidence coverage is a measure of source matching, not a guarantee of correctness."}


@router.get("/reports/evidence/explorer")
def evidence_explorer(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    queries = _query_for_user(db, user).order_by(Query.created_at.desc()).limit(100).all()
    reports = []
    for row in queries:
        answer = row.answer
        if not answer:
            continue
        claim_rows = []
        for claim in answer.claims:
            evidence_items = []
            for citation in claim.citations:
                source_id = citation.document.source_id if citation.document else citation.source_id_snapshot
                if source_id is None or not can_access_source(db, user, source_id):
                    continue
                document = citation.document
                source = document.source if document else db.query(DataSource).filter(DataSource.id == source_id).first()
                evidence_items.append({
                    "id": citation.id,
                    "document_id": document.id if document else None,
                    "source_id": source_id,
                    "document_name": mask_sensitive_text(
                        document.title if document else citation.document_title_snapshot or "Historical document"
                    ),
                    "source_name": mask_sensitive_text(source.name) if source else "Not available",
                    "source_type": source.source_type if source else None,
                    "quote": mask_sensitive_text(citation.quoted_text),
                    "page": citation.page_number,
                    "section": mask_sensitive_text(citation.chunk.section_title) if citation.chunk and citation.chunk.section_title else None,
                    "version": document.version if document else citation.document_version_snapshot,
                    "created_at": document.created_at.isoformat() if document else None,
                    "updated_at": document.updated_at.isoformat() if document else None,
                    "source_url": mask_sensitive_text(citation.source_url) if citation.source_url else None,
                    "status": citation.support_status,
                })
            restricted_evidence = len(evidence_items) < len(claim.citations)
            claim_rows.append({
                "id": claim.id,
                "text": mask_sensitive_text(claim.claim_text),
                "status": "Not verified" if restricted_evidence and not evidence_items else claim.support_status,
                "evidence": evidence_items,
                "limitation": "Some saved evidence is unavailable to this account." if restricted_evidence else None,
            })

        conflict_rows = []
        for conflict in row.conflicts:
            visible_evidence = []
            for item in conflict.evidence or []:
                source_id = item.get("source_id")
                if source_id is None or not can_access_source(db, user, source_id):
                    continue
                visible_evidence.append({
                    **item,
                    "document_name": mask_sensitive_text(item.get("document_name", "Not available")),
                    "quote": mask_sensitive_text(item.get("quote", "")),
                    "source": mask_sensitive_text(item.get("source", "Not available")),
                    "source_type": item.get("source_type"),
                    "version": item.get("version"),
                    "page": item.get("page"),
                    "document_created_at": item.get("document_created_at"),
                    "document_updated_at": item.get("document_updated_at"),
                })
            if visible_evidence:
                conflict_rows.append({
                    "id": conflict.id,
                    "subject": mask_sensitive_text(conflict.subject),
                    "status": conflict.status,
                    "summary": mask_sensitive_text(conflict.summary),
                    "resolution": mask_sensitive_text(conflict.resolution) if conflict.resolution else None,
                    "created_at": conflict.created_at.isoformat(),
                    "evidence": visible_evidence,
                })

        retrieval_source_ids = set()
        for run in row.retrieval_runs:
            for result in run.results:
                source_id = result.chunk.document.source_id
                if can_access_source(db, user, source_id):
                    retrieval_source_ids.add(source_id)
        source_count = len(retrieval_source_ids) or len({
            evidence["source_id"]
            for claim in claim_rows
            for evidence in claim["evidence"]
        })
        coverage_statuses = ("Supported", "Partly Supported", "Conflicting Information", "Not Enough Evidence", "Unsupported", "Not verified")
        coverage = {label: sum(claim["status"] == label for claim in claim_rows) for label in coverage_statuses}
        coverage["total"] = len(claim_rows)
        coverage["coverage_percent"] = round(
            100 * (coverage["Supported"] + coverage["Partly Supported"]) / len(claim_rows),
            1,
        ) if claim_rows else 0.0
        reports.append({
            "query_id": row.id,
            "question": mask_sensitive_text(row.question),
            "answer_id": answer.id,
            "answer": mask_sensitive_text(answer.answer_text),
            "verification_status": answer.verification_status,
            "coverage": coverage,
            "created_at": answer.created_at.isoformat(),
            "sources_examined": source_count,
            "claims": claim_rows,
            "conflicts": conflict_rows,
        })
    return {
        "reports": reports,
        "coverage_disclaimer": "Evidence coverage measures source matching, not answer accuracy or a guarantee of correctness.",
    }


@router.get("/reports/export")
def export_report(
    format: str = QueryParam(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "manager")),
):
    query = db.query(Query)
    if user.role.name != "admin":
        query = query.filter(Query.user_id == user.id)
    answers = []
    for row in query.order_by(Query.created_at.desc()).all():
        answer = row.answer
        if not answer:
            continue
        restricted_evidence = user.role.name != "admin" and any(
            (citation.document.source_id if citation.document else citation.source_id_snapshot)
            and not can_access_source(
                db,
                user,
                citation.document.source_id if citation.document else citation.source_id_snapshot,
            )
            for claim in answer.claims for citation in claim.citations
            if (citation.document.source_id if citation.document else citation.source_id_snapshot) is not None
        )
        if restricted_evidence:
            continue
        claims = [{
            "claim": claim.claim_text,
            "status": claim.support_status,
            "citations": [{
                "source_id": citation.document.source_id if citation.document else citation.source_id_snapshot,
                "source": mask_sensitive_text(citation.document.source.name) if citation.document and citation.document.source else None,
                "source_type": citation.document.source.source_type if citation.document and citation.document.source else None,
                "document": mask_sensitive_text(citation.document.title if citation.document else citation.document_title_snapshot or ""),
                "version": citation.document.version if citation.document else citation.document_version_snapshot,
                "page": citation.page_number,
                "section": mask_sensitive_text(citation.chunk.section_title) if citation.chunk and citation.chunk.section_title else None,
                "created_at": citation.document.created_at.isoformat() if citation.document else None,
                "updated_at": citation.document.updated_at.isoformat() if citation.document else None,
                "quote": mask_sensitive_text(citation.quoted_text),
                "source_url": mask_sensitive_text(citation.source_url) if citation.source_url else None,
                "status": citation.support_status,
            } for citation in claim.citations if (
                user.role.name == "admin"
                or (
                    (citation.document.source_id if citation.document else citation.source_id_snapshot) is not None
                    and can_access_source(db, user, citation.document.source_id if citation.document else citation.source_id_snapshot)
                )
            )],
        } for claim in answer.claims]
        answers.append({
            "query_id": row.id,
            "question": mask_sensitive_text(row.question),
            "answer_id": answer.id,
            "answer": mask_sensitive_text(answer.answer_text),
            "created_at": answer.created_at.isoformat(),
            "verification_status": answer.verification_status,
            "evidence_coverage": answer.evidence_coverage or {},
            "claims": claims,
            "conflicts": [{
                "subject": mask_sensitive_text(item.subject),
                "status": item.status,
                "summary": item.summary,
                "created_at": item.created_at.isoformat(),
                "evidence": [
                    {**evidence,
                     "document_name": mask_sensitive_text(evidence.get("document_name", "")),
                     "quote": mask_sensitive_text(evidence.get("quote", ""))}
                    for evidence in (item.evidence or [])
                    if user.role.name == "admin"
                    or (evidence.get("source_id") is not None and can_access_source(db, user, evidence["source_id"]))
                ],
                "resolution": mask_sensitive_text(item.resolution) if item.resolution else None,
            } for item in row.conflicts],
        })
    report_generated_at = datetime.utcnow().isoformat()
    export = {
        "format": format,
        "generated_at": report_generated_at,
        "coverage_disclaimer": "Evidence coverage is a measure of source matching, not a guarantee of correctness.",
        "answers": answers,
    }
    db.add(AuditLog(user_id=user.id, action="evidence_report_exported", resource_type="report", resource_id="evidence", details=f"format={format}; answers={len(answers)}"))
    db.commit()
    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["report_generated_at", "query_id", "question", "answer_id", "answer", "created_at", "verification_status", "evidence_coverage", "claims", "conflicts"])
        writer.writeheader()
        for item in answers:
            row = {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                for key, value in item.items()
            }
            row["report_generated_at"] = report_generated_at
            writer.writerow(row)
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="evidence-report.csv"'},
        )
    return export
