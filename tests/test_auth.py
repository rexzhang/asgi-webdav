from base64 import b64encode
from copy import deepcopy

import pytest
from icecream import ic

from asgi_webdav.auth import DAVAuth, DAVPassword, DAVPasswordType
from asgi_webdav.cache import DAVCacheType
from asgi_webdav.config import Config, get_config_copy_from_dict
from asgi_webdav.constants import DAVPath, DAVUser
from asgi_webdav.exception import DAVExceptionConfigPaserFailed
from asgi_webdav.request import DAVRequest

from .test_webdav_base import ASGITestClient, get_webdav_app

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

BASIC_AUTHORIZATION = b"Basic " + b64encode(f"{USERNAME}:{PASSWORD}".encode())
BASIC_AUTHORIZATION_BAD_1 = b"Basic bad basic_authorization"
BASIC_AUTHORIZATION_BAD_2 = b"Basic " + b64encode(b"username-password")
BASIC_AUTHORIZATION_BAD_3 = b"BasicAAAAA"
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
    "account_mapping": [
        {
            "username": USERNAME_ANONYMOUS_USER,
            "password": PASSWORD_ANONYMOUS_USER,
            "permissions": ["+^/$"],
        }
    ],
    "anonymous_username": USERNAME_ANONYMOUS_USER,
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}

BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_BAD_1 = {
    "account_mapping": [
        {
            "username": "wrong-anonymous-username",
            "password": PASSWORD_ANONYMOUS_USER,
            "permissions": ["+^/$"],
        }
    ],
    "anonymous_username": USERNAME_ANONYMOUS_USER,
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}

BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_BAD_2 = {
    "account_mapping": [
        {
            "username": USERNAME_ANONYMOUS_USER,
            "password": PASSWORD_ANONYMOUS_USER,
            "permissions": ["+^/$"],
        }
    ],
    "anonymous_username": "wrong-anonymous-username",
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

    headers = {b"authorization": BASIC_AUTHORIZATION_BAD_1}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {b"authorization": BASIC_AUTHORIZATION_BAD_2}
    response = await client.get("/", headers=headers)
    assert response.status_code == 401

    headers = {b"authorization": BASIC_AUTHORIZATION_BAD_3}
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
    client = ASGITestClient(
        get_webdav_app(config_object=BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER)
    )

    response = await client.get(
        "/",
    )
    assert response.status_code == 200

    response = await client.get(
        "/no_permission",
    )
    assert response.status_code == 403


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


def get_dav_request(extra_headers: dict[bytes, bytes] = {}) -> DAVRequest:
    headers_dict = {b"user-agent": b"litmus/0.13 neon/0.31.2"} | extra_headers
    headers = [(k, v) for k, v in headers_dict.items()]

    return DAVRequest(
        scope={
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "query_string": b"",
            "headers": headers,
        },
        receive=fake_call,
        send=fake_call,
    )


@pytest.mark.asyncio
async def test_dav_auth_pick_out_user_anonymous_user():
    # anonymous user : ok
    config = get_config_copy_from_dict(
        BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER
    )
    dav_auth = DAVAuth(config)
    ic(config)
    ic(dav_auth.user_mapping)

    user, message = await dav_auth.pick_out_user(get_dav_request({}))
    assert user is not None
    assert user.username == USERNAME_ANONYMOUS_USER

    # ---
    user, message = await dav_auth.pick_out_user(
        get_dav_request({b"authorization": BASIC_AUTHORIZATION})
    )
    assert user is None

    # anonymous user : bad : 1
    config = get_config_copy_from_dict(
        BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_BAD_1
    )
    with pytest.raises(DAVExceptionConfigPaserFailed):
        dav_auth = DAVAuth(config)

    # anonymous user : bad : 2
    config = get_config_copy_from_dict(
        BASIC_AUTHORIZATION_CONFIG_DATA_FOR_ANONYMOUS_USER_BAD_2
    )
    with pytest.raises(DAVExceptionConfigPaserFailed):
        dav_auth = DAVAuth(config)


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
