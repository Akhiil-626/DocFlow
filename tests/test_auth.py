import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import RefreshToken, User
from tests.conftest import auth_headers_for


def test_register_and_login_success(client: TestClient, db_session: Session):
    """Test successful organization registration and subsequent user login."""
    register_payload = {
        "org_name": "Initech Corp",
        "email": "peter@initech.com",
        "password": "SecurePassword123!",
    }
    reg_res = client.post("/auth/register", json=register_payload)
    assert reg_res.status_code == 201
    user_data = reg_res.json()
    assert user_data["email"] == "peter@initech.com"
    assert user_data["role"] == "admin"
    assert "id" in user_data
    assert "org_id" in user_data

    # Verify login
    login_payload = {
        "email": "peter@initech.com",
        "password": "SecurePassword123!",
    }
    login_res = client.post("/auth/login", json=login_payload)
    assert login_res.status_code == 200
    token_data = login_res.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"

    # Verify HttpOnly cookie
    assert "refresh_token" in login_res.cookies
    refresh_token = login_res.cookies["refresh_token"]
    assert len(refresh_token) > 20

    # Verify /auth/me with access token
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    me_res = client.get("/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "peter@initech.com"


def test_login_wrong_password_fails_with_generic_message(client: TestClient, admin_user_a: User):
    """Test wrong password fails with the generic error message."""
    login_res = client.post(
        "/auth/login",
        json={"email": admin_user_a.email, "password": "WrongPassword123!"},
    )
    assert login_res.status_code == 401
    assert login_res.json()["detail"] == "Invalid email or password"


def test_login_nonexistent_email_fails_with_same_generic_message(client: TestClient):
    """Test non-existent email fails with the exact same generic error message."""
    login_res = client.post(
        "/auth/login",
        json={"email": "nonexistent@user.com", "password": "AnyPassword123!"},
    )
    assert login_res.status_code == 401
    assert login_res.json()["detail"] == "Invalid email or password"


def test_refresh_token_rotation(client: TestClient, admin_user_a: User, db_session: Session):
    """Test rotating refresh token revokes the old one and issues a new valid token."""
    login_res = client.post(
        "/auth/login",
        json={"email": admin_user_a.email, "password": "admin_pass_123"},
    )
    assert login_res.status_code == 200
    first_refresh_cookie = login_res.cookies["refresh_token"]

    # Rotate refresh token
    refresh_res = client.post("/auth/refresh", cookies={"refresh_token": first_refresh_cookie})
    assert refresh_res.status_code == 200
    new_token_data = refresh_res.json()
    assert "access_token" in new_token_data

    second_refresh_cookie = refresh_res.cookies["refresh_token"]
    assert second_refresh_cookie != first_refresh_cookie

    # New token works to access protected route
    me_res = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {new_token_data['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["email"] == admin_user_a.email


def test_refresh_token_reuse_revokes_all_user_sessions(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    """Test reusing an already-revoked refresh token revokes ALL tokens for that user and returns 401."""
    login_res = client.post(
        "/auth/login",
        json={"email": admin_user_a.email, "password": "admin_pass_123"},
    )
    assert login_res.status_code == 200
    first_token = login_res.cookies["refresh_token"]

    # Legitimate rotation 1
    rotate_res = client.post("/auth/refresh", cookies={"refresh_token": first_token})
    assert rotate_res.status_code == 200
    second_token = rotate_res.cookies["refresh_token"]

    # Attacker or replay tries to reuse old first_token!
    reuse_res = client.post("/auth/refresh", cookies={"refresh_token": first_token})
    assert reuse_res.status_code == 401
    assert "revoked" in reuse_res.json()["detail"].lower()

    # Now verify that even second_token (which was previously active) has been revoked!
    second_reuse_res = client.post("/auth/refresh", cookies={"refresh_token": second_token})
    assert second_reuse_res.status_code == 401

    # In DB, all refresh tokens for this user must now be revoked
    active_tokens = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.user_id == admin_user_a.id, RefreshToken.revoked_at.is_(None))
        .all()
    )
    assert len(active_tokens) == 0


def test_logout_revokes_token_and_clears_cookie(
    client: TestClient,
    admin_user_a: User,
    db_session: Session,
):
    """Test logout revokes the active token and deletes the cookie."""
    login_res = client.post(
        "/auth/login",
        json={"email": admin_user_a.email, "password": "admin_pass_123"},
    )
    assert login_res.status_code == 200
    refresh_cookie = login_res.cookies["refresh_token"]

    # Call logout
    logout_res = client.post("/auth/logout", cookies={"refresh_token": refresh_cookie})
    assert logout_res.status_code == 200
    assert logout_res.json()["detail"] == "Successfully logged out"

    # Refresh with logged-out token must fail
    refresh_res = client.post("/auth/refresh", cookies={"refresh_token": refresh_cookie})
    assert refresh_res.status_code == 401


def test_refresh_token_reuse_regression(client: TestClient):
    """Regression test per requirement 5:
    register, login, refresh (200), reuse the old token (401), and confirm the newest token also fails (401).
    """
    # 1. Register
    reg_res = client.post(
        "/auth/register",
        json={
            "org_name": "Regression Org",
            "email": "regression@test.com",
            "password": "Password123!",
        },
    )
    assert reg_res.status_code == 201

    # 2. Login
    login_res = client.post(
        "/auth/login",
        json={
            "email": "regression@test.com",
            "password": "Password123!",
        },
    )
    assert login_res.status_code == 200
    token1 = login_res.cookies["refresh_token"]

    # 3. Refresh (200) -> issues token2, revokes token1 with replaced_by_id=token2
    refresh_res = client.post("/auth/refresh", cookies={"refresh_token": token1})
    assert refresh_res.status_code == 200
    token2 = refresh_res.cookies["refresh_token"]

    # 4. Reuse old token1 -> 401 (triggers revocation of all tokens)
    reuse_res = client.post("/auth/refresh", cookies={"refresh_token": token1})
    assert reuse_res.status_code == 401

    # 5. Confirm newest token2 also fails with 401
    newest_res = client.post("/auth/refresh", cookies={"refresh_token": token2})
    assert newest_res.status_code == 401
