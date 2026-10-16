from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.documents import router as documents_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.reports import router as reports_router
from app.api.routes.sources import router as sources_router
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.models.models import AuditLog, Base, DataSource, Permission, Role, RolePermission, User

if engine.dialect.name == "sqlite":
    Base.metadata.create_all(bind=engine)


def ensure_additive_schema_compatibility() -> None:
    if engine.dialect.name != "sqlite":
        return
    additions = {
        "answers": [("evidence_coverage", "JSON")],
        "conflicts": [("evidence", "JSON")],
        "change_alerts": [("document_title", "VARCHAR(255) NOT NULL DEFAULT ''")],
        "citations": [
            ("source_id_snapshot", "INTEGER"),
            ("document_title_snapshot", "VARCHAR(255)"),
            ("document_version_snapshot", "VARCHAR(50)"),
        ],
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table, columns_to_add in additions.items():
            if table not in tables:
                continue
            existing_columns = {item["name"] for item in inspector.get_columns(table)}
            for column, column_type in columns_to_add:
                if column not in existing_columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))
        if "change_alerts" in tables:
            connection.execute(text(
                "UPDATE change_alerts SET document_title = "
                "(SELECT title FROM documents WHERE documents.id = change_alerts.document_id) "
                "WHERE document_title = '' AND document_id IS NOT NULL"
            ))
        if "citations" in tables:
            connection.execute(text(
                "UPDATE citations SET "
                "source_id_snapshot = (SELECT source_id FROM documents WHERE documents.id = citations.document_id), "
                "document_title_snapshot = (SELECT title FROM documents WHERE documents.id = citations.document_id), "
                "document_version_snapshot = (SELECT version FROM documents WHERE documents.id = citations.document_id) "
                "WHERE document_id IS NOT NULL"
            ))


ensure_additive_schema_compatibility()
app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth")
app.include_router(sources_router, prefix="/api/sources")
app.include_router(documents_router, prefix="/api/documents")
app.include_router(chat_router, prefix="/api")
app.include_router(evidence_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(admin_router, prefix="/api")


@app.get("/health")
def health() -> dict:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "service": settings.app_name, "database": "connected"}


def seed_initial_roles_and_admin(db: Session) -> None:
    admin_role = db.query(Role).filter(Role.name == "admin").first()
    if not admin_role:
        admin_role = Role(name="admin")
        db.add(admin_role)
        db.flush()
    manager_role = db.query(Role).filter(Role.name == "manager").first()
    if not manager_role:
        manager_role = Role(name="manager")
        db.add(manager_role)
        db.flush()
    employee_role = db.query(Role).filter(Role.name == "employee").first()
    if not employee_role:
        employee_role = Role(name="employee")
        db.add(employee_role)
        db.flush()

    for name in ["view_sources", "manage_sources", "qa_access", "manage_users", "view_reports"]:
        perm = db.query(Permission).filter(Permission.name == name).first()
        if not perm:
            perm = Permission(name=name)
            db.add(perm)
            db.flush()
        if name == "view_sources":
            if not db.query(RolePermission).filter(RolePermission.role_id == employee_role.id, RolePermission.permission_id == perm.id).first():
                db.add(RolePermission(role_id=employee_role.id, permission_id=perm.id))
        if name in {"view_sources", "manage_sources", "qa_access"}:
            if not db.query(RolePermission).filter(RolePermission.role_id == manager_role.id, RolePermission.permission_id == perm.id).first():
                db.add(RolePermission(role_id=manager_role.id, permission_id=perm.id))
        if not db.query(RolePermission).filter(RolePermission.role_id == admin_role.id, RolePermission.permission_id == perm.id).first():
            db.add(RolePermission(role_id=admin_role.id, permission_id=perm.id))

    admin_user = db.query(User).filter(User.email == "admin@company.com").first()
    bootstrap_password = settings.bootstrap_admin_password
    if engine.dialect.name == "sqlite" and not bootstrap_password:
        bootstrap_password = "admin123"
    if not admin_user:
        if bootstrap_password:
            admin_user = User(
                name="Admin User",
                email="admin@company.com",
                password_hash=hash_password(bootstrap_password),
                role_id=admin_role.id,
                status="active",
            )
            db.add(admin_user)
            db.flush()

    for source in db.query(DataSource).all():
        if (source.configuration or {}).get("source") != "demo":
            continue
        changed = source.connection_status != "Setup required"
        source.connection_status = "Setup required"
        for document in source.documents:
            if document.status == "Ready":
                document.status = "Archived"
                changed = True
        if changed:
            db.add(AuditLog(
                user_id=admin_user.id if admin_user else None,
                action="demo_source_archived",
                resource_type="source",
                resource_id=str(source.id),
                details="Seeded example data was archived and removed from retrieval.",
            ))

    db.commit()


# Ensure base roles and the initial admin account exist before requests.
db = SessionLocal()
try:
    seed_initial_roles_and_admin(db)
finally:
    db.close()


@app.on_event("startup")
def startup() -> None:
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(bind=engine)
    ensure_additive_schema_compatibility()
    db = SessionLocal()
    try:
        seed_initial_roles_and_admin(db)
    finally:
        db.close()


@app.get("/")
def root() -> dict:
    return {"message": "Enterprise RAG Assistant backend is running."}
