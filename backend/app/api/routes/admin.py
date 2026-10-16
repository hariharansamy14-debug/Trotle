from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.core.config import settings
from app.core.security import hash_password
from app.models.models import AuditLog, DataSource, Role, SourceAccess, User

router = APIRouter()


@router.get("/settings/runtime")
def runtime_settings(user: User = Depends(get_current_user)) -> dict:
    provider = settings.llm_provider.strip().lower()
    embedding_provider = settings.embedding_provider.strip().lower()
    embedding_key_configured = bool(settings.embedding_api_key and settings.embedding_api_key.strip())
    if provider in {"grok", "xai"}:
        credentials_configured = bool(settings.grok_api_key and settings.grok_api_key.strip())
        llm_status = "untested" if credentials_configured else "missing_credentials"
        llm_name = "Grok (xAI)"
        endpoint = urlsplit(settings.grok_api_url)
        endpoint_host = endpoint.hostname if endpoint.scheme == "https" else None
        model = settings.grok_model
        diagnostic = "Credentials and model have not been verified against xAI." if credentials_configured else "Add a valid xAI API key to the backend environment."
    elif provider in {"gemini", "google"}:
        credentials_configured = bool(settings.google_api_key or settings.gemini_api_key)
        llm_status = "untested" if credentials_configured else "missing_credentials"
        llm_name = "Gemini (Google)"
        endpoint = urlsplit(settings.gemini_api_url)
        endpoint_host = endpoint.hostname if endpoint.scheme == "https" else None
        model = settings.gemini_model
        diagnostic = (
            "Credentials and model have not been verified against Google."
            if credentials_configured
            else "Add a valid Google AI key as GOOGLE_API_KEY or GEMINI_API_KEY in the backend .env file."
        )
    elif provider in {"mock", "local"}:
        llm_status = "local_only"
        llm_name = "Local evidence response"
        credentials_configured = False
        endpoint_host = None
        model = None
        diagnostic = "No external AI provider is used; responses are assembled from retrieved evidence."
    else:
        llm_status = "unsupported"
        llm_name = provider
        credentials_configured = False
        endpoint_host = None
        model = None
        diagnostic = "This provider is not supported by the current backend."
    return {
        "llm": {
            "provider": llm_name,
            "status": llm_status,
            "credentials_configured": credentials_configured,
            "model": model,
            "endpoint_host": endpoint_host,
            "diagnostic": diagnostic,
        },
        "embeddings": {
            "provider": settings.embedding_provider,
            "status": (
                "unsupported" if embedding_provider != "gemini"
                else "configured" if embedding_key_configured
                else "missing_credentials"
            ),
            "model": settings.embedding_model,
            "diagnostic": (
                "Gemini dense embeddings are enabled with BM25 and sparse-vector ranking."
                if embedding_provider == "gemini" and embedding_key_configured
                else "Set EMBEDDING_PROVIDER=gemini; mock embeddings are disabled."
                if embedding_provider != "gemini"
                else "Set GOOGLE_API_KEY (or GEMINI_API_KEY) in the backend .env file; mock embeddings are disabled."
            ),
        },
        "retrieval": {
            "method": "bm25_sparse_vector_gemini",
            "maximum_results": 8,
        },
        "source_connectors": {
            "file_upload": "available",
            "database": "unavailable",
            "website_api": "unavailable",
            "cloud_storage": "unavailable",
        },
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> list[dict]:
    rows = db.query(User).all()
    return [{"id": item.id, "name": item.name, "email": item.email, "role": item.role.name if item.role else "employee", "status": item.status} for item in rows]


@router.post("/users")
def create_user(payload: dict, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> dict:
    role = db.query(Role).filter(Role.name == payload.get("role", "employee")).first()
    if not role:
        role = Role(name=payload.get("role", "employee"))
        db.add(role); db.commit(); db.refresh(role)
    new_user = User(name=payload.get("name"), email=payload.get("email"), password_hash=hash_password(payload.get("password", "Welcome123")), role_id=role.id, status="active")
    db.add(new_user); db.commit(); db.refresh(new_user)
    db.add(AuditLog(user_id=user.id, action="create_user", resource_type="user", resource_id=str(new_user.id), details=new_user.email))
    db.commit()
    return {"message": "User created", "id": new_user.id}


@router.patch("/users/{user_id}")
def update_user(user_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> dict:
    row = db.query(User).filter(User.id == user_id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if payload.get("status"):
        row.status = payload["status"]
    if payload.get("role"):
        role = db.query(Role).filter(Role.name == payload["role"]).first()
        if role:
            row.role_id = role.id
    db.commit()
    return {"message": "User updated"}


@router.get("/audit-logs")
def list_audit_logs(db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> list[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).all()
    return [{"id": item.id, "action": item.action, "resource_type": item.resource_type, "resource_id": item.resource_id, "details": item.details, "created_at": item.created_at.isoformat()} for item in rows]


@router.get("/sources/{source_id}/access")
def list_source_access(source_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> list[dict]:
    if not db.query(DataSource).filter(DataSource.id == source_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    rows = db.query(SourceAccess).filter(SourceAccess.source_id == source_id).all()
    return [{
        "id": row.id,
        "user_id": row.user_id,
        "user_email": row.user.email if row.user else None,
        "role_id": row.role_id,
        "role": db.query(Role).filter(Role.id == row.role_id).first().name if row.role_id else None,
        "permission_level": row.permission_level,
    } for row in rows]


@router.post("/sources/{source_id}/access")
def grant_source_access(source_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> dict:
    source = db.query(DataSource).filter(DataSource.id == source_id).first()
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    user_id = payload.get("user_id")
    role_id = payload.get("role_id")
    permission_level = payload.get("permission_level", "read")
    if bool(user_id) == bool(role_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Specify exactly one of user_id or role_id.")
    if permission_level not in {"read", "write", "admin"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid permission level.")
    if user_id and not db.query(User).filter(User.id == user_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if role_id and not db.query(Role).filter(Role.id == role_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    query = db.query(SourceAccess).filter(SourceAccess.source_id == source_id)
    query = query.filter(SourceAccess.user_id == user_id) if user_id else query.filter(SourceAccess.role_id == role_id)
    access = query.first()
    if access:
        access.permission_level = permission_level
    else:
        access = SourceAccess(
            source_id=source_id,
            user_id=user_id,
            role_id=role_id,
            permission_level=permission_level,
        )
        db.add(access)
        db.flush()
    db.add(AuditLog(
        user_id=user.id,
        action="source_access_granted",
        resource_type="source",
        resource_id=str(source_id),
        details=f"access_id={access.id}; permission={permission_level}",
    ))
    db.commit()
    return {"id": access.id, "source_id": source_id, "permission_level": access.permission_level}


@router.delete("/sources/{source_id}/access/{access_id}")
def revoke_source_access(source_id: int, access_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))) -> dict:
    access = db.query(SourceAccess).filter(
        SourceAccess.id == access_id,
        SourceAccess.source_id == source_id,
    ).first()
    if not access:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source access assignment not found")
    db.add(AuditLog(
        user_id=user.id,
        action="source_access_revoked",
        resource_type="source",
        resource_id=str(source_id),
        details=f"access_id={access.id}",
    ))
    db.delete(access)
    db.commit()
    return {"message": "Source access revoked"}
