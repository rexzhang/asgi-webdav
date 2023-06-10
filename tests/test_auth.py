from base64 import b64encode

import pytest
from icecream import ic

from asgi_webdav.auth import DAVAuth, DAVPassword, DAVPasswordType
from asgi_webdav.config import Config
from asgi_webdav.constants import ASGIScope, DAVPath, DAVUser
from asgi_webdav.request import DAVRequest

from .test_webdav_base import ASGITestClient, get_webdav_app

USERNAME = "username"
PASSWORD = "password"
USERNAME_HASHLIB = "user-hashlib"
PASSWORD_HASHLIB = "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"
USERNAME_DIGEST = "user-digest"
PASSWORD_DIGEST = "<digest>:ASGI-WebDAV:c1d34f1e0f457c4de05b7468d5165567"

INVALID_PASSWORD_FORMAT_USER_1 = "invalid-user-1"
INVALID_PASSWORD_FORMAT_USER_2 = "invalid-user-2"
INVALID_PASSWORD_FORMAT_1 = "<invalid>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"
INVALID_PASSWORD_FORMAT_2 = "<hashlib>::sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"

BASIC_AUTHORIZATION = b"Basic " + b64encode(f"{USERNAME}:{PASSWORD}".encode())
BASIC_AUTHORIZATION_BAD_1 = "Basic bad basic_authorization"
BASIC_AUTHORIZATION_BAD_2 = "Basic " + b64encode(b"username-password").decode("utf-8")
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


def fake_call():
    pass


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


@pytest.mark.asyncio
async def test_basic_authentication_basic():
    client = ASGITestClient(
        get_webdav_app(config_object=BASIC_AUTHORIZATION_CONFIG_DATA)
    )

    headers = {}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {"authorization": BASIC_AUTHORIZATION_BAD_1}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {"authorization": BASIC_AUTHORIZATION_BAD_2}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {"authorization": BASIC_AUTHORIZATION_BAD_3}
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


def test_verify_permission():
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


def test_dav_auth_create_response_401():
    request = DAVRequest(
        scope=ASGIScope(
            {
                "method": "GET",
                "headers": dict({b"user-agent": b"litmus/0.13 neon/0.31.2"}),
                "path": "/",
            }
        ),
        receive=fake_call,
        send=fake_call,
    )
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
