import os
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_db
from app.deps import get_storage
from app.main import app
from app.models import Organization, User
from app.security import create_access_token, hash_password
from app.storage import LocalStorage, Storage


def get_test_database_url() -> str:
    """Resolve test database connection string for local host or inside Docker."""
    if url := os.getenv("TEST_DATABASE_URL"):
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    # Inside Docker container
    if Path("/.dockerenv").exists():
        return "postgresql+psycopg://docflow:docflow_password@db:5432/docflow_test"

    # On host machine
    return "postgresql+psycopg://docflow:docflow_password@localhost:5433/docflow_test"


TEST_DATABASE_URL = get_test_database_url()


def ensure_test_database_exists(db_url: str) -> None:
    """Ensure the separate 'docflow_test' database exists on the PostgreSQL service."""
    try:
        parsed = db_url.rsplit("/", 1)
        admin_url = f"{parsed[0]}/postgres"
        db_name = parsed[1].split("?")[0]
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        admin_engine.dispose()
    except Exception:
        # If unable to connect to maintenance DB or database already exists, proceed
        pass


ensure_test_database_exists(TEST_DATABASE_URL)

test_engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all schema tables in the separate docflow_test PostgreSQL database."""
    with test_engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text(
                    "DROP TABLE IF EXISTS validation_issues, line_items, extractions, "
                    "audit_log, documents, refresh_tokens, users, organizations CASCADE;"
                )
            )
    Base.metadata.create_all(bind=test_engine)
    yield
    # Tables remain in docflow_test schema


def truncate_tables():
    """Truncate all data in docflow_test using CASCADE to preserve schema across tests."""
    with test_engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text(
                    "TRUNCATE TABLE audit_log, validation_issues, line_items, extractions, documents, refresh_tokens, users, organizations CASCADE;"
                )
            )


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure every test begins and ends with an empty test database."""
    truncate_tables()
    yield
    truncate_tables()


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a direct session to docflow_test for fixture setup and assertions."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def temp_storage(tmp_path: Path) -> Storage:
    storage_dir = tmp_path / "uploads"
    storage_dir.mkdir(parents=True, exist_ok=True)
    return LocalStorage(storage_dir)


@pytest.fixture
def client(temp_storage: Storage) -> Generator[TestClient, None, None]:
    """TestClient wired to docflow_test PostgreSQL database and temporary storage."""

    def override_get_db() -> Generator[Session, None, None]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    def override_get_storage() -> Storage:
        return temp_storage

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage] = override_get_storage

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def org_a(db_session: Session) -> Organization:
    org = Organization(id=uuid.uuid4(), name="Acme Corp")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def org_b(db_session: Session) -> Organization:
    org = Organization(id=uuid.uuid4(), name="Beta Industries")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture
def admin_user_a(db_session: Session, org_a: Organization) -> User:
    user = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="admin_a@acme.com",
        password_hash=hash_password("admin_pass_123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def reviewer_user_a(db_session: Session, org_a: Organization) -> User:
    user = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="reviewer_a@acme.com",
        password_hash=hash_password("reviewer_pass_123"),
        role="reviewer",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def viewer_user_a(db_session: Session, org_a: Organization) -> User:
    user = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="viewer_a@acme.com",
        password_hash=hash_password("viewer_pass_123"),
        role="viewer",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def user_b(db_session: Session, org_b: Organization) -> User:
    user = User(
        id=uuid.uuid4(),
        org_id=org_b.id,
        email="admin_b@beta.com",
        password_hash=hash_password("admin_pass_b"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers_for(user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
    )
    return {"Authorization": f"Bearer {token}"}
