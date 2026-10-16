from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.models import Answer, AnswerClaim, AuditLog, ChangeAlert, Citation, Conflict, DataSource, Document, DocumentChunk, Query, User
from app.services.rag_service import STOP_WORDS, allowed_source_ids_for_user, can_access_source, can_manage_source, mask_sensitive_text

router = APIRouter()
GENERATED_FILENAME_SUFFIX = re.compile(
    r"(?i)(?:[-_][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[-_](?=[0-9a-f]{8,}$)(?=[0-9a-f]*[a-f])[0-9a-f]{8,})$"
)


def _relationship_document_label(filename: str) -> str:
    path = Path(filename)
    readable_stem = GENERATED_FILENAME_SUFFIX.sub("", path.stem).rstrip(" -_.")
    return f"{readable_stem}{path.suffix}" if readable_stem else filename


@router.get("")
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    source_ids = allowed_source_ids_for_user(db, user)
    docs = db.query(Document).filter(
        Document.source_id.in_(source_ids),
        Document.status != "Deleted",
    ).all()
    return [{
        "id": doc.id,
        "source_id": doc.source_id,
        "title": mask_sensitive_text(doc.title),
        "version": doc.version,
        "file_type": doc.file_type,
        "status": doc.status,
        "source_url": mask_sensitive_text(doc.source_url) if doc.source_url else None,
        "created_at": doc.created_at.isoformat(),
        "chunks": db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count(),
        "can_delete": can_manage_source(db, user, doc.source_id),
    } for doc in docs]


@router.get("/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not can_access_source(db, user, doc.source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return {"id": doc.id, "title": mask_sensitive_text(doc.title), "file_type": doc.file_type, "source_url": mask_sensitive_text(doc.source_url) if doc.source_url else None, "status": doc.status}


@router.get("/{document_id}/chunks")
def get_document_chunks(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not can_access_source(db, user, doc.source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return [{"id": chunk.id, "content": mask_sensitive_text(chunk.content), "page_number": chunk.page_number, "section_title": mask_sensitive_text(chunk.section_title) if chunk.section_title else None} for chunk in doc.chunks]


@router.get("/{document_id}/compare")
def compare_document_versions(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    current = db.query(Document).filter(Document.id == document_id).first()
    if not current or not can_access_source(db, user, current.source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    previous = db.query(Document).filter(
        Document.source_id == current.source_id,
        Document.title == current.title,
        Document.id != current.id,
    ).order_by(Document.created_at.desc()).first()
    if not previous:
        return {"document_id": current.id, "current_version": current.version, "previous_version": None, "changes": [], "message": "No earlier version is available."}

    old_text = "\n".join(mask_sensitive_text(chunk.content) for chunk in sorted(previous.chunks, key=lambda item: item.chunk_index))
    new_text = "\n".join(mask_sensitive_text(chunk.content) for chunk in sorted(current.chunks, key=lambda item: item.chunk_index))
    matcher = difflib.SequenceMatcher(a=old_text.splitlines(), b=new_text.splitlines())
    changes = [
        {"type": tag, "previous": old_text.splitlines()[i1:i2], "current": new_text.splitlines()[j1:j2]}
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]
    return {
        "document_id": current.id,
        "current_version": current.version,
        "previous_document_id": previous.id,
        "previous_version": previous.version,
        "changes": changes,
    }


@router.get("/relationships/map")
def document_relationship_map(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    accessible_source_ids = allowed_source_ids_for_user(db, user)
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()
    document_nodes: dict[int, dict] = {}

    def add_node(node_id: str, node_type: str, label: str, **details: object) -> None:
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "type": node_type,
            "label": mask_sensitive_text(label)[:180],
            "details": details,
        })

    def add_edge(source: str, target: str, relation: str, explanation: str, candidate: bool = False, **details: object) -> None:
        edges.append({
            "id": f"{source}|{relation}|{target}|{len(edges)}",
            "from": source,
            "to": target,
            "type": relation,
            "candidate": candidate,
            "explanation": explanation,
            "details": details,
        })

    visible_documents = db.query(Document).filter(
        Document.source_id.in_(accessible_source_ids),
        Document.status.in_(("Ready", "Archived")),
    ).order_by(Document.updated_at.desc()).limit(150).all() if accessible_source_ids else []
    for document in visible_documents:
        document_nodes[document.id] = {
            "id": f"document:{document.id}",
            "document": document,
            "type": "document",
        }

    query_rows = db.query(Query)
    if user.role.name != "admin":
        query_rows = query_rows.filter(Query.user_id == user.id)
    queries = query_rows.order_by(Query.created_at.desc()).limit(50).all()
    query_ids = [query.id for query in queries]
    answer_rows = db.query(Answer).filter(Answer.query_id.in_(query_ids)).all() if query_ids else []
    answers_by_query = {answer.query_id: answer for answer in answer_rows}
    answer_ids = [answer.id for answer in answer_rows]
    claims = db.query(AnswerClaim).filter(AnswerClaim.answer_id.in_(answer_ids)).all() if answer_ids else []
    claim_ids = [claim.id for claim in claims]
    citations = db.query(Citation).filter(Citation.claim_id.in_(claim_ids)).limit(300).all() if claim_ids else []
    citation_document_ids = {citation.document_id for citation in citations if citation.document_id is not None}
    historical_documents = db.query(Document).filter(
        Document.id.in_(citation_document_ids),
        Document.source_id.in_(accessible_source_ids),
    ).all() if citation_document_ids and accessible_source_ids else []
    for document in historical_documents:
        document_nodes.setdefault(document.id, {
            "id": f"document:{document.id}",
            "document": document,
            "type": "document",
        })

    sources = {
        source.id: source
        for source in db.query(DataSource).filter(DataSource.id.in_(accessible_source_ids)).all()
    } if accessible_source_ids else {}
    version_groups: dict[tuple[int, str], list[Document]] = {}
    for entry in document_nodes.values():
        document = entry["document"]
        version_groups.setdefault((document.source_id, document.title), []).append(document)
    version_document_ids = {
        document.id
        for group in version_groups.values() if len(group) > 1
        for document in sorted(group, key=lambda item: (item.created_at, item.id))[1:]
    }

    for document_id, entry in document_nodes.items():
        document = entry["document"]
        source = sources.get(document.source_id)
        is_version = document.id in version_document_ids
        display_title = _relationship_document_label(document.title)
        label = f"{display_title} — {document.version}" if is_version and document.version else display_title
        node_type = "document version" if is_version else "document"
        add_node(
            entry["id"],
            node_type,
            label,
            document_id=document.id,
            source_id=document.source_id,
            source_name=mask_sensitive_text(source.name) if source else "Not available",
            source_type=source.source_type if source else None,
            filename=mask_sensitive_text(document.title),
            version=document.version,
            status=document.status,
            created_at=document.created_at.isoformat() if document.created_at else None,
            updated_at=document.updated_at.isoformat() if document.updated_at else None,
            can_open=True,
        )

    # The source, exact title, and uploader-assigned version sequence establish version groups.
    for group in version_groups.values():
        if len(group) < 2:
            continue
        ordered_versions = sorted(group, key=lambda document: (document.created_at, document.id))
        parent_id = f"document:{ordered_versions[0].id}"
        for version_document in ordered_versions[1:]:
            add_edge(
                f"document:{version_document.id}",
                parent_id,
                "version of",
                "These uploads share the same source and exact original filename; version records were created by the upload workflow.",
            )

    hash_groups: dict[str, list[Document]] = {}
    for entry in document_nodes.values():
        document = entry["document"]
        if document.content_hash:
            hash_groups.setdefault(document.content_hash, []).append(document)
    for duplicate_group in hash_groups.values():
        if len(duplicate_group) > 1:
            for duplicate in duplicate_group[1:]:
                add_edge(
                    f"document:{duplicate.id}",
                    f"document:{duplicate_group[0].id}",
                    "identical content hash",
                    "Both stored documents have the same full-file SHA-256 hash; records remain separate.",
                )

    claims_by_answer: dict[int, list[AnswerClaim]] = {}
    for claim in claims:
        claims_by_answer.setdefault(claim.answer_id, []).append(claim)

    citation_chunk_ids = {citation.chunk_id for citation in citations if citation.chunk_id is not None}
    citation_chunks = {
        chunk.id: chunk for chunk in db.query(DocumentChunk).filter(DocumentChunk.id.in_(citation_chunk_ids)).all()
    } if citation_chunk_ids else {}
    citations_by_claim: dict[int, list[Citation]] = {}
    for citation in citations:
        citations_by_claim.setdefault(citation.claim_id, []).append(citation)

    for query in queries:
        answer = answers_by_query.get(query.id)
        if answer is None:
            continue
        question_id = f"question:{query.id}"
        add_node(
            question_id,
            "question",
            query.question,
            query_id=query.id,
            text=mask_sensitive_text(query.question),
            created_at=query.created_at.isoformat() if query.created_at else None,
            answer_status=answer.verification_status,
        )
        for claim in claims_by_answer.get(answer.id, []):
            claim_node_id = f"claim:{claim.id}"
            add_node(
                claim_node_id,
                "claim",
                claim.claim_text,
                claim_id=claim.id,
                query_id=query.id,
                text=mask_sensitive_text(claim.claim_text),
                status=claim.support_status,
                verification_basis="Existing deterministic term-overlap check; not semantic entailment.",
            )
            add_edge(question_id, claim_node_id, "answer includes", "This claim was saved as part of the answer to this question.")
            for citation in citations_by_claim.get(claim.id, []):
                document_entry = document_nodes.get(citation.document_id) if citation.document_id is not None else None
                document = document_entry["document"] if document_entry else None
                source_id = document.source_id if document else citation.source_id_snapshot
                if source_id is None or source_id not in accessible_source_ids:
                    continue
                if document is None or document.id not in document_nodes:
                    continue
                chunk = citation_chunks.get(citation.chunk_id)
                evidence_id = f"evidence:citation:{citation.id}"
                quote = citation.quoted_text or (chunk.content if chunk else "")
                add_node(
                    evidence_id,
                    "evidence",
                    quote,
                    citation_id=citation.id,
                    document_id=document.id,
                    source_id=source_id,
                    chunk_id=chunk.id if chunk else None,
                    page=citation.page_number or (chunk.page_number if chunk else None),
                    section=mask_sensitive_text(chunk.section_title) if chunk and chunk.section_title else None,
                    quote=mask_sensitive_text(quote[:1000]),
                    version=document.version or citation.document_version_snapshot,
                    status=citation.support_status,
                    can_open=True,
                )
                add_edge(claim_node_id, evidence_id, "cited evidence", f"Saved citation status: {citation.support_status}. Citation association is not an independent semantic verification.")
                add_edge(evidence_id, f"document:{document.id}", "passage from", "The citation references this source document and passage.")

    conflicts = db.query(Conflict).filter(Conflict.query_id.in_(query_ids)).limit(100).all() if query_ids else []
    question_ids_set = set(query_ids)
    for conflict in conflicts:
        visible_conflict_evidence = []
        for index, item in enumerate(conflict.evidence or []):
            source_id = item.get("source_id")
            if source_id not in accessible_source_ids:
                continue
            document_id = item.get("document_id")
            document_entry = document_nodes.get(document_id)
            if document_entry is None:
                continue
            evidence_id = f"evidence:conflict:{conflict.id}:{index}"
            document = document_entry["document"]
            add_node(
                evidence_id,
                "evidence",
                item.get("quote") or "Recorded conflict evidence",
                document_id=document.id,
                source_id=source_id,
                page=item.get("page"),
                version=item.get("version") or document.version,
                quote=mask_sensitive_text((item.get("quote") or "")[:1000]),
                status="Conflicting Information",
                values=item.get("values"),
                can_open=True,
            )
            visible_conflict_evidence.append(evidence_id)
            add_edge(evidence_id, f"document:{document.id}", "passage from", "This source passage was stored with the conflict record.")
        if not visible_conflict_evidence:
            continue
        conflict_id = f"conflict:{conflict.id}"
        add_node(
            conflict_id,
            "conflict",
            conflict.subject,
            conflict_id=conflict.id,
            query_id=conflict.query_id,
            summary=mask_sensitive_text(conflict.summary),
            status=conflict.status,
            resolution=mask_sensitive_text(conflict.resolution) if conflict.resolution else None,
            created_at=conflict.created_at.isoformat() if conflict.created_at else None,
            evidence_count=len(visible_conflict_evidence),
        )
        if conflict.query_id in question_ids_set:
            add_edge(f"question:{conflict.query_id}", conflict_id, "has recorded conflict", "A conflict record was saved for this question; its evidence is shown separately.")
        for evidence_id in visible_conflict_evidence:
            add_edge(conflict_id, evidence_id, "records disagreement", "This passage is one side of the stored conflict; the system does not determine which side is authoritative.")

    keyword_documents = [
        entry["document"] for entry in document_nodes.values()
        if entry["document"].status == "Ready"
    ][:40]
    keyword_doc_ids = [document.id for document in keyword_documents]
    if keyword_doc_ids:
        ranked_chunks = db.query(
            DocumentChunk.document_id.label("document_id"),
            DocumentChunk.content.label("content"),
            func.row_number().over(
                partition_by=DocumentChunk.document_id,
                order_by=DocumentChunk.chunk_index,
            ).label("chunk_rank"),
        ).filter(DocumentChunk.document_id.in_(keyword_doc_ids)).subquery()
        keyword_chunks = db.query(ranked_chunks.c.document_id, ranked_chunks.c.content).filter(
            ranked_chunks.c.chunk_rank <= 10
        ).order_by(ranked_chunks.c.document_id, ranked_chunks.c.chunk_rank).all()
    else:
        keyword_chunks = []
    terms_by_document: dict[int, set[str]] = {document_id: set() for document_id in keyword_doc_ids}
    for document_id, content in keyword_chunks:
        terms_by_document[document_id].update(
            term.lower() for term in re.findall(r"[A-Za-z0-9]{5,}", content or "")
            if term.lower() not in STOP_WORDS
        )
    keyword_links = 0
    for index, left in enumerate(keyword_documents):
        for right in keyword_documents[index + 1:]:
            shared_terms = sorted(terms_by_document[left.id] & terms_by_document[right.id])
            if len(shared_terms) < 2:
                continue
            add_edge(
                f"document:{left.id}",
                f"document:{right.id}",
                "possible topical overlap",
                "Candidate link based only on shared exact content terms; it is not evidence of support, contradiction, or semantic similarity.",
                candidate=True,
                shared_terms=[mask_sensitive_text(term) for term in shared_terms[:8]],
            )
            keyword_links += 1
            if keyword_links >= 150:
                break
        if keyword_links >= 150:
            break

    return {
        "nodes": nodes,
        "edges": edges,
        "basis": "Evidence edges come from saved questions, claim citations, source passages, conflict records, and upload version metadata. Claim statuses use deterministic term overlap, not semantic entailment. Keyword-overlap links are candidates only.",
        "limits": {"documents": 150, "questions": 50, "citations": 300, "keyword_documents": 40, "keyword_edges": 150},
        "truncated": len(visible_documents) >= 150 or len(queries) >= 50 or len(citations) >= 300 or len(conflicts) >= 100,
    }


@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc or not can_manage_source(db, user, doc.source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    alert = ChangeAlert(
        source_id=doc.source_id,
        document_id=doc.id,
        document_title=doc.title,
        event_type="deleted",
        dedupe_key=hashlib.sha256(f"deleted:{doc.source_id}:{doc.source_url}:{doc.content_hash}".encode()).hexdigest(),
        summary=f"{doc.title} ({doc.version or 'version unknown'}) was deleted.",
    )
    db.add(alert)
    doc.status = "Deleted"
    db.add(AuditLog(user_id=user.id, action="delete_document", resource_type="document", resource_id=str(doc.id), details=doc.title))
    db.commit()
    return {"message": "Document deleted"}
