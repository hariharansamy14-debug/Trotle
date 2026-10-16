from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.models import AuditLog, ChangeAlert, DataSource, Document, DocumentChunk, SyncJob, User
from app.schemas.sources import SourceCreateRequest, SourceSyncRequest
from app.services.file_service import SUPPORTED_TYPES, chunk_text, ensure_upload_directory, extract_pages_from_file, file_hash
from app.services.rag_service import allowed_source_ids_for_user, can_access_source, mask_sensitive_text, mask_sensitive_value

router = APIRouter()


def validate_public_source_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid source URL is required.")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(re.search(r"password|api[_-]?key|access[_-]?token|secret|credential", key, re.I) for key, _ in parse_qsl(parsed.query))
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use an HTTP(S) URL without embedded credentials or secret query parameters.",
        )
    return value


@router.get("")
def list_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    source_ids = allowed_source_ids_for_user(db, user)
    sources = db.query(DataSource).filter(DataSource.id.in_(source_ids)).all()
    return [{
        "id": source.id,
        "name": mask_sensitive_text(source.name),
        "source_type": source.source_type,
        "connection_status": source.connection_status,
        "status": source.connection_status,
        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
        "documents_count": db.query(Document).filter(
            Document.source_id == source.id,
            Document.status != "Deleted",
        ).count(),
    } for source in sources]


@router.post("/files")
def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")

    upload_dir = ensure_upload_directory(".")
    destination = upload_dir / f"{uuid4().hex}{extension}"
    with destination.open("wb") as handle:
        handle.write(file.file.read())

    try:
        pages = extract_pages_from_file(str(destination), filename)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not extract text: {str(exc)}") from exc

    content_hash = file_hash(str(destination))
    source = db.query(DataSource).filter(DataSource.owner_id == user.id, DataSource.name == filename).first()
    if not source:
        source = DataSource(name=filename, source_type="upload", owner_id=user.id, connection_status="Ready", configuration={"filename": filename})
        db.add(source); db.commit(); db.refresh(source)

    previous = db.query(Document).filter(
        Document.source_id == source.id,
        Document.title == filename,
    ).order_by(Document.created_at.desc()).first()
    if previous and previous.content_hash == content_hash:
        destination.unlink(missing_ok=True)
        return {"message": "This exact document version is already indexed.", "source_id": source.id, "document_id": previous.id, "duplicate": True}

    version_number = 1
    if previous:
        match = re.search(r"(\d+)$", previous.version or "")
        version_number = int(match.group(1)) + 1 if match else 2
        previous.status = "Archived"
    document = Document(
        source_id=source.id,
        title=filename,
        file_type=extension,
        source_url=str(destination),
        content_hash=content_hash,
        version=f"v{version_number}",
        status="Ready",
    )
    db.add(document); db.commit(); db.refresh(document)

    index = 0
    for page_text, page_number in pages:
        for chunk_text_value in chunk_text(page_text):
            db.add(DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk_text_value,
                page_number=page_number,
                section_title="Uploaded File",
                chunk_metadata={"filename": filename},
            ))
            index += 1
    dedupe_key = hashlib.sha256(f"{source.id}:{document.source_url}:{content_hash}".encode()).hexdigest()
    db.add(ChangeAlert(
        source_id=source.id,
        document_id=document.id,
        document_title=filename,
        event_type="modified" if previous else "new",
        dedupe_key=dedupe_key,
        summary=(
            f"{filename} changed from {previous.version or 'an earlier version'} to {document.version}."
            if previous else f"{filename} was added as {document.version}."
        ),
    ))
    db.add(AuditLog(user_id=user.id, action="upload_file", resource_type="document", resource_id=str(document.id), details=f"{filename} indexed as {document.version}"))
    db.commit()

    return {"message": "File uploaded and processed successfully", "source_id": source.id, "document_id": document.id, "version": document.version, "changed": previous is not None}


@router.post("/database/test")
def test_database_connection(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    if not payload.get("host") or not payload.get("database_name"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Database host and name are required.")
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="No database connector is configured; no connection was attempted.")


@router.post("/database")
def create_database_source(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    source = DataSource(name=payload.get("name", "Database Source"), source_type="database", owner_id=user.id, connection_status="Setup required", configuration={"database_type": payload.get("database_type", "postgresql")})
    db.add(source); db.commit(); db.refresh(source)
    db.add(AuditLog(user_id=user.id, action="source_created", resource_type="source", resource_id=str(source.id), details="database adapter setup required"))
    db.commit()
    return {"message": "Database source created", "source_id": source.id}


@router.post("/website")
def create_website_source(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    url = validate_public_source_url(payload.get("url"))
    source = DataSource(name=payload.get("name", "Website Source"), source_type="website", owner_id=user.id, connection_status="Setup required", configuration={"url": url})
    db.add(source); db.commit(); db.refresh(source)
    db.add(AuditLog(user_id=user.id, action="source_created", resource_type="source", resource_id=str(source.id), details="website adapter setup required"))
    db.commit()
    return {"message": "Website source created", "source_id": source.id}


@router.post("/api")
def create_api_source(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    base_url = validate_public_source_url(payload.get("base_url"))
    source = DataSource(name=payload.get("name", "API Source"), source_type="api", owner_id=user.id, connection_status="Setup required", configuration={"base_url": base_url})
    db.add(source); db.commit(); db.refresh(source)
    db.add(AuditLog(user_id=user.id, action="source_created", resource_type="source", resource_id=str(source.id), details="API adapter setup required"))
    db.commit()
    return {"message": "API source created", "source_id": source.id}


@router.post("/cloud/authorize")
def authorize_cloud_source(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    provider = payload.get("provider", "google_drive")
    if not provider:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider is required.")
    return {"status": "setup_required", "message": f"Setup required for {provider}. Configure OAuth credentials first."}


@router.get("/{source_id}")
def get_source(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source or not can_access_source(db, user, source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return {"id": source.id, "name": mask_sensitive_text(source.name), "source_type": source.source_type, "connection_status": source.connection_status, "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None, "configuration": mask_sensitive_value(source.configuration)}


@router.post("/{source_id}/sync")
def sync_source(source_id: int, payload: SourceSyncRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    source = db.query(DataSource).filter(DataSource.id == source_id, DataSource.owner_id == user.id).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    job = SyncJob(source_id=source.id, status="failed", started_at=datetime.utcnow(), completed_at=datetime.utcnow(),
                  error_message="No synchronization adapter is configured for this source type.")
    db.add(job)
    db.add(AuditLog(user_id=user.id, action="sync_failed", resource_type="source", resource_id=str(source.id), details=job.error_message))
    db.commit()
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=job.error_message)


@router.post("/{source_id}/retry")
def retry_source(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    source = db.query(DataSource).filter(DataSource.id == source_id, DataSource.owner_id == user.id).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    job = SyncJob(source_id=source.id, status="failed", started_at=datetime.utcnow(), completed_at=datetime.utcnow(),
                  error_message="No synchronization adapter is configured for this source type.")
    db.add(job)
    db.add(AuditLog(user_id=user.id, action="sync_failed", resource_type="source", resource_id=str(source.id), details=job.error_message))
    db.commit()
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=job.error_message)


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    source = db.query(DataSource).filter(DataSource.id == source_id, DataSource.owner_id == user.id).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    db.add(AuditLog(user_id=user.id, action="source_deleted", resource_type="source", resource_id=str(source.id), details=source.name))
    db.delete(source)
    db.commit()
    return {"message": "Source removed"}
