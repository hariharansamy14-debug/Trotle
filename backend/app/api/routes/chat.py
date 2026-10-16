from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.models import Answer, AnswerClaim, AuditLog, ChangeAlert, Citation, Conflict, Conversation, Feedback, Query, RetrievalResult, RetrievalRun, User
from app.schemas.chat import ChatRequest, FeedbackRequest
from app.services.rag_service import (
    allowed_source_ids_for_user,
    citation_for_hit,
    detect_conflicts,
    evidence_coverage,
    explain_hit,
    generate_answer,
    search_chunks,
    verify_claims,
)

router = APIRouter()


@router.post("/chat")
def ask_question(payload: ChatRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    if not payload.question.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question cannot be empty")

    conversation = None
    if payload.conversation_id:
        conversation = db.query(Conversation).filter(Conversation.id == payload.conversation_id, Conversation.user_id == user.id).first()
    if not conversation:
        conversation = Conversation(user_id=user.id, title=payload.question[:80])
        db.add(conversation); db.commit(); db.refresh(conversation)

    query = Query(user_id=user.id, conversation_id=conversation.id, question=payload.question)
    db.add(query); db.commit(); db.refresh(query)
    conversation.updated_at = query.created_at
    db.commit()

    try:
        hits = search_chunks(db, payload.question, user, payload.source_ids)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    try:
        answer_text, claim_texts = generate_answer(payload.question, hits)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    evaluated = verify_claims(claim_texts, hits, payload.question)
    conflicts = detect_conflicts(payload.question, hits)
    change_events = []
    if "what changed this month" in payload.question.lower():
        now = datetime.utcnow()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        allowed_ids = allowed_source_ids_for_user(db, user)
        change_events = db.query(ChangeAlert).filter(
            ChangeAlert.source_id.in_(allowed_ids),
            ChangeAlert.created_at >= month_start,
        ).order_by(ChangeAlert.created_at.desc()).all()
        claim_texts = []
        evaluated = []
        conflicts = []
        if change_events:
            answer_text = "Recorded changes this month: " + " ".join(
                f"{event.created_at:%Y-%m-%d} — {event.summary}" for event in change_events
            ) + " These are ingestion change records, not a determination of policy authority."
        else:
            answer_text = f"No uploaded-file change events are recorded since {month_start:%Y-%m-%d}. External source synchronization is not configured."
    for claim in evaluated:
        if claim["hit"] and conflicts:
            claim_words = set(claim["claim"].lower().split())
            for conflict in conflicts:
                for evidence in conflict["evidence"]:
                    if evidence["document_id"] == claim["hit"]["document"].id:
                        claim["support_status"] = "Conflicting Information"
                        break
    coverage = evidence_coverage(evaluated)
    statuses = {claim["support_status"] for claim in evaluated}
    if conflicts:
        verification_status = "Conflicting Information"
    elif statuses == {"Supported"}:
        verification_status = "Supported"
    elif statuses == {"Unsupported"}:
        verification_status = "Unsupported"
    elif "Partly Supported" in statuses:
        verification_status = "Partly Supported"
    else:
        verification_status = "Not Enough Evidence"

    retrieval_run = RetrievalRun(query_id=query.id, search_method="bm25_sparse_vector_gemini", status="complete")
    db.add(retrieval_run); db.commit(); db.refresh(retrieval_run)

    for index, hit in enumerate(hits, start=1):
        db.add(RetrievalResult(
            retrieval_run_id=retrieval_run.id,
            chunk_id=hit["chunk"].id,
            keyword_score=hit["bm25_score"],
            vector_score=hit["vector_score"],
            combined_score=hit["score"],
            rank=index,
        ))

    answer = Answer(
        query_id=query.id,
        answer_text=answer_text,
        model_name=(
            settings.grok_model
            if settings.llm_provider.strip().lower() in {"grok", "xai"}
            else settings.gemini_model
            if settings.llm_provider.strip().lower() in {"gemini", "google"}
            else "local-grounded-model"
        ),
        verification_status=verification_status,
        evidence_coverage=coverage,
    )
    db.add(answer); db.commit(); db.refresh(answer)

    citations = []
    for claim in evaluated:
        answer_claim = AnswerClaim(answer_id=answer.id, claim_text=claim["claim"], support_status=claim["support_status"])
        db.add(answer_claim)
        db.flush()
        hit = claim["hit"]
        if hit:
            citation_data = citation_for_hit(hit, claim["support_status"])
            citations.append(citation_data)
            db.add(Citation(
                claim_id=answer_claim.id,
                document_id=hit["document"].id,
                chunk_id=hit["chunk"].id,
                quoted_text=citation_data["quote"],
                page_number=hit["chunk"].page_number,
                source_url=citation_data["source_url"],
                source_id_snapshot=hit["document"].source_id,
                document_title_snapshot=hit["document"].title,
                document_version_snapshot=hit["document"].version,
                support_status=claim["support_status"],
            ))
        claim.pop("hit")
    db.add(AuditLog(user_id=user.id, action="ask_question", resource_type="query", resource_id=str(query.id), details="Evidence retrieval and verification completed"))

    if conflicts:
        for conflict in conflicts:
            db.add(Conflict(
                query_id=query.id,
                subject=conflict["subject"],
                status="open",
                summary=conflict["summary"],
                evidence=conflict["evidence"],
            ))
    db.commit()

    return {
        "conversation_id": conversation.id,
        "answer_id": answer.id,
        "answer": {"text": answer.answer_text, "verification_status": answer.verification_status},
        "citations": citations,
        "claims": evaluated,
        "evidence_coverage": coverage,
        "conflicts": conflicts,
        "why_these_results": [explain_hit(hit) for hit in hits],
        "change_events": [{
            "id": event.id,
            "document": event.document_title,
            "event_type": event.event_type,
            "summary": event.summary,
            "created_at": event.created_at.isoformat(),
        } for event in change_events],
        "coverage_disclaimer": "Evidence coverage reflects retrieved claim support and is not a guarantee of correctness.",
    }


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    conversations = db.query(Conversation).filter(Conversation.user_id == user.id).order_by(Conversation.updated_at.desc()).all()
    return [{
        "id": conversation.id,
        "title": conversation.title,
        "updated_at": conversation.updated_at.isoformat(),
        "latest_query_id": max(conversation.queries, key=lambda query: query.created_at).id if conversation.queries else None,
        "query_ids": [query.id for query in conversation.queries],
    } for conversation in conversations]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    queries = db.query(Query).filter(Query.conversation_id == conversation_id).all()
    return {"id": conversation.id, "title": conversation.title, "queries": [{"id": query.id, "question": query.question, "created_at": query.created_at.isoformat()} for query in queries]}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.user_id == user.id).first()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    query_ids = [query_id for (query_id,) in db.query(Query.id).filter(Query.conversation_id == conversation_id).all()]
    answer_ids = [answer_id for (answer_id,) in db.query(Answer.id).filter(Answer.query_id.in_(query_ids)).all()] if query_ids else []
    claim_ids = [claim_id for (claim_id,) in db.query(AnswerClaim.id).filter(AnswerClaim.answer_id.in_(answer_ids)).all()] if answer_ids else []
    run_ids = [run_id for (run_id,) in db.query(RetrievalRun.id).filter(RetrievalRun.query_id.in_(query_ids)).all()] if query_ids else []
    if claim_ids:
        db.query(Citation).filter(Citation.claim_id.in_(claim_ids)).delete(synchronize_session=False)
        db.query(AnswerClaim).filter(AnswerClaim.id.in_(claim_ids)).delete(synchronize_session=False)
    if answer_ids:
        db.query(Answer).filter(Answer.id.in_(answer_ids)).delete(synchronize_session=False)
    if query_ids:
        db.query(Conflict).filter(Conflict.query_id.in_(query_ids)).delete(synchronize_session=False)
        db.query(Feedback).filter(Feedback.query_id.in_(query_ids)).delete(synchronize_session=False)
    if run_ids:
        db.query(RetrievalResult).filter(RetrievalResult.retrieval_run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(RetrievalRun).filter(RetrievalRun.id.in_(run_ids)).delete(synchronize_session=False)
    if query_ids:
        db.query(Query).filter(Query.id.in_(query_ids)).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
    return {"message": "Conversation deleted"}


@router.post("/answers/{answer_id}/feedback")
def submit_feedback(answer_id: int, payload: FeedbackRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer not found")
    query = answer.query
    db.add(AuditLog(user_id=user.id, action="feedback", resource_type="answer", resource_id=str(answer.id), details=payload.comment or payload.rating))
    db.commit()
    return {"message": "Feedback saved", "rating": payload.rating}
