from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.models.models import Answer, AuditLog, ChangeAlert, Conflict, User
from app.services.rag_service import can_access_source, mask_sensitive_text

router = APIRouter()


@router.get("/answers/{answer_id}/evidence")
def get_answer_evidence(answer_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    permitted_owner = answer is not None and answer.query.user_id == user.id
    permitted_manager = (
        answer is not None
        and user.role.name == "manager"
        and all(
            not (citation.document.source_id if citation.document else citation.source_id_snapshot)
            or can_access_source(db, user, citation.document.source_id if citation.document else citation.source_id_snapshot)
            for claim in answer.claims for citation in claim.citations
        )
    )
    if not answer or (user.role.name != "admin" and not permitted_owner and not permitted_manager):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer not found")
    claims = []
    for claim in answer.claims:
        citations = []
        restricted_citation = False
        for citation in claim.citations:
            source_id = citation.document.source_id if citation.document else citation.source_id_snapshot
            if source_id and not can_access_source(db, user, source_id):
                restricted_citation = True
                continue
            citations.append({
                "id": citation.id,
                "document_id": citation.document_id,
                "document_name": mask_sensitive_text(citation.document.title if citation.document else citation.document_title_snapshot or ""),
                "version": citation.document.version if citation.document else citation.document_version_snapshot,
                "page": citation.page_number,
                "source_url": mask_sensitive_text(citation.source_url) if citation.source_url else None,
                "quote": mask_sensitive_text(citation.quoted_text),
                "support_status": citation.support_status,
            })
        claims.append({
            "id": claim.id,
            "claim_text": "Claim hidden because source access has changed." if restricted_citation else mask_sensitive_text(claim.claim_text),
            "support_status": "Not Enough Evidence" if restricted_citation else claim.support_status,
            "citations": citations,
        })
    return {"answer_id": answer.id, "verification_status": answer.verification_status, "evidence_coverage": answer.evidence_coverage, "claims": claims}


@router.get("/conflicts")
def list_conflicts(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    conflicts = db.query(Conflict).all()
    if user.role.name == "admin":
        visible = conflicts
    elif user.role.name == "manager":
        visible = [
            item for item in conflicts
            if item.query.user_id == user.id or any(
                evidence.get("source_id") and can_access_source(db, user, evidence["source_id"])
                for evidence in (item.evidence or [])
            )
        ]
    else:
        visible = [item for item in conflicts if item.query.user_id == user.id]
    return [{
        "id": item.id,
        "subject": mask_sensitive_text(item.subject),
        "status": item.status,
        "summary": item.summary,
        "evidence": [
            {**evidence,
             "document_name": mask_sensitive_text(evidence.get("document_name", "")),
             "quote": mask_sensitive_text(evidence.get("quote", ""))}
            for evidence in (item.evidence or [])
            if not evidence.get("source_id") or can_access_source(db, user, evidence["source_id"])
        ],
        "resolution": mask_sensitive_text(item.resolution) if item.resolution else None,
    } for item in visible]


@router.post("/conflicts/{conflict_id}/review")
def review_conflict(conflict_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager"))) -> dict:
    conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
    can_review = (
        conflict is not None
        and (
            user.role.name == "admin"
            or conflict.query.user_id == user.id
            or (
                user.role.name == "manager"
                and any(
                    evidence.get("source_id") and can_access_source(db, user, evidence["source_id"])
                    for evidence in (conflict.evidence or [])
                )
            )
        )
    )
    if not conflict or not can_review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")
    resolution = payload.get("resolution")
    if not isinstance(resolution, str) or not resolution.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A non-empty resolution explanation is required.")
    conflict.status = "reviewed"
    conflict.resolution = resolution.strip()
    conflict.reviewed_by = user.id
    db.add(AuditLog(user_id=user.id, action="conflict_resolved", resource_type="conflict", resource_id=str(conflict.id), details=conflict.resolution))
    db.commit()
    return {"message": "Conflict reviewed", "status": conflict.status}


@router.get("/change-alerts")
def list_change_alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    alerts = db.query(ChangeAlert).order_by(ChangeAlert.created_at.desc()).all()
    return [{
        "id": alert.id,
        "source_id": alert.source_id,
        "source": mask_sensitive_text(alert.source.name) if alert.source else "Removed source",
        "document_id": alert.document_id,
        "document": mask_sensitive_text(alert.document.title if alert.document else alert.document_title),
        "event_type": alert.event_type,
        "summary": mask_sensitive_text(alert.summary),
        "created_at": alert.created_at.isoformat(),
        "reviewed": alert.reviewed_at is not None,
    } for alert in alerts if alert.source and can_access_source(db, user, alert.source_id)]


@router.post("/change-alerts/{alert_id}/review")
def review_change_alert(alert_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "manager"))) -> dict:
    alert = db.query(ChangeAlert).filter(ChangeAlert.id == alert_id).first()
    if not alert or not can_access_source(db, user, alert.source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Change alert not found")
    alert.reviewed_at = datetime.utcnow()
    db.add(AuditLog(user_id=user.id, action="change_alert_reviewed", resource_type="change_alert", resource_id=str(alert.id), details=alert.event_type))
    db.commit()
    return {"id": alert.id, "reviewed": True}
