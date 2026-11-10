import time
from base64 import b64encode
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import asgi_webdav.auth as auth_module
from asgi_webdav.auth import (
    DAVAuth,
    DAVPassword,
    DAVPasswordType,
    HTTPOIDCAuth,
    _md5,
)
from asgi_webdav.config import generate_config_from_dict
from asgi_webdav.exceptions import (
    DAVExceptionAuthFailed,
    DAVExceptionConfig,
    DAVExceptionProviderInitFailed,
)

from .kits.asgi import create_dav_request_object

jwt = pytest.importorskip("jwt", reason="OIDC extra (PyJWT) not installed")
rsa = pytest.importorskip(
    "cryptography.hazmat.primitives.asymmetric.rsa",
    reason="OIDC extra (cryptography) not installed",
)

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
def rsa_keys() -> Any:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _make_token(private_key: Any, **overrides: Any) -> str:
    payload = {
        "preferred_username": "bob",
        "sub": "f1b2c3d4-0000-4000-8000-000000000000",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "azp": CLIENT_ID,
        "typ": "Bearer",
        "scope": "openid profile",
        "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    token: str = jwt.encode(payload, private_key, algorithm="RS256")
    return token


def _build_oidc_dav_auth(rsa_keys: Any, account_mapping: Any) -> Any:
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
def oidc_dav_auth(rsa_keys: Any) -> Any:
    account_mapping = [
        {"username": "*oidc", "password": OIDC_PASSWORD, "permissions": []},
        {
            "username": "alice",
            "password": "secret",
            "permissions": ["+^/data/public"],
        },
    ]
    yield _build_oidc_dav_auth(rsa_keys, account_mapping)


def test_dav_password_oidc_parsing() -> None:
    pw = DAVPassword(OIDC_PASSWORD)
    assert pw.type == DAVPasswordType.OIDC
    assert len(pw.data) == 8
    assert pw.data[2] == ISSUER
    assert pw.data[3].endswith("/certs")
    assert pw.data[4] == AUDIENCE
    assert pw.data[5] == CLIENT_ID
    assert pw.data[6] == "RS256"
    assert pw.data[7] == "openid"

    # wrong field count -> INVALID (requires the 8-field form)
    bad = DAVPassword("<oidc>#1#issuer#jwks#aud#cid#RS256")
    assert bad.type == DAVPasswordType.INVALID

    # the removed 9th group_prefix field is no longer accepted
    legacy = DAVPassword(OIDC_PASSWORD + "#asgi-webdav_")
    assert legacy.type == DAVPasswordType.INVALID


def test_http_oidc_auth_verify_token_valid(rsa_keys: Any, oidc_dav_auth: Any) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key)
    payload = oidc_dav_auth.oidc_auth.verify_token(token)
    assert payload["preferred_username"] == "bob"


def test_http_oidc_auth_verify_token_wrong_iss(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, iss="https://evil.example.com")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_wrong_aud(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, aud="other-audience")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_wrong_azp(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, azp="other-client")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_wrong_typ(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, typ="ID")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_missing_scope(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, scope="email")
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


def test_http_oidc_auth_verify_token_expired(rsa_keys: Any, oidc_dav_auth: Any) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, exp=int(time.time()) - 10)
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


async def test_dav_auth_pick_out_user_bearer_valid_user(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, preferred_username="alice")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await oidc_dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == "alice"
    assert request.authorization_method == "Bearer"


async def test_dav_auth_pick_out_user_bearer_unknown_user_no_template_fallback(
    rsa_keys: Any,
) -> None:
    private_key, _ = rsa_keys
    # even with permissions on *oidc, "bob" (not in account_mapping) is denied
    account_mapping = [
        {"username": "*oidc", "password": OIDC_PASSWORD, "permissions": ["+"]},
    ]
    dav_auth = _build_oidc_dav_auth(rsa_keys, account_mapping)
    token = _make_token(private_key, preferred_username="bob")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await dav_auth.pick_out_user(request)
    assert message == "no permission"
    assert not hasattr(request, "user")


async def test_dav_auth_pick_out_user_bearer_invalid(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, exp=int(time.time()) - 10)
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    message = await oidc_dav_auth.pick_out_user(request)
    assert message == "no permission"


async def test_dav_auth_pick_out_user_bearer_missing_username(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
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


async def test_dav_auth_pick_out_user_bearer_not_configured(rsa_keys: Any) -> None:
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
    # generic message: the 401 must not reveal that OIDC is not configured
    assert message == "no permission"
    assert not hasattr(request, "user")


async def test_dav_auth_pick_out_user_bearer_invalid_no_anonymous_fallback(
    rsa_keys: Any,
) -> None:
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


def test_dav_auth_create_response_401_includes_bearer(oidc_dav_auth: Any) -> None:
    request = create_dav_request_object()
    oidc_dav_auth.config.http_digest_auth.enable = False
    oidc_dav_auth.config.http_digest_auth.enable_rule = ""
    response = oidc_dav_auth.create_response_401(request, "msg")
    challenge = response.headers.get(b"WWW-Authenticate")
    assert challenge.startswith(b"Basic")
    assert challenge.endswith(b"Bearer")


def test_http_oidc_auth_init_jwt_not_installed() -> None:
    with (
        patch.object(auth_module, "jwt", None),
        patch.object(auth_module, "PyJWKClient", None),
    ):
        with pytest.raises(DAVExceptionConfig, match="install OIDC module"):
            HTTPOIDCAuth(OIDC_PASSWORD.split("#"))


def test_http_oidc_auth_init_unsupported_version() -> None:
    bad_password = ("<oidc>#99#issuer#jwks_uri#audience#client_id#RS256#openid").split(
        "#"
    )
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        mock_pjwk.return_value.get_jwk_set = MagicMock()
        with pytest.raises(
            DAVExceptionConfig, match="Unsupported OIDC password version"
        ):
            HTTPOIDCAuth(bad_password)


def test_http_oidc_auth_init_jwks_fetch_failure() -> None:
    password_data = OIDC_PASSWORD.split("#")
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        mock_pjwk.return_value.get_jwk_set.side_effect = ConnectionError(
            "network error"
        )
        with pytest.raises(
            DAVExceptionProviderInitFailed, match="Failed to fetch JWKS"
        ):
            HTTPOIDCAuth(password_data)


def test_http_oidc_auth_verify_token_jwt_library_none(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    with patch.object(auth_module, "jwt", None):
        with pytest.raises(DAVExceptionAuthFailed):
            oidc_dav_auth.oidc_auth.verify_token("fake.token.value")


async def test_dav_auth_init_oidc_wrong_password_format() -> None:
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


async def test_dav_auth_pick_out_user_bearer_unknown_user_no_fallback(
    rsa_keys: Any,
) -> None:
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


# --- Keycloak groups are irrelevant to OIDC auth and permissions ---
# Any Keycloak user can authenticate, whatever its group membership. The token's
# groups claim is never read: permissions only come from the configured account
# matching preferred_username, and unknown users are always denied.

_NO_GROUPS_CLAIM = object()

GROUPS_CLAIMS: list[Any] = [
    _NO_GROUPS_CLAIM,  # group membership is not required
    [],
    ["webdav-users", "vpn-users"],  # ordinary Keycloak groups
    ["asgi-webdav_+^/data/transfer", "asgi-webdav_+"],  # old prefix mechanism
    ["+", "+^/", "-^/data/public"],  # values that look like permissions
    # malformed values must not cause errors either
    ["asgi-webdav_"],
    ["asgi-webdav_admins"],
    [""],
    ["asgi-webdav_+[unclosed"],
    [None, 123, {"a": 1}, ["nested"]],
    "asgi-webdav_+",
    {"asgi-webdav_+": True},
    123,
    None,
]


def _make_token_with_groups(private_key: Any, username: str, groups: Any) -> str:
    if groups is _NO_GROUPS_CLAIM:
        return _make_token(private_key, preferred_username=username)
    return _make_token(private_key, preferred_username=username, groups=groups)


@pytest.mark.parametrize("groups", GROUPS_CLAIMS)
async def test_dav_auth_pick_out_user_bearer_groups_ignored_configured_user(
    rsa_keys: Any, oidc_dav_auth: Any, groups: Any
) -> None:
    """Configured user: authenticated, permissions from the account only."""
    private_key, _ = rsa_keys
    token = _make_token_with_groups(private_key, "alice", groups)
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    assert await oidc_dav_auth.pick_out_user(request) is None
    assert request.user.username == "alice"
    assert request.user.permissions == ["+^/data/public"]
    assert request.user.admin is False


@pytest.mark.parametrize("groups", GROUPS_CLAIMS)
async def test_dav_auth_pick_out_user_bearer_groups_ignored_unknown_user(
    rsa_keys: Any, groups: Any
) -> None:
    """Unknown user: denied, neither groups nor *oidc permissions are a fallback."""
    private_key, _ = rsa_keys
    account_mapping = [
        {"username": "*oidc", "password": OIDC_PASSWORD, "permissions": ["+"]},
    ]
    dav_auth = _build_oidc_dav_auth(rsa_keys, account_mapping)
    token = _make_token_with_groups(private_key, "mallory", groups)
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    assert await dav_auth.pick_out_user(request) == "no permission"
    assert not hasattr(request, "user")


# --- Dedicated HDFS accounts ("group-like" access) use Basic auth ---

HDFS_ACCOUNT = "grp-transfer"
HDFS_ACCOUNT_PASSWORD = "password"
# <hashlib>:sha256:salt:sha256("salt:password")
HDFS_ACCOUNT_HASHLIB = "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"


def _basic_header(username: str, password: str) -> dict[str, str]:
    credential = b64encode(f"{username}:{password}".encode()).decode()
    return {"authorization": f"Basic {credential}"}


@pytest.mark.parametrize("password", [HDFS_ACCOUNT_PASSWORD, HDFS_ACCOUNT_HASHLIB])
async def test_dav_auth_basic_dedicated_hdfs_account_with_oidc_enabled(
    rsa_keys: Any, password: str
) -> None:
    """Basic auth for dedicated accounts keeps working next to OIDC Bearer auth."""
    private_key, _ = rsa_keys
    account_mapping = [
        {"username": "*oidc", "password": OIDC_PASSWORD, "permissions": []},
        {
            "username": "alice",
            "password": "alice-secret",
            "permissions": ["+^/data/public"],
        },
        {
            "username": HDFS_ACCOUNT,
            "password": password,
            "permissions": ["+^/data/transfer"],
        },
    ]
    dav_auth = _build_oidc_dav_auth(rsa_keys, account_mapping)

    request = create_dav_request_object(
        headers=_basic_header(HDFS_ACCOUNT, HDFS_ACCOUNT_PASSWORD)
    )
    assert await dav_auth.pick_out_user(request) is None
    assert request.authorization_method == "Basic"
    assert request.user.username == HDFS_ACCOUNT
    assert request.user.permissions == ["+^/data/transfer"]

    request = create_dav_request_object(
        headers=_basic_header(HDFS_ACCOUNT, "bad-password")
    )
    assert await dav_auth.pick_out_user(request) == "no permission"

    # an OIDC user in the same server still gets only its own account
    token = _make_token(
        private_key,
        preferred_username="alice",
        groups=[HDFS_ACCOUNT, "asgi-webdav_+^/data/transfer"],
    )
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    assert await dav_auth.pick_out_user(request) is None
    assert request.user.username == "alice"
    assert request.user.permissions == ["+^/data/public"]


# --- Regression: Digest auth against the *oidc sentinel ---


@pytest.mark.parametrize("qop", ["", "auth"])
async def test_dav_auth_digest_oidc_sentinel_rejected(
    oidc_dav_auth: Any, qop: str
) -> None:
    """The *oidc password yields an empty HA1; Digest must not accept it."""
    nonce, uri = "any-nonce", "/"
    ha2 = _md5(f"GET:{uri}")
    header = (
        f'Digest username="*oidc", realm="{oidc_dav_auth.realm}",'
        f' nonce="{nonce}", uri="{uri}"'
    )
    if qop:
        response = _md5(f":{nonce}:00000001:cnonce:auth:{ha2}")
        header += f', qop=auth, nc=00000001, cnonce="cnonce", response="{response}"'
    else:
        header += f', response="{_md5(f":{nonce}:{ha2}")}"'

    request = create_dav_request_object(headers={"authorization": header})
    assert await oidc_dav_auth.pick_out_user(request) == "no permission"


async def test_dav_auth_basic_oidc_sentinel_rejected(oidc_dav_auth: Any) -> None:
    import base64

    for password in ("", OIDC_PASSWORD, "anything"):
        credential = base64.b64encode(f"*oidc:{password}".encode()).decode()
        request = create_dav_request_object(
            headers={"authorization": f"Basic {credential}"}
        )
        assert await oidc_dav_auth.pick_out_user(request) == "no permission"


# --- Regression: required claims (exp, iss, aud, sub) ---


@pytest.mark.parametrize("claim", ["exp", "iss", "aud", "sub"])
def test_http_oidc_auth_verify_token_missing_required_claim(
    rsa_keys: Any, oidc_dav_auth: Any, claim: str
) -> None:
    private_key, _ = rsa_keys
    payload = jwt.decode(_make_token(private_key), options={"verify_signature": False})
    del payload[claim]
    token = jwt.encode(payload, private_key, algorithm="RS256")
    with pytest.raises(DAVExceptionAuthFailed, match="MissingRequiredClaimError"):
        oidc_dav_auth.oidc_auth.verify_token(token)


async def test_dav_auth_pick_out_user_bearer_signed_token_without_exp(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    """A correctly signed token with no exp must not authenticate (never expires)."""
    private_key, _ = rsa_keys
    payload = jwt.decode(
        _make_token(private_key, preferred_username="alice"),
        options={"verify_signature": False},
    )
    del payload["exp"]
    token = jwt.encode(payload, private_key, algorithm="RS256")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    assert await oidc_dav_auth.pick_out_user(request) == "no permission"


def test_http_oidc_auth_verify_token_wrong_signature(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_token(other_key)
    with pytest.raises(DAVExceptionAuthFailed):
        oidc_dav_auth.oidc_auth.verify_token(token)


# --- Regression: malformed claims never cause HTTP 500 ---


@pytest.mark.parametrize(
    "preferred_username", [["alice"], {"u": "alice"}, 123, True, "", None]
)
async def test_dav_auth_pick_out_user_bearer_malformed_preferred_username(
    rsa_keys: Any, oidc_dav_auth: Any, caplog: Any, preferred_username: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, preferred_username=preferred_username)
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    with caplog.at_level("WARNING", logger="asgi_webdav.auth"):
        assert await oidc_dav_auth.pick_out_user(request) == "no permission"
    assert "preferred_username" in caplog.text
    assert token not in caplog.text


@pytest.mark.parametrize("preferred_username", ["*oidc", "*ldap"])
async def test_dav_auth_pick_out_user_bearer_sentinel_username_rejected(
    rsa_keys: Any, preferred_username: str
) -> None:
    private_key, _ = rsa_keys
    account_mapping = [
        {"username": "*oidc", "password": OIDC_PASSWORD, "permissions": ["+"]},
        {
            "username": "*ldap",
            "password": "<ldap>#2#ldaps://ldap.example.com#cert_policy=try"
            "#uid={username},dc=example,dc=com",
            "permissions": ["+"],
        },
    ]
    dav_auth = _build_oidc_dav_auth(rsa_keys, account_mapping)
    token = _make_token(private_key, preferred_username=preferred_username)
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    assert await dav_auth.pick_out_user(request) == "no permission"


@pytest.mark.parametrize("scope", [123, ["openid"], {"openid": True}, None])
def test_http_oidc_auth_verify_token_malformed_scope(
    rsa_keys: Any, oidc_dav_auth: Any, scope: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, scope=scope)
    with pytest.raises(DAVExceptionAuthFailed, match="scope"):
        oidc_dav_auth.oidc_auth.verify_token(token)


async def test_dav_auth_pick_out_user_bearer_malformed_scope(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    private_key, _ = rsa_keys
    token = _make_token(private_key, preferred_username="alice", scope=["openid"])
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    assert await oidc_dav_auth.pick_out_user(request) == "no permission"


# --- Regression: malformed Bearer header encoding ---


@pytest.mark.parametrize(
    "header",
    [
        b"Bearer \xff\xfe",
        b"Bearer caf\xc3\xa9.x.y",  # valid UTF-8, but not a JWT (non-ASCII)
        b"Bearer ",
        b"Bearer not-a-jwt",
        b"Bearer a.b.c",
    ],
)
async def test_dav_auth_pick_out_user_bearer_malformed_header(
    oidc_dav_auth: Any, caplog: Any, header: bytes
) -> None:
    request = create_dav_request_object(headers=[(b"authorization", header)])
    with caplog.at_level("DEBUG", logger="asgi_webdav.auth"):
        assert await oidc_dav_auth.pick_out_user(request) == "no permission"
    assert "Bearer auth rejected" in caplog.text
    assert "\\xff" not in caplog.text


# --- Regression: JWKS retrieval runs off the event loop ---


async def test_dav_auth_pick_out_user_bearer_verifies_off_event_loop(
    rsa_keys: Any, oidc_dav_auth: Any
) -> None:
    import threading

    loop_thread = threading.get_ident()
    verify_threads: list[int] = []
    original = oidc_dav_auth.oidc_auth._jwks_client.get_signing_key_from_jwt

    def record_thread(token: str) -> Any:
        verify_threads.append(threading.get_ident())
        return original(token)

    oidc_dav_auth.oidc_auth._jwks_client.get_signing_key_from_jwt = record_thread

    private_key, _ = rsa_keys
    token = _make_token(private_key, preferred_username="alice")
    request = create_dav_request_object(headers={"authorization": f"Bearer {token}"})
    assert await oidc_dav_auth.pick_out_user(request) is None
    assert verify_threads and verify_threads[0] != loop_thread


def test_http_oidc_auth_jwks_client_timeouts() -> None:
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        HTTPOIDCAuth(OIDC_PASSWORD.split("#"))
    mock_pjwk.assert_called_once_with(
        "https://idp.example.com/realms/PIC/protocol/openid-connect/certs",
        lifespan=HTTPOIDCAuth.JWKS_CACHE_LIFESPAN,
        timeout=HTTPOIDCAuth.JWKS_FETCH_TIMEOUT,
    )


# --- Regression: config validation at startup ---


def _oidc_password(**fields: str) -> list[str]:
    values = {
        "issuer": ISSUER,
        "jwks_uri": "https://idp.example.com/certs",
        "audience": AUDIENCE,
        "client_id": CLIENT_ID,
        "algorithm": "RS256",
        "scope": "openid",
    }
    values.update(fields)
    return ["<oidc>", "1", *values.values()]


@pytest.mark.parametrize(
    "fields, match",
    [
        ({"algorithm": "HS256"}, "Unsupported OIDC algorithm"),
        ({"algorithm": "none"}, "Unsupported OIDC algorithm"),
        ({"algorithm": ""}, "Unsupported OIDC algorithm"),
        ({"algorithm": "rs256"}, "Unsupported OIDC algorithm"),
        ({"issuer": ""}, "Invalid OIDC issuer"),
        ({"issuer": "idp.example.com"}, "Invalid OIDC issuer"),
        ({"issuer": "ftp://idp.example.com"}, "Invalid OIDC issuer"),
        ({"jwks_uri": "file:///etc/passwd"}, "Invalid OIDC jwks_uri"),
        ({"jwks_uri": "https://"}, "Invalid OIDC jwks_uri"),
        ({"audience": ""}, "OIDC audience must not be empty"),
        ({"client_id": " "}, "OIDC client_id must not be empty"),
        ({"scope": ""}, "OIDC scope must not be empty"),
    ],
)
def test_http_oidc_auth_init_invalid_config(fields: dict[str, str], match: str) -> None:
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        with pytest.raises(DAVExceptionConfig, match=match):
            HTTPOIDCAuth(_oidc_password(**fields))
    # rejected before any network access
    mock_pjwk.assert_not_called()


@pytest.mark.parametrize("algorithm", HTTPOIDCAuth.ALLOWED_ALGORITHMS)
def test_http_oidc_auth_init_allowed_algorithms(algorithm: str) -> None:
    with patch.object(auth_module, "PyJWKClient"):
        assert HTTPOIDCAuth(_oidc_password(algorithm=algorithm)).algorithm == algorithm


def test_http_oidc_auth_init_http_allowed_with_warning(caplog: Any) -> None:
    """Plain HTTP stays usable for local development, but is flagged."""
    with patch.object(auth_module, "PyJWKClient"):
        with caplog.at_level("WARNING", logger="asgi_webdav.auth"):
            oidc = HTTPOIDCAuth(
                _oidc_password(
                    issuer="http://localhost:8080/realms/dev",
                    jwks_uri="http://localhost:8080/realms/dev/certs",
                )
            )
    assert oidc.issuer == "http://localhost:8080/realms/dev"
    assert "OIDC issuer uses plain HTTP" in caplog.text
    assert "OIDC jwks_uri uses plain HTTP" in caplog.text


def test_http_oidc_auth_init_https_no_warning(caplog: Any) -> None:
    with patch.object(auth_module, "PyJWKClient"):
        with caplog.at_level("WARNING", logger="asgi_webdav.auth"):
            HTTPOIDCAuth(_oidc_password())
    assert "plain HTTP" not in caplog.text


def _dav_auth_config(oidc_account: dict[str, Any]) -> Any:
    return generate_config_from_dict(
        {
            "account_mapping": [oidc_account],
            "provider_mapping": [{"prefix": "/", "uri": "memory:///"}],
        },
        complete_config=True,
    )


@pytest.mark.parametrize(
    "password",
    [
        OIDC_PASSWORD + "#asgi-webdav_",  # removed group_prefix field
        OIDC_PASSWORD.replace("/certs", "/certs#fragment"),  # '#' inside a URL
    ],
)
def test_dav_auth_init_oidc_password_field_count(password: str) -> None:
    config = _dav_auth_config(
        {"username": "*oidc", "password": password, "permissions": []}
    )
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        with pytest.raises(DAVExceptionConfig, match="must use the <oidc> format"):
            DAVAuth(config)
    mock_pjwk.assert_not_called()


def test_dav_auth_init_oidc_sentinel_admin_rejected() -> None:
    config = _dav_auth_config(
        {
            "username": "*oidc",
            "password": OIDC_PASSWORD,
            "permissions": [],
            "admin": True,
        }
    )
    with patch.object(auth_module, "PyJWKClient") as mock_pjwk:
        with pytest.raises(
            DAVExceptionConfig, match="The \\*oidc user must not be admin"
        ):
            DAVAuth(config)
    mock_pjwk.assert_not_called()


def test_dav_app_init_oidc_sentinel_admin_rejected() -> None:
    """The server refuses to start: DAVApp builds DAVAuth at startup."""
    from asgi_webdav.server import DAVApp

    config = _dav_auth_config(
        {
            "username": "*oidc",
            "password": OIDC_PASSWORD,
            "permissions": [],
            "admin": True,
        }
    )
    with pytest.raises(DAVExceptionConfig, match="must not be admin"):
        DAVApp(config)


def test_dav_auth_init_oidc_sentinel_permissions_ignored(
    rsa_keys: Any, caplog: Any
) -> None:
    with caplog.at_level("WARNING", logger="asgi_webdav.auth"):
        _build_oidc_dav_auth(
            rsa_keys,
            [{"username": "*oidc", "password": OIDC_PASSWORD, "permissions": ["+"]}],
        )
    assert "permissions of the *oidc user are ignored" in caplog.text
