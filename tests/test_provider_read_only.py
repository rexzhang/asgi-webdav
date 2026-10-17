import pytest

from asgi_webdav.config import generate_config_from_dict
from asgi_webdav.server import DAVApp

from .kits.asgi import create_asgiref_http_scope_object

USERNAME = "username"
PASSWORD = "password"

CONFIG_DATA = {
    "account_mapping": [
        {"username": USERNAME, "password": PASSWORD, "permissions": ["+"]},
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
            "read_only": True,
        },
    ],
}


def basic_auth_headers() -> dict[str, str]:
    # username:password
    return {"authorization": "Basic dXNlcm5hbWU6cGFzc3dvcmQ="}


async def handle(
    method: str,
    path: str,
    headers: dict[str, str],
    data: bytes = b"",
    app: DAVApp | None = None,
):
    if app is None:
        app = DAVApp(generate_config_from_dict(CONFIG_DATA))

    scope = create_asgiref_http_scope_object(method=method, path=path, headers=headers)

    async def receive():
        return {"type": "http.request", "body": data, "more_body": False}

    async def send(event):
        return None

    return await app.handle(scope, receive, send)


def assert_read_only_rejection(response) -> None:
    assert response.status == 403
    assert b"WWW-Authenticate" not in response.headers
    assert b"read" in response.content.lower()


@pytest.mark.asyncio
async def test_read_only_write_methods_rejected_with_403():
    headers = basic_auth_headers()

    for method, path, data in [
        ("PUT", "/new-file", b"data"),
        ("MKCOL", "/new-dir", b""),
        ("DELETE", "/anything", b""),
        ("COPY", "/anything", b""),
        ("MOVE", "/anything", b""),
    ]:
        extra: dict[str, str] = {}
        if method in ("COPY", "MOVE"):
            extra = {"destination": "/other"}

        _, response = await handle(method, path, headers | extra, data)
        assert_read_only_rejection(response)


@pytest.mark.asyncio
async def test_read_only_lock_unlock_rejected_with_403():
    headers = basic_auth_headers()
    lock_body = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<D:lockinfo xmlns:D="DAV:">'
        b"<D:lockscope><D:exclusive/></D:lockscope>"
        b"<D:locktype><D:write/></D:locktype>"
        b"<D:owner>test</D:owner>"
        b"</D:lockinfo>"
    )

    _, response = await handle("LOCK", "/file", headers, lock_body)
    assert_read_only_rejection(response)

    unlock_headers = headers | {
        "lock-token": ("<opaquelocktoken:00000000-0000-4000-8000-000000000000>")
    }
    _, response = await handle("UNLOCK", "/file", unlock_headers)
    assert_read_only_rejection(response)


@pytest.mark.asyncio
async def test_read_only_proppatch_rejected_with_403():
    headers = basic_auth_headers() | {"content-type": "application/xml"}
    body = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<D:propertyupdate xmlns:D="DAV:">'
        b'<D:set><D:prop><prop0 xmlns="">value0</prop0></D:prop></D:set>'
        b"</D:propertyupdate>"
    )

    _, response = await handle("PROPPATCH", "/file", headers, body)
    assert_read_only_rejection(response)


@pytest.mark.asyncio
async def test_read_only_options_advertises_no_class_2():
    app = DAVApp(generate_config_from_dict(CONFIG_DATA))
    provider = app.web_dav.prefix_provider_mapping[0].provider
    assert provider.read_only is True

    _, response = await handle("OPTIONS", "/", basic_auth_headers())
    assert response.status == 200
    assert response.headers[b"DAV"] == b"1"
    assert b"PUT" not in response.headers[b"Allow"]


@pytest.mark.asyncio
async def test_writable_provider_options_advertises_class_2():
    writable_config_data = CONFIG_DATA | {
        "provider_mapping": [
            {
                "prefix": "/",
                "uri": "memory:///",
            },
        ],
    }
    app = DAVApp(generate_config_from_dict(writable_config_data))
    provider = app.web_dav.prefix_provider_mapping[0].provider
    assert provider.read_only is False

    _, response = await handle("OPTIONS", "/", basic_auth_headers(), app=app)
    assert response.status == 200
    assert response.headers[b"DAV"] == b"1, 2", response.headers.get(b"DAV")
    assert b"PUT" in response.headers[b"Allow"]
