import uuid
from datetime import UTC, datetime, timedelta

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import AuditLog, Organization, RefreshToken, User
from app.schemas import (
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.security import (
    create_access_token,
    generate_random_token,
    hash_password,
    hash_token,
    verify_password,
)

router = APIRouter()

GENERIC_AUTH_ERROR = "Invalid email or password"


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new organization and admin user",
)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> User:
    """Create a new organization and its initial admin user."""
    existing_user = db.query(User).filter(User.email == payload.email.lower()).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists",
        )

    # 1. Create Organization
    org = Organization(
        id=uuid.uuid4(),
        name=payload.org_name.strip(),
    )
    db.add(org)
    db.flush()

    # 2. Create Admin User
    user = User(
        id=uuid.uuid4(),
        org_id=org.id,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role="admin",
        is_active=True,
    )
    db.add(user)
    db.flush()

    # 3. Create Audit Log
    audit_entry = AuditLog(
        id=uuid.uuid4(),
        org_id=org.id,
        user_id=user.id,
        action="organization_registered",
        entity_type="organization",
        entity_id=org.id,
        new_value={"org_name": org.name, "admin_email": user.email},
    )
    db.add(audit_entry)

    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate user and issue access JWT + refresh token cookie",
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Verify credentials, return short-lived JWT, and set HttpOnly refresh token cookie."""
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GENERIC_AUTH_ERROR,
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GENERIC_AUTH_ERROR,
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=GENERIC_AUTH_ERROR,
        )

    # Issue access token
    access_token = create_access_token(
        user_id=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
    )

    # Generate random refresh token & store ONLY its SHA-256 hash
    raw_refresh_token = generate_random_token()
    token_digest = hash_token(raw_refresh_token)
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    refresh_token_record = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_digest,
        expires_at=expires_at,
    )
    db.add(refresh_token_record)
    db.commit()

    # Set HttpOnly cookie
    max_age_seconds = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    response.set_cookie(
        key="refresh_token",
        value=raw_refresh_token,
        httponly=True,
        samesite="lax",
        max_age=max_age_seconds,
        path="/",
    )

    return TokenResponse(access_token=access_token, token_type="bearer")


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate refresh token and issue new access JWT",
)
def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    x_refresh_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Rotate refresh token. Revoke all sessions if a revoked token is reused."""
    raw_token = refresh_token or x_refresh_token
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    token_digest = hash_token(raw_token)
    token_record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_digest).first()

    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Check for reuse of an already-revoked token
    if token_record.revoked_at is not None:
        # Security incident: revoke all refresh tokens for this user
        db.query(RefreshToken).filter(
            RefreshToken.user_id == token_record.user_id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(UTC)}, synchronize_session="fetch")
        db.commit()

        response.delete_cookie(key="refresh_token", path="/")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Revoked refresh token reused; all sessions revoked",
        )

    # Check expiry (ensure timezone-aware comparison for SQLite/PostgreSQL compatibility)
    expires_at = (
        token_record.expires_at
        if token_record.expires_at.tzinfo is not None
        else token_record.expires_at.replace(tzinfo=UTC)
    )
    if expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    user = db.query(User).filter(User.id == token_record.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Rotate token: insert and flush new token first to prevent ForeignKeyViolation
    now = datetime.now(UTC)
    new_token_id = uuid.uuid4()
    new_raw_token = generate_random_token()
    new_token_digest = hash_token(new_raw_token)
    new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    new_token_record = RefreshToken(
        id=new_token_id,
        user_id=user.id,
        token_hash=new_token_digest,
        expires_at=new_expires_at,
    )
    db.add(new_token_record)
    db.flush()

    token_record.revoked_at = now
    token_record.replaced_by_id = new_token_id
    db.commit()

    # Issue new access token
    new_access_token = create_access_token(
        user_id=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
    )

    max_age_seconds = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    response.set_cookie(
        key="refresh_token",
        value=new_raw_token,
        httponly=True,
        samesite="lax",
        max_age=max_age_seconds,
        path="/",
    )

    return TokenResponse(access_token=new_access_token, token_type="bearer")


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke the current refresh token and clear cookie",
)
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    x_refresh_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Revoke active refresh token and delete cookie."""
    raw_token = refresh_token or x_refresh_token
    if raw_token:
        token_digest = hash_token(raw_token)
        token_record = db.query(RefreshToken).filter(RefreshToken.token_hash == token_digest).first()
        if token_record and token_record.revoked_at is None:
            token_record.revoked_at = datetime.now(UTC)
            db.commit()

    response.delete_cookie(key="refresh_token", path="/")
    return MessageResponse(detail="Successfully logged out")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    """Return the profile of the currently logged-in user."""
    return current_user
