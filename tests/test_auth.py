import hashlib
import re
from base64 import b64encode
from copy import deepcopy

import pytest
from icecream import ic

from asgi_webdav.auth import DAVAuth, DAVPassword, DAVPasswordType, HTTPDigestAuth
from asgi_webdav.cache import DAVCacheType
from asgi_webdav.config import Config, generate_config_from_dict
from asgi_webdav.constants import DAVPath, DAVUser
from asgi_webdav.request import DAVRequest

from .kits.asgi import (
    ASGITestClient,
    create_dav_request_object,
    get_webdav_app,
    parse_digest_challenge,
)

USERNAME = "username"
PASSWORD = "password"
USERNAME_HASHLIB = "user-hashlib"
PASSWORD_HASHLIB = "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"
USERNAME_DIGEST = "user-digest"
PASSWORD_DIGEST = "<digest>:ASGI-WebDAV:c1d34f1e0f457c4de05b7468d5165567"
USERNAME_ANONYMOUS_USER = "anonymous"
PASSWORD_ANONYMOUS_USER = ""

INVALID_PASSWORD_FORMAT_USER_1 = "invalid-user-1"
INVALID_PASSWORD_FORMAT_USER_2 = "invalid-user-2"
INVALID_PASSWORD_FORMAT_1 = "<invalid>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"
INVALID_PASSWORD_FORMAT_2 = "<hashlib>::sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"

BASIC_AUTHORIZATION = "Basic " + b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
BASIC_AUTHORIZATION_ANONYMOUS = (
    "Basic "
    + b64encode(
        f"{USERNAME_ANONYMOUS_USER}:{PASSWORD_ANONYMOUS_USER}".encode()
    ).decode()
)
BASIC_AUTHORIZATION_BAD_1 = "Basic bad basic_authorization"
BASIC_AUTHORIZATION_BAD_2 = "Basic " + b64encode(b"username-password").decode()
BASIC_AUTHORIZATION_BAD_3 = "BasicAAAAA"
BASIC_AUTHORIZATION_CONFIG_DATA = {
    "account_mapping": [
        {"username": USERNAME, "password": PASSWORD, "permissions": ["+^/$"]},
        {
            "username": INVALID_PASSWORD_FORMAT_USER_1,
            "password": INVALID_PASSWORD_FORMAT_1,
            "permissions": ["+^/$"],
        },
        {
            "username": INVALID_PASSWORD_FORMAT_USER_2,
            "password": INVALID_PASSWORD_FORMAT_2,
            "permissions": ["+^/$"],
        },
        {
            "username": USERNAME_HASHLIB,
            "password": PASSWORD_HASHLIB,
            "permissions": ["+^/$"],
        },
        {
            "username": USERNAME_DIGEST,
            "password": PASSWORD_DIGEST,
            "permissions": ["+^/$"],
        },
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}


BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER = {
    "anonymous": {
        "enable": True,
        "user": {
            "username": USERNAME_ANONYMOUS_USER,
            "password": PASSWORD_ANONYMOUS_USER,
            "permissions": ["+^/$"],
        },
    },
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}
BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_DEFAULT = {
    "anonymous": {
        "enable": True,
    },
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}
BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_DISABLE = {
    "anonymous": {
        "enable": False,
    },
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}
BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_ALLOW_MISSING_AUTH_HEADER_FALSE = {
    "anonymous": {
        "enable": True,
        "allow_missing_auth_header": False,
    },
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}


def test_dev_password_class():
    pw_obj = DAVPassword("password")
    assert pw_obj.type == DAVPasswordType.RAW

    # invalid format in Config
    pw_obj = DAVPassword(INVALID_PASSWORD_FORMAT_1)
    assert pw_obj.type == DAVPasswordType.INVALID

    pw_obj = DAVPassword(INVALID_PASSWORD_FORMAT_2)
    assert pw_obj.type == DAVPasswordType.INVALID

    # hashlib
    pw_obj = DAVPassword(
        "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"
    )
    assert pw_obj.type == DAVPasswordType.HASHLIB

    valid, message = pw_obj.check_hashlib_password("password")
    assert valid

    valid, message = pw_obj.check_hashlib_password("bad-password")
    assert not valid

    pw_obj = DAVPassword(
        "<hashlib>:sha256-bad:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"
    )
    valid, message = pw_obj.check_hashlib_password("password")
    assert not valid

    # digest
    pw_obj = DAVPassword("<digest>:ASGI-WebDAV:f73de4cba3dd4ea2acb0228b90f3f4f9")
    assert pw_obj.type == DAVPasswordType.DIGEST

    valid, message = pw_obj.check_digest_password("username", "password")
    assert valid

    valid, message = pw_obj.check_digest_password("username", "bad-password")
    assert not valid

    # ldap
    pw_obj = DAVPassword(
        "<ldap>#1#ldaps://rexzhang.myds.me#SIMPLE#"
        "uid=user-ldap,cn=users,dc=rexzhang,dc=myds,dc=me"
    )
    assert pw_obj.type == DAVPasswordType.LDAP

    # ldap fallback
    pw_obj = DAVPassword(
        "<ldap>#2#ldaps://your.domain.com#cert_policy=try#uid={username},cn=users,dc=domain,dc=tld"
    )
    assert pw_obj.type == DAVPasswordType.LDAP


async def _test_basic_authentication_basic(config_object):
    client = ASGITestClient(get_webdav_app(config_object=config_object))

    headers = {}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {b"authorization": BASIC_AUTHORIZATION_BAD_1.encode("utf-8")}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {b"authorization": BASIC_AUTHORIZATION_BAD_2.encode("utf-8")}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {b"authorization": BASIC_AUTHORIZATION_BAD_3.encode("utf-8")}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    response = await client.get(
        "/",
        headers=client.create_basic_authorization_headers(
            INVALID_PASSWORD_FORMAT_USER_1, PASSWORD
        ),
    )
    assert response.status_code == 401

    response = await client.get(
        "/",
        headers=client.create_basic_authorization_headers(
            INVALID_PASSWORD_FORMAT_USER_2, PASSWORD
        ),
    )
    assert response.status_code == 401

    response = await client.get(
        "/", headers=client.create_basic_authorization_headers("missed-user", PASSWORD)
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_basic_authentication_basic():
    config_obj_cache_memory = BASIC_AUTHORIZATION_CONFIG_DATA
    config_obj_cache_bypass = deepcopy(BASIC_AUTHORIZATION_CONFIG_DATA)
    config_obj_cache_bypass.update({"http_basic_auth": {"cache_type": "bypass"}})

    for config_object, cache_type in [
        [config_obj_cache_bypass, DAVCacheType.BYPASS],
        [config_obj_cache_memory, DAVCacheType.MEMORY],
    ]:
        print(cache_type)
        await _test_basic_authentication_basic(config_object)


@pytest.mark.asyncio
async def test_basic_authentication_raw():
    client = ASGITestClient(
        get_webdav_app(config_object=BASIC_AUTHORIZATION_CONFIG_DATA)
    )

    response = await client.get(
        "/", headers=client.create_basic_authorization_headers(USERNAME, PASSWORD)
    )
    assert response.status_code == 200

    response = await client.get(
        "/", headers=client.create_basic_authorization_headers(USERNAME, "bad-password")
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_basic_authentication_hashlib():
    client = ASGITestClient(
        get_webdav_app(config_object=BASIC_AUTHORIZATION_CONFIG_DATA)
    )

    response = await client.get(
        "/",
        headers=client.create_basic_authorization_headers(USERNAME_HASHLIB, PASSWORD),
    )
    assert response.status_code == 200

    response = await client.get(
        "/",
        headers=client.create_basic_authorization_headers(
            USERNAME_HASHLIB, "bad-password"
        ),
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_basic_authentication_digest():
    client = ASGITestClient(
        get_webdav_app(config_object=BASIC_AUTHORIZATION_CONFIG_DATA)
    )

    response = await client.get(
        "/",
        headers=client.create_basic_authorization_headers(USERNAME_DIGEST, PASSWORD),
    )
    assert response.status_code == 200

    response = await client.get(
        "/",
        headers=client.create_basic_authorization_headers(
            USERNAME_DIGEST, "bad-password"
        ),
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_basic_authentication_anonymous_user():
    # anonymous user, default enable
    client = ASGITestClient(
        get_webdav_app(config_object=BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER)
    )

    response = await client.get(
        "/", headers={b"authorization": BASIC_AUTHORIZATION_ANONYMOUS.encode("utf-8")}
    )
    assert response.status_code == 200

    response = await client.get(
        "/",
    )
    assert response.status_code == 200

    response = await client.get(
        "/no_permission",
        headers={b"authorization": BASIC_AUTHORIZATION_ANONYMOUS.encode("utf-8")},
    )
    assert response.status_code == 401

    response = await client.get(
        "/no_permission",
    )
    assert response.status_code == 401

    # anonymous user, disable allow_missing_auth_header
    client = ASGITestClient(
        get_webdav_app(
            config_object=BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_ALLOW_MISSING_AUTH_HEADER_FALSE
        )
    )
    response = await client.get(
        "/", headers={b"authorization": BASIC_AUTHORIZATION_ANONYMOUS.encode("utf-8")}
    )
    assert response.status_code == 200

    response = await client.get(
        "/",
    )
    assert response.status_code == 401

    # anonymous user disable
    client = ASGITestClient(
        get_webdav_app(
            config_object=BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_DISABLE
        )
    )

    response = await client.get(
        "/", headers={b"authorization": BASIC_AUTHORIZATION_ANONYMOUS.encode("utf-8")}
    )
    assert response.status_code == 401

    response = await client.get(
        "/",
    )
    assert response.status_code == 401


def test_dav_user_check_paths_permission():
    username = USERNAME
    password = PASSWORD
    admin = False

    # "+"
    permissions = ["+^/aa"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert not dav_user.check_paths_permission([DAVPath("/a")])
    assert dav_user.check_paths_permission([DAVPath("/aa")])
    assert dav_user.check_paths_permission([DAVPath("/aaa")])

    permissions = ["+^/bbb"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert not dav_user.check_paths_permission(
        [DAVPath("/aaa")],
    )

    # "-"
    permissions = ["-^/aaa"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert not dav_user.check_paths_permission(
        [DAVPath("/aaa")],
    )

    # "$"
    permissions = ["+^/a$"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/ab")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/a/b")],
    )

    # multi-rules
    permissions = ["+^/a$", "+^/a/b"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert dav_user.check_paths_permission(
        [DAVPath("/a/b")],
    )

    permissions = ["+^/a$", "+^/a/b", "-^/a/b/c"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert dav_user.check_paths_permission(
        [DAVPath("/a/b")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/a/b/c")],
    )

    permissions = ["+^/a$", "+^/a/b1", "-^/a/b2"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert dav_user.check_paths_permission(
        [DAVPath("/a/b1")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/a/b2")],
    )


def get_dav_request(extra_headers: dict[str, str]) -> DAVRequest:
    headers = {"user-agent": "litmus/0.13 neon/0.31.2"} | extra_headers
    return create_dav_request_object(headers=headers)


@pytest.mark.asyncio
async def test_dav_auth_pick_out_user_anonymous_user():
    # anonymous user : ok
    config = generate_config_from_dict(
        BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_DEFAULT, complete_config=True
    )
    dav_auth = DAVAuth(config)
    ic(config)
    ic(dav_auth.user_mapping)

    # --- anonymous user in auth header
    request = get_dav_request({"authorization": BASIC_AUTHORIZATION_ANONYMOUS})
    message = await dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == USERNAME_ANONYMOUS_USER

    # --- no auth header
    request = get_dav_request({})
    message = await dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == USERNAME_ANONYMOUS_USER

    # --- anonymous user not in auth header
    request = get_dav_request({"authorization": BASIC_AUTHORIZATION})
    message = await dav_auth.pick_out_user(request)
    assert message is not None

    # anonymous user : disable
    config = generate_config_from_dict(
        BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_DISABLE, complete_config=True
    )
    dav_auth = DAVAuth(config)
    ic(config)
    ic(dav_auth.user_mapping)

    # --- anonymous user in auth header
    request = get_dav_request({"authorization": BASIC_AUTHORIZATION_ANONYMOUS})
    message = await dav_auth.pick_out_user(request)
    assert message is not None

    # --- no auth header
    request = get_dav_request({})
    message = await dav_auth.pick_out_user(request)
    assert message is not None

    # anonymous user: allow_missing_auth_header is False
    config = generate_config_from_dict(
        BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_ALLOW_MISSING_AUTH_HEADER_FALSE,
        complete_config=True,
    )
    dav_auth = DAVAuth(config)
    ic(config)
    ic(dav_auth.user_mapping)

    # --- anonymous user in auth header
    request = get_dav_request({"authorization": BASIC_AUTHORIZATION_ANONYMOUS})
    message = await dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == USERNAME_ANONYMOUS_USER

    # --- no auth header
    request = get_dav_request({})
    message = await dav_auth.pick_out_user(request)
    assert message is not None


def test_dav_auth_create_response_401():
    request = get_dav_request({})
    test_response_message = "test response message"
    config = Config()

    # http_digest_auth.enable is True
    config.http_digest_auth.enable = True
    config.http_digest_auth.disable_rule = ""
    dav_auth = DAVAuth(config)
    response = dav_auth.create_response_401(request, test_response_message)
    ic(response)
    assert response.headers.get(b"WWW-Authenticate").startswith(b"Digest")

    config.http_digest_auth.enable = True
    config.http_digest_auth.disable_rule = "no-match"
    dav_auth = DAVAuth(config)
    response = dav_auth.create_response_401(request, test_response_message)
    ic(response)
    assert response.headers.get(b"WWW-Authenticate").startswith(b"Digest")

    config.http_digest_auth.enable = True
    config.http_digest_auth.disable_rule = "neon"
    dav_auth = DAVAuth(config)
    response = dav_auth.create_response_401(request, test_response_message)
    ic(response)
    assert response.headers.get(b"WWW-Authenticate").startswith(b"Basic")

    # http_digest_auth.enable is False
    config.http_digest_auth.enable = False
    config.http_digest_auth.enable_rule = "neon"
    dav_auth = DAVAuth(config)
    response = dav_auth.create_response_401(request, test_response_message)
    ic(response)
    assert response.headers.get(b"WWW-Authenticate").startswith(b"Digest")

    config.http_digest_auth.enable = False
    config.http_digest_auth.enable_rule = "no-match"
    dav_auth = DAVAuth(config)
    response = dav_auth.create_response_401(request, test_response_message)
    ic(response)
    assert response.headers.get(b"WWW-Authenticate").startswith(b"Basic")

    config.http_digest_auth.enable = False
    config.http_digest_auth.enable_rule = ""
    dav_auth = DAVAuth(config)
    response = dav_auth.create_response_401(request, test_response_message)
    ic(response)
    assert response.headers.get(b"WWW-Authenticate").startswith(b"Basic")


DIGEST_AUTHORIZATION_CONFIG_DATA = BASIC_AUTHORIZATION_CONFIG_DATA | {
    "http_digest_auth": {"enable": True}
}
# md5("user-digest:ASGI-WebDAV:password")
DIGEST_HA1_USER_DIGEST = "c1d34f1e0f457c4de05b7468d5165567"


def get_dav_auth_digest() -> DAVAuth:
    config = generate_config_from_dict(
        DIGEST_AUTHORIZATION_CONFIG_DATA, complete_config=True
    )
    return DAVAuth(config)


def get_digest_challenge(dav_auth: DAVAuth) -> str:
    return dav_auth.http_digest_auth.make_auth_challenge_string().decode("utf-8")


def build_ha2(method: str, uri: str) -> str:
    return hashlib.md5(f"{method}:{uri}".encode()).hexdigest()


def test_http_digest_auth_challenge_format():
    challenge = (
        HTTPDigestAuth(realm="ASGI-WebDAV").make_auth_challenge_string().decode("utf-8")
    )
    assert challenge.startswith("Digest ")

    params = parse_digest_challenge(challenge)
    assert params["realm"] == "ASGI-WebDAV"
    assert params["qop"] == "auth"
    assert params["algorithm"] == "MD5"
    assert params["stale"] == "false"
    assert re.fullmatch(r"[0-9a-f]{32}", params["nonce"])
    assert re.fullmatch(r"[0-9A-F]{32}", params["opaque"])

    # RFC 7616 3.3: algorithm and stale MUST be unquoted tokens
    assert "algorithm=MD5" in challenge
    assert 'algorithm="MD5"' not in challenge
    assert "stale=false" in challenge
    assert 'stale="false"' not in challenge


def test_http_digest_auth_authorization_parser():
    parser = HTTPDigestAuth.authorization_str_parser_to_data

    # neon 0.31.x style: algorithm/qop quoted, nc unquoted,
    # comma inside a quoted value
    data = parser(
        'username="u", realm="r", nonce="n", uri="/a,b.txt", '
        'algorithm="MD5", response="abc", opaque="o", '
        'cnonce="c", nc=00000001, qop="auth"'
    )
    assert data["uri"] == "/a,b.txt"
    assert data["algorithm"] == "MD5"
    assert data["qop"] == "auth"
    assert data["nc"] == "00000001"

    # backslash escaped characters inside quoted values
    data = parser('username="a\\"b\\\\c", response="x"')
    assert data["username"] == 'a"b\\c'
    assert data["response"] == "x"

    # RFC strict style: unquoted tokens
    data = parser('username="u", algorithm=MD5, qop=auth, nc=00000002')
    assert data["algorithm"] == "MD5"
    assert data["qop"] == "auth"
    assert data["nc"] == "00000002"

    # malformed segments are skipped without raising
    data = parser(',,,=x,username="u",response="r"')
    assert data == {"username": "u", "response": "r"}


@pytest.mark.asyncio
async def test_dav_auth_pick_out_user_digest_params():
    dav_auth = get_dav_auth_digest()
    challenge = get_digest_challenge(dav_auth)
    nonce = parse_digest_challenge(challenge)["nonce"]

    nc = "00000001"
    cnonce = "0a4f113b"
    ha1 = hashlib.md5(f"{USERNAME}:ASGI-WebDAV:{PASSWORD}".encode()).hexdigest()
    ha2 = build_ha2("GET", "/")
    response = hashlib.md5(
        f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}".encode()
    ).hexdigest()

    # --- minimal params: no algorithm/opaque (RFC 7616 3.4 optional)
    minimal = (
        f'Digest username="{USERNAME}", realm="ASGI-WebDAV", nonce="{nonce}", '
        f'uri="/", response="{response}", cnonce="{cnonce}", nc={nc}, qop=auth'
    )
    request = get_dav_request({"authorization": minimal})
    message = await dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == USERNAME
    assert request.authorization_info

    # --- RFC 2069 legacy style: no qop/nc/cnonce
    response_2069 = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    legacy = (
        f'Digest username="{USERNAME}", realm="ASGI-WebDAV", nonce="{nonce}", '
        f'uri="/", response="{response_2069}"'
    )
    request = get_dav_request({"authorization": legacy})
    message = await dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == USERNAME

    # --- qop=auth but cnonce missing -> rejected
    missing_cnonce = (
        f'Digest username="{USERNAME}", realm="ASGI-WebDAV", nonce="{nonce}", '
        f'uri="/", response="{response}", nc={nc}, qop=auth'
    )
    request = get_dav_request({"authorization": missing_cnonce})
    message = await dav_auth.pick_out_user(request)
    assert message is not None

    # --- unsupported qop value -> rejected
    auth_int = (
        f'Digest username="{USERNAME}", realm="ASGI-WebDAV", nonce="{nonce}", '
        f'uri="/", response="{response}", cnonce="{cnonce}", nc={nc}, qop=auth-int'
    )
    request = get_dav_request({"authorization": auth_int})
    message = await dav_auth.pick_out_user(request)
    assert message is not None

    # --- wrong response -> rejected
    wrong_response = (
        f'Digest username="{USERNAME}", realm="ASGI-WebDAV", nonce="{nonce}", '
        f'uri="/", response="wrong", cnonce="{cnonce}", nc={nc}, qop=auth'
    )
    request = get_dav_request({"authorization": wrong_response})
    message = await dav_auth.pick_out_user(request)
    assert message is not None

    # --- neon-style header against a <digest> stored password account
    headers = ASGITestClient.create_digest_authorization_headers(
        "GET", "/", challenge, USERNAME_DIGEST, ha1=DIGEST_HA1_USER_DIGEST
    )
    request = get_dav_request(headers)
    message = await dav_auth.pick_out_user(request)
    assert message is None
    assert request.user.username == USERNAME_DIGEST


@pytest.mark.asyncio
async def test_dav_auth_digest_authentication_info_rspauth():
    # Regression test for the neon (WinSCP) incompatibility root cause:
    # rspauth MUST be computed from an empty-method HA2 (RFC 7616 3.5.2),
    # exactly as neon's verify_digest_response() verifies it.
    dav_auth = get_dav_auth_digest()
    challenge = get_digest_challenge(dav_auth)
    nonce = parse_digest_challenge(challenge)["nonce"]

    uri = "/file.txt"
    nc = "00000001"
    cnonce = "0a4f113b"
    headers = ASGITestClient.create_digest_authorization_headers(
        "GET", uri, challenge, USERNAME, password=PASSWORD, nc=nc, cnonce=cnonce
    )
    request = get_dav_request(headers)
    message = await dav_auth.pick_out_user(request)
    assert message is None

    # RFC 7616 3.5: qop/nc unquoted, rspauth/cnonce quoted
    auth_info = request.authorization_info.decode("utf-8")
    assert "qop=auth" in auth_info
    assert 'qop="auth"' not in auth_info
    assert f"nc={nc}" in auth_info
    assert f'nc="{nc}"' not in auth_info

    data = HTTPDigestAuth.authorization_str_parser_to_data(auth_info)
    assert data["cnonce"] == cnonce

    ha1 = hashlib.md5(f"{USERNAME}:ASGI-WebDAV:{PASSWORD}".encode()).hexdigest()
    ha2_prime = build_ha2("", uri)
    expected_rspauth = hashlib.md5(
        f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2_prime}".encode()
    ).hexdigest()
    assert data["rspauth"] == expected_rspauth


@pytest.mark.asyncio
async def test_digest_authentication_end_to_end():
    client = ASGITestClient(
        get_webdav_app(config_object=DIGEST_AUTHORIZATION_CONFIG_DATA)
    )

    # no auth -> 401 with a Digest challenge
    response = await client.get("/")
    assert response.status_code == 401
    challenge = response.headers[b"www-authenticate"].decode("utf-8")
    assert challenge.startswith("Digest")

    # neon-style digest auth against a <digest> stored password account
    headers = ASGITestClient.create_digest_authorization_headers(
        "GET", "/", challenge, USERNAME_DIGEST, ha1=DIGEST_HA1_USER_DIGEST
    )
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    auth_info = response.headers[b"authentication-info"].decode("utf-8")
    assert "rspauth=" in auth_info

    # RAW password account
    response = await client.get("/")
    challenge = response.headers[b"www-authenticate"].decode("utf-8")
    headers = ASGITestClient.create_digest_authorization_headers(
        "GET", "/", challenge, USERNAME, password=PASSWORD
    )
    response = await client.get("/", headers=headers)
    assert response.status_code == 200

    # wrong password -> 401
    response = await client.get("/")
    challenge = response.headers[b"www-authenticate"].decode("utf-8")
    headers = ASGITestClient.create_digest_authorization_headers(
        "GET", "/", challenge, USERNAME, password="bad-password"
    )
    response = await client.get("/", headers=headers)
    assert response.status_code == 401
