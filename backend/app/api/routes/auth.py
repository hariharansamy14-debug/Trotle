from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.models import AuditLog, Role, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered")
    role = db.query(Role).filter(Role.name == "employee").first()
    if not role:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Role configuration missing")
    user = User(name=payload.name, email=payload.email.lower(), password_hash=hash_password(payload.password), role_id=role.id, status="active")
    db.add(user)
    db.commit(); db.refresh(user)
    db.add(AuditLog(user_id=user.id, action="register", resource_type="user", resource_id=str(user.id), details="User registered"))
    db.commit()
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user={"id": user.id, "name": user.name, "email": user.email, "role": user.role.name if user.role else "employee"})


@router.post("/login", response_model=TokenResponse)
def login_user(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user={"id": user.id, "name": user.name, "email": user.email, "role": user.role.name if user.role else "employee"})


@router.post("/logout")
def logout_user(user: User = Depends(get_current_user)) -> dict:
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def current_user(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(id=user.id, name=user.name, email=user.email, role=user.role.name if user.role else "employee", status=user.status)
