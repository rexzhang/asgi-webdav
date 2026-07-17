import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import asgi_webdav.auth as auth_module
from asgi_webdav.auth import DAVAuth, DAVPassword, DAVPasswordType, HTTPOIDCAuth
from asgi_webdav.config import generate_config_from_dict
from asgi_webdav.exceptions import (
    DAVExceptionAuthFailed,
    DAVExceptionConfig,
    DAVExceptionProviderInitFailed,
)

from .testkit_asgi import create_dav_request_object

OIDC_PASSWORD = (
    "<oidc>#1"
    "#https://idp.example.com/realms/PIC"
    "#https://idp.example.com/realms/PIC/protocol/openid-connect/certs"
    "#account"
    "#cosmohub-test"
    "#RS256"
    "#openid"
)

ISSUER = "https://idp.example.com/realms/PIC"
AUDIENCE = "account"
CLIENT_ID = "cosmohub-test"


@pytest.fixture
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _make_token(private_key, **overrides) -> str:
    payload = {
        "preferred_username": "bob",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "azp": CLIENT_ID,
        "typ": "Bearer",
        "scope": "openid profile",
        "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    return jwt.encode(payload, private_key, algorithm="RS256")


def _build_oidc_dav_auth(rsa_keys, account_mapping):
    private_key, public_key = rsa_keys
    config = generate_config_from_dict(
        {
            "account_mapping": account_mapping,
            "provider_mapping": [{"prefix": "/", "uri": "memory:///"}],
        },
        complete_config=True,
    )
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        mock_client = MagicMock()
        mock_client.get_jwk_set = MagicMock()
        mock_client.get_signing_key_from_jwt = MagicMock(
            return_value=SimpleNamespace(key=public_key)
        )
        mock_pjwk.return_value = mock_client
        dav_auth = DAVAuth(config)
    return dav_auth


@pytest.fixture
def oidc_dav_auth(rsa_keys):
    account_mapping = [
        {"username": "*oidc", "password": OIDC_PASSWORD, "permissions": ["+"]},
        {
            "username": "alice",
            "password": "secret",
            "permissions": ["+^/data/public"],
        },
    ]
    yield _build_oidc_dav_auth(rsa_keys, account_mapping)


def test_dav_password_oidc_parsing():
    pw = DAVPassword(OIDC_PASSWORD)
    assert pw.type == DAVPasswordType.OIDC
    assert len(pw.data) == 8
    assert pw.data[2] == ISSUER
    assert pw.data[3].endswith("/certs")
    assert pw.data[4] == AUDIENCE
    assert pw.data[5] == CLIENT_ID
    assert pw.data[6] == "RS256"
    assert pw.data[7] == "openid"

    # wrong field count -> INVALID (Bearer-only requires the 8-field form)
    bad = DAVPassword("<oidc>#1#issuer#jwks#aud#cid#RS256")
    assert bad.type == DAVPasswordType.INVALID


def test_http_oidc_auth_verify_token_valid(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key)
    payload = oidc_dav_auth.oidc_auth.verify_token(token)
    assert payload["preferred_username"] == "bob"


def test_http_oidc_auth_verify_token_wrong_iss(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, iss="https://evil.example.com")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_wrong_aud(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, aud="other-audience")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_wrong_azp(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, azp="other-client")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_wrong_typ(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, typ="ID")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_missing_scope(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, scope="email")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_expired(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, exp=int(time.time()) - 10)
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


async def test_dav_auth_pick_out_user_bearer_valid_user(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, preferred_username="alice")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await oidc_dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == "alice"
    assert request.authorization_method == "Bearer"


async def test_dav_auth_pick_out_user_bearer_fallback(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    # "bob" is not in account_mapping -> inherits *oidc template permissions
    token = _make_token(private_key, preferred_username="bob")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await oidc_dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == "bob"
    assert request.user.permissions == ["+"]


async def test_dav_auth_pick_out_user_bearer_invalid(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    token = _make_token(private_key, exp=int(time.time()) - 10)
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await oidc_dav_auth.pick_out_user(request)
    assert message == "no permission"


async def test_dav_auth_pick_out_user_bearer_missing_username(rsa_keys, oidc_dav_auth):
    private_key, _ = rsa_keys
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "azp": CLIENT_ID,
        "typ": "Bearer",
        "scope": "openid",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, private_key, algorithm="RS256")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await oidc_dav_auth.pick_out_user(request)
    assert message == "no permission"


async def test_dav_auth_pick_out_user_bearer_not_configured(rsa_keys):
    private_key, _ = rsa_keys
    config = generate_config_from_dict(
        {
            "account_mapping": [
                {"username": "alice", "password": "secret", "permissions": ["+"]}
            ],
            "provider_mapping": [{"prefix": "/", "uri": "memory:///"}],
        },
        complete_config=True,
    )
    dav_auth = DAVAuth(config)
    token = _make_token(private_key, preferred_username="alice")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await dav_auth.pick_out_user(request)
    assert message == "OpenID not available"


async def test_dav_auth_pick_out_user_bearer_invalid_no_anonymous_fallback(rsa_keys):
    private_key, _ = rsa_keys
    config = generate_config_from_dict(
        {
            "account_mapping": [
                {"username": "*oidc", "password": OIDC_PASSWORD, "permissions": ["+"]}
            ],
            "anonymous": {"enable": True},
            "provider_mapping": [{"prefix": "/", "uri": "memory:///"}],
        },
        complete_config=True,
    )
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        mock_client = MagicMock()
        mock_client.get_jwk_set = MagicMock()
        mock_client.get_signing_key_from_jwt = MagicMock(
            return_value=SimpleNamespace(key=rsa_keys[1])
        )
        mock_pjwk.return_value = mock_client
        dav_auth = DAVAuth(config)
    token = _make_token(private_key, exp=int(time.time()) - 10)
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await dav_auth.pick_out_user(request)
    # invalid Bearer must hard-fail (401), never silently degrade to anonymous
    assert message is not None


def test_dav_auth_create_response_401_includes_bearer(oidc_dav_auth):
    request = create_dav_request_object()
    oidc_dav_auth.config.http_digest_auth.enable = False
    oidc_dav_auth.config.http_digest_auth.enable_rule = ""
    response = oidc_dav_auth.create_response_401(request, "msg")
    challenge = response.headers.get(b"WWW-Authenticate")
    assert challenge.startswith(b"Basic")
    assert challenge.endswith(b"Bearer")


def test_http_oidc_auth_init_jwt_not_installed():
    with (
        patch.object(auth_module, "jwt", None),
        patch.object(auth_module, "PyJWKClient", None),
    ):
        with pytest.raises(DAVExceptionConfig, match="install OIDC module"):
            HTTPOIDCAuth(OIDC_PASSWORD.split("#"))


def test_http_oidc_auth_init_unsupported_version():
    bad_password = ("<oidc>#99#issuer#jwks_uri#audience#client_id#RS256#openid").split(
        "#"
    )
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        mock_pjwk.return_value.get_jwk_set = MagicMock()
        with pytest.raises(
            DAVExceptionConfig, match="Unsupported OIDC password version"
        ):
            HTTPOIDCAuth(bad_password)


def test_http_oidc_auth_init_jwks_fetch_failure():
    password_data = OIDC_PASSWORD.split("#")
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        mock_pjwk.return_value.get_jwk_set.side_effect = ConnectionError(
            "network error"
        )
        with pytest.raises(
            DAVExceptionProviderInitFailed, match="Failed to fetch JWKS"
        ):
            HTTPOIDCAuth(password_data)


def test_http_oidc_auth_verify_token_jwt_library_none(rsa_keys, oidc_dav_auth):
    with patch.object(auth_module, "jwt", None):
        with pytest.raises(DAVExceptionAuthFailed):
            oidc_dav_auth.oidc_auth.verify_token("fake.token.value")


async def test_dav_auth_init_oidc_wrong_password_format():
    config = generate_config_from_dict(
        {
            "account_mapping": [
                {
                    "username": "*oidc",
                    "password": "plain-text-password",
                    "permissions": ["+"],
                }
            ],
            "provider_mapping": [{"prefix": "/", "uri": "memory:///"}],
        },
        complete_config=True,
    )
    with pytest.raises(DAVExceptionConfig, match="must use the <oidc> format"):
        DAVAuth(config)


async def test_dav_auth_pick_out_user_bearer_unknown_user_no_fallback(rsa_keys):
    private_key, _ = rsa_keys
    config = generate_config_from_dict(
        {
            "account_mapping": [
                {"username": "alice", "password": "secret", "permissions": ["+"]}
            ],
            "provider_mapping": [{"prefix": "/", "uri": "memory:///"}],
        },
        complete_config=True,
    )
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        mock_client = MagicMock()
        mock_client.get_jwk_set = MagicMock()
        mock_client.get_signing_key_from_jwt = MagicMock(
            return_value=SimpleNamespace(key=rsa_keys[1])
        )
        mock_pjwk.return_value = mock_client
        dav_auth = DAVAuth(config)
        dav_auth.oidc_auth = HTTPOIDCAuth(OIDC_PASSWORD.split("#"))

    token = _make_token(private_key, preferred_username="unknown-user")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await dav_auth.pick_out_user(request)
    assert message == "no permission"
