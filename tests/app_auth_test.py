"""Tests for the /auth route."""

from __future__ import annotations

import base64
import os
import time
from typing import TYPE_CHECKING
from unittest.mock import ANY, call, patch

import jwt

from jwt_authorizer import config
from jwt_authorizer.session import SessionStore, Ticket
from tests.util import RSAKeyPair, create_test_app, create_test_token

if TYPE_CHECKING:
    import redis


def assert_www_authenticate_header_matches(
    header: str, method: str, error: str
) -> None:
    header_method, header_info = header.split(" ", 1)
    assert header_method == method
    if header_method == "Basic":
        assert header_info == 'realm="tokens"'
    else:
        data = header_info.split(",")
        assert data[0] == 'realm="tokens"'
        assert data[1] == f'error="{error}"'
        assert data[2].startswith("error_description=")


def test_authnz_token_no_auth() -> None:
    app = create_test_app()

    with app.test_client() as client:
        r = client.get("/auth?capability=exec:admin")
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"]
        assert_www_authenticate_header_matches(
            r.headers["WWW-Authenticate"], "Bearer", "No Authorization header"
        )

        r = client.get(
            "/auth?capability=exec:admin", headers={"Authorization": "Bearer"}
        )
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"]
        assert_www_authenticate_header_matches(
            r.headers["WWW-Authenticate"], "Bearer", "Unable to find token"
        )

        r = client.get(
            "/auth?capability=exec:admin",
            headers={"Authorization": "Bearer token"},
        )
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"]
        assert_www_authenticate_header_matches(
            r.headers["WWW-Authenticate"], "Bearer", "Invalid Token"
        )


def test_authnz_token_access_denied() -> None:
    keypair = RSAKeyPair()
    token = create_test_token(keypair)
    app = create_test_app(keypair)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            r = client.get(
                "/auth?capability=exec:admin",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert get_key_as_pem.call_args_list == [
                call("https://test.example.com/", "some-kid")
            ]

    assert r.status_code == 403
    assert b"No Capability group found in user's `isMemberOf`" in r.data
    assert r.headers["X-Auth-Request-Token-Capabilities"] == ""
    assert r.headers["X-Auth-Request-Capabilities-Accepted"] == "exec:admin"
    assert r.headers["X-Auth-Request-Capabilities-Satisfy"] == "all"


def test_authnz_token_satisfy_all() -> None:
    keypair = RSAKeyPair()
    token = create_test_token(keypair, ["test"])
    app = create_test_app(keypair)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            r = client.get(
                "/auth?capability=exec:test&capability=exec:admin",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert get_key_as_pem.call_args_list == [
                call("https://test.example.com/", "some-kid")
            ]

    assert r.status_code == 403
    assert b"No Capability group found in user's `isMemberOf`" in r.data
    assert r.headers["X-Auth-Request-Token-Capabilities"] == "exec:test"
    assert (
        r.headers["X-Auth-Request-Capabilities-Accepted"]
        == "exec:admin exec:test"
    )
    assert r.headers["X-Auth-Request-Capabilities-Satisfy"] == "all"


def test_authnz_token_success() -> None:
    keypair = RSAKeyPair()
    token = create_test_token(keypair, ["admin"])
    app = create_test_app(keypair)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            r = client.get(
                "/auth?capability=exec:admin",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert get_key_as_pem.call_args_list == [
                call("https://test.example.com/", "some-kid")
            ]

    assert r.status_code == 200
    assert (
        r.headers["X-Auth-Request-Token-Capabilities"] == "exec:admin read:all"
    )
    assert r.headers["X-Auth-Request-Capabilities-Accepted"] == "exec:admin"
    assert r.headers["X-Auth-Request-Capabilities-Satisfy"] == "all"
    assert r.headers["X-Auth-Request-Email"] == "some-user@example.com"
    assert r.headers["X-Auth-Request-User"] == "some-user"
    assert r.headers["X-Auth-Request-Uid"] == "1000"
    assert r.headers["X-Auth-Request-Groups"] == "admin"
    assert r.headers["X-Auth-Request-Token"] == token
    assert r.headers["X-Auth-Request-Token-Ticket"] == ""


def test_authnz_token_success_any() -> None:
    keypair = RSAKeyPair()
    token = create_test_token(keypair, ["test"])
    app = create_test_app(keypair)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            r = client.get(
                "/auth?capability=exec:admin&capability=exec:test&satisfy=any",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert get_key_as_pem.call_args_list == [
                call("https://test.example.com/", "some-kid")
            ]

    assert r.status_code == 200
    assert r.headers["X-Auth-Request-Token-Capabilities"] == "exec:test"
    assert (
        r.headers["X-Auth-Request-Capabilities-Accepted"]
        == "exec:admin exec:test"
    )
    assert r.headers["X-Auth-Request-Capabilities-Satisfy"] == "any"
    assert r.headers["X-Auth-Request-Groups"] == "test"


def test_authnz_token_forwarded() -> None:
    keypair = RSAKeyPair()
    token = create_test_token(keypair, ["admin"])
    app = create_test_app(keypair)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            r = client.get(
                "/auth?capability=exec:admin",
                headers={
                    "Authorization": "Basic blah",
                    "X-Forwarded-Access-Token": token,
                },
            )

    assert r.status_code == 200
    assert r.headers["X-Auth-Request-Email"] == "some-user@example.com"

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            r = client.get(
                "/auth?capability=exec:admin",
                headers={
                    "Authorization": "Basic blah",
                    "X-Forwarded-Ticket-Id-Token": token,
                },
            )

    assert r.status_code == 200
    assert r.headers["X-Auth-Request-Email"] == "some-user@example.com"


def test_authnz_token_basic() -> None:
    keypair = RSAKeyPair()
    token = create_test_token(keypair, ["admin"])
    app = create_test_app(keypair)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            basic = f"{token}:x-oauth-basic".encode()
            basic_b64 = base64.b64encode(basic).decode()
            r = client.get(
                "/auth?capability=exec:admin",
                headers={"Authorization": f"Basic {basic_b64}"},
            )

    assert r.status_code == 200
    assert r.headers["X-Auth-Request-Email"] == "some-user@example.com"

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            basic = f"x-oauth-basic:{token}".encode()
            basic_b64 = base64.b64encode(basic).decode()
            r = client.get(
                "/auth?capability=exec:admin",
                headers={"Authorization": f"Basic {basic_b64}"},
            )

    assert r.status_code == 200
    assert r.headers["X-Auth-Request-Email"] == "some-user@example.com"


def test_authnz_token_reissue(redis_client: redis.Redis) -> None:
    """Test that an upstream token is reissued properly."""
    keypair = RSAKeyPair()
    ticket = Ticket()
    ticket_handle = ticket.encode("oauth2_proxy")
    ticket_b64 = base64.urlsafe_b64encode(ticket_handle.encode()).decode()
    cookie = f"{ticket_b64}|32132781|blahblah"
    token = create_test_token(
        keypair,
        ["admin"],
        kid="orig-kid",
        aud="https://test.example.com/",
        iss="https://orig.example.com/",
        jti=ticket.as_handle("oauth2_proxy"),
    )
    session_secret = os.urandom(16)
    app = create_test_app(keypair, session_secret)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            client.set_cookie("localhost", "oauth2_proxy", cookie)
            r = client.get(
                "/auth?capability=exec:admin",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert get_key_as_pem.call_args_list == [
                call("https://orig.example.com/", "orig-kid")
            ]

    assert r.status_code == 200
    assert r.headers["X-Auth-Request-Token-Ticket"] == ticket_handle
    new_token = r.headers["X-Auth-Request-Token"]
    assert token != new_token

    assert jwt.get_unverified_header(new_token) == {
        "alg": config.ALGORITHM,
        "typ": "JWT",
        "kid": "some-kid",
    }

    decoded_token = jwt.decode(
        new_token,
        keypair.public_key_as_pem(),
        algorithms=config.ALGORITHM,
        audience="https://example.com/",
    )
    assert decoded_token == {
        "act": {
            "aud": "https://test.example.com/",
            "iss": "https://orig.example.com/",
            "jti": ticket.as_handle("oauth2_proxy"),
        },
        "aud": "https://example.com/",
        "email": "some-user@example.com",
        "exp": ANY,
        "iat": ANY,
        "isMemberOf": [{"name": "admin"}],
        "iss": "https://test.example.com/",
        "jti": ticket.as_handle("oauth2_proxy"),
        "scope": "exec:admin read:all",
        "sub": "some-user",
        "uid": "some-user",
        "uidNumber": "1000",
    }
    now = time.time()
    expected_exp = now + app.config["OAUTH2_JWT_EXP"] * 60
    assert expected_exp - 5 <= decoded_token["exp"] <= expected_exp + 5
    assert now - 5 <= decoded_token["iat"] <= now + 5

    session_store = SessionStore("oauth2_proxy", session_secret, redis_client)
    session = session_store.get_session(ticket)
    assert session
    assert session.token == new_token
    assert session.user == "some-user@example.com"


def test_authnz_token_reissue_internal(redis_client: redis.Redis) -> None:
    """Test requesting token reissuance to an internal audience."""
    keypair = RSAKeyPair()
    token = create_test_token(keypair, ["admin"])
    session_secret = os.urandom(16)
    app = create_test_app(keypair, session_secret)

    with app.test_client() as client:
        with patch("jwt_authorizer.authnz.get_key_as_pem") as get_key_as_pem:
            get_key_as_pem.return_value = keypair.public_key_as_pem()
            r = client.get(
                "/auth?capability=exec:admin&audience=https://example.com/api",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert get_key_as_pem.call_args_list == [
                call("https://test.example.com/", "some-kid")
            ]

    assert r.status_code == 200
    new_token = r.headers["X-Auth-Request-Token"]
    assert token != new_token
    ticket = Ticket.from_str(
        "oauth2_proxy", r.headers["X-Auth-Request-Token-Ticket"]
    )

    assert jwt.get_unverified_header(new_token) == {
        "alg": config.ALGORITHM,
        "typ": "JWT",
        "kid": "some-kid",
    }

    decoded_token = jwt.decode(
        new_token,
        keypair.public_key_as_pem(),
        algorithms=config.ALGORITHM,
        audience="https://example.com/api",
    )
    assert decoded_token == {
        "act": {
            "aud": "https://example.com/",
            "iss": "https://test.example.com/",
            "jti": "some-unique-id",
        },
        "aud": "https://example.com/api",
        "email": "some-user@example.com",
        "exp": ANY,
        "iat": ANY,
        "isMemberOf": [{"name": "admin"}],
        "iss": "https://test.example.com/",
        "jti": ticket.as_handle("oauth2_proxy"),
        "sub": "some-user",
        "uid": "some-user",
        "uidNumber": "1000",
    }
    now = time.time()
    expected_exp = now + app.config["OAUTH2_JWT_EXP"] * 60
    assert expected_exp - 5 <= decoded_token["exp"] <= expected_exp + 5
    assert now - 5 <= decoded_token["iat"] <= now + 5

    session_store = SessionStore("oauth2_proxy", session_secret, redis_client)
    session = session_store.get_session(ticket)
    assert session
    assert session.token == new_token
    assert session.user == "some-user@example.com"
