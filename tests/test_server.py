import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from asgi_middleware_static_file import ASGIMiddlewareStaticFile
from asgiref.typing import ASGIReceiveEvent, HTTPScope
from pytest_mock import MockerFixture

import asgi_webdav
from asgi_webdav.config import Config, generate_config_from_dict
from asgi_webdav.constants import AppEntryParameters, DevMode
from asgi_webdav.exceptions import DAVExceptionProviderInitFailed
from asgi_webdav.middleware.cors import ASGIMiddlewareCORS
from asgi_webdav.response import DAVResponse
from asgi_webdav.server import DAVApp, convert_aep_to_uvicorn_kwargs, get_asgi_app
from asgi_webdav.web_dav import WebDAV

from .kits.asgi import ASGIFakeSend, create_asgiref_http_scope_object, fake_send
from .kits.common import CLIENT_UA_FIREFOX

USERNAME = "username"
PASSWORD = "password"

CONFIG_OBJECT: dict[str, Any] = {
    "account_mapping": [
        {"username": USERNAME, "password": PASSWORD, "permissions": ["+"]},
    ],
    "provider_mapping": [
        {"prefix": "/", "uri": "memory:///"},
    ],
}

AUTHORIZATION_HEADERS = {
    "authorization": "Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
    "user-agent": "pytest",
}


@pytest.fixture(autouse=True)
def clean_prefix_provider_mapping() -> Iterator[None]:
    # WebDAV.prefix_provider_mapping is a shared class-level list: every
    # DAVApp/WebDAV built anywhere appends to it, so reset it around each test
    WebDAV.prefix_provider_mapping.clear()
    yield
    WebDAV.prefix_provider_mapping.clear()


@pytest.fixture()
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # keep get_asgi_app away from the repo .env file (WEBDAV_SENTRY_DSN is
    # loaded relative to the current working directory) and the shell env
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEBDAV_SENTRY_DSN", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)


@pytest.fixture()
def dav_app() -> DAVApp:
    return DAVApp(generate_config_from_dict(CONFIG_OBJECT))


class BodyReceive:
    """ASGI receive callable: the body in one event, http.disconnect after."""

    def __init__(self, body: bytes) -> None:
        self._body: bytes | None = body

    async def __call__(self) -> ASGIReceiveEvent:
        if self._body is not None:
            body, self._body = self._body, None
            event: ASGIReceiveEvent = {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
            return event

        # keep the disconnect watcher from spinning on immediate events
        return {"type": "http.disconnect"}


def get_scope(
    method: str, path: str, headers: dict[str, str] | None = None
) -> HTTPScope:
    data = AUTHORIZATION_HEADERS.copy()
    if headers is not None:
        data.update(headers)

    return create_asgiref_http_scope_object(method=method, path=path, headers=data)


async def get_response_content(response: DAVResponse) -> bytes:
    content = b""
    async for data, _more_data in response.content_body_generator:
        content += data

    return content


# --- DAVApp


def test_dav_app_init_provider_failed_system_exit(mocker: MockerFixture) -> None:
    # WebDAV.__init__ swallows every provider failure itself, so the abort
    # path in DAVApp.__init__ is only reachable when the ctor itself raises
    mocker.patch(
        "asgi_webdav.server.WebDAV",
        side_effect=DAVExceptionProviderInitFailed("mock init failed"),
    )

    with pytest.raises(SystemExit):
        DAVApp(Config())


async def test_dav_app_call_get_and_copy(dav_app: DAVApp) -> None:
    scope = get_scope("PUT", "/file.txt")
    _, response = await dav_app.handle(scope, BodyReceive(b"12345"), fake_send)
    assert response.status == 201

    # COPY goes through the full ASGI entry: __call__ picks the COPY/MOVE
    # log branch (which includes the destination) and sends via the sender
    scope = get_scope("COPY", "/file.txt", {"destination": "/file2.txt"})
    fake_send_channel = ASGIFakeSend()
    await dav_app(scope, BodyReceive(b""), fake_send_channel)

    assert fake_send_channel.status == 204

    # a regular method picks the standard request log branch
    scope = get_scope("GET", "/file.txt")
    fake_send_channel = ASGIFakeSend()
    await dav_app(scope, BodyReceive(b""), fake_send_channel)

    assert fake_send_channel.status == 200
    assert fake_send_channel.bodys == [b"12345"]


async def test_handle_wrong_credentials_401(dav_app: DAVApp) -> None:
    # auth failure short-circuits the request before routing
    scope = get_scope(
        "GET", "/", {"authorization": "Basic d3Jvbmc6d3Jvbmc="}  # wrong:wrong
    )
    _, response = await dav_app.handle(scope, BodyReceive(b""), fake_send)

    assert response.status == 401
    assert b"WWW-Authenticate" in response.headers


async def test_handle_admin_root_page(dav_app: DAVApp) -> None:
    scope = get_scope("GET", "/_")
    _, response = await dav_app.handle(scope, BodyReceive(b""), fake_send)

    assert response.status == 200
    content = await get_response_content(response)
    assert b"/_/admin/logging" in content


async def test_handle_distribute_provider_init_failed_system_exit(
    dav_app: DAVApp, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        dav_app.web_dav,
        "distribute",
        side_effect=DAVExceptionProviderInitFailed("mock init failed"),
    )

    scope = get_scope("GET", "/")
    with pytest.raises(SystemExit):
        await dav_app.handle(scope, BodyReceive(b""), fake_send)


async def test_handle_browser_401_returns_login_form() -> None:
    config = generate_config_from_dict(
        {
            "account_mapping": [
                {"username": USERNAME, "password": PASSWORD, "permissions": ["+"]},
                {
                    "username": "anonymous",
                    "password": "",
                    "permissions": ["+^/pub/"],
                },
            ],
            "anonymous": {"enable": True},
            "provider_mapping": [
                {"prefix": "/", "uri": "memory:///"},
            ],
        }
    )
    dav_app = DAVApp(config)

    # no authorization header + restricted anonymous user + browser UA:
    # distribute answers 401, handle() converts it to the login form page
    scope = create_asgiref_http_scope_object(
        method="GET",
        path="/pub",
        headers={"user-agent": CLIENT_UA_FIREFOX},
    )
    _, response = await dav_app.handle(scope, BodyReceive(b""), fake_send)

    assert response.status == 401
    assert b"WWW-Authenticate" in response.headers
    content = await get_response_content(response)
    assert b"401" in content


# --- get_asgi_app


def test_get_asgi_app_from_config_file(clean_env: None, tmp_path: Path) -> None:
    config_file = tmp_path / "server.json"
    config_file.write_text(json.dumps(CONFIG_OBJECT), encoding="utf-8")

    aep = AppEntryParameters(config_file=str(config_file))
    app: Any = get_asgi_app(aep=aep)

    assert isinstance(app, ASGIMiddlewareStaticFile)
    assert isinstance(app.app, DAVApp)
    assert app.app.config.provider_mapping[0].prefix == "/"


def test_get_asgi_app_from_missing_config_file(clean_env: None, tmp_path: Path) -> None:
    aep = AppEntryParameters(config_file=str(tmp_path / "missing.json"))
    app: Any = get_asgi_app(aep=aep)

    # the config file can not be loaded => fall back to the default config
    assert isinstance(app, ASGIMiddlewareStaticFile)
    assert isinstance(app.app, DAVApp)


def test_get_asgi_app_default_config(clean_env: None) -> None:
    app: Any = get_asgi_app(aep=AppEntryParameters())

    assert isinstance(app, ASGIMiddlewareStaticFile)
    assert isinstance(app.app, DAVApp)


def test_get_asgi_app_with_config_obj(clean_env: None) -> None:
    app: Any = get_asgi_app(aep=AppEntryParameters(), config_obj=CONFIG_OBJECT)

    assert isinstance(app, ASGIMiddlewareStaticFile)
    assert isinstance(app.app, DAVApp)
    assert app.app.config.provider_mapping[0].prefix == "/"


def test_get_asgi_app_with_cors(clean_env: None) -> None:
    config_obj = CONFIG_OBJECT | {"cors": {"enable": True}}
    app: Any = get_asgi_app(aep=AppEntryParameters(), config_obj=config_obj)

    assert isinstance(app, ASGIMiddlewareCORS)
    assert isinstance(app.app, ASGIMiddlewareStaticFile)
    assert isinstance(app.app.app, DAVApp)


def test_get_asgi_app_with_sentry(clean_env: None, mocker: MockerFixture) -> None:
    pytest.importorskip("sentry_sdk")
    from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

    init_mock = mocker.patch("sentry_sdk.init")

    config_obj = CONFIG_OBJECT | {"sentry_dsn": "https://public@example.com/1"}
    app: Any = get_asgi_app(aep=AppEntryParameters(), config_obj=config_obj)

    init_mock.assert_called_once()
    assert init_mock.call_args.kwargs["dsn"] == "https://public@example.com/1"
    assert isinstance(app, SentryAsgiMiddleware)


def test_get_asgi_app_sentry_import_error(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # simulate: sentry_sdk is not installed
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)

    config_obj = CONFIG_OBJECT | {"sentry_dsn": "https://public@example.com/1"}
    app: Any = get_asgi_app(aep=AppEntryParameters(), config_obj=config_obj)

    # the import failure is swallowed, the app keeps working without sentry
    assert isinstance(app, ASGIMiddlewareStaticFile)
    assert isinstance(app.app, DAVApp)


# --- convert_aep_to_uvicorn_kwargs


def test_convert_aep_to_uvicorn_kwargs_dev_mode() -> None:
    aep = AppEntryParameters(
        bind_host="127.0.0.1",
        bind_port=8888,
        dev_mode=DevMode.DEV,
    )
    kwargs = convert_aep_to_uvicorn_kwargs(aep)

    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8888
    assert kwargs["use_colors"] is True
    assert kwargs["lifespan"] == "off"
    assert kwargs["log_level"] == "warning"
    assert kwargs["access_log"] is False
    assert kwargs["forwarded_allow_ips"] == "*"
    assert kwargs["app"] == "asgi_webdav.dev.dev:app"
    assert kwargs["reload"] is True
    package_path = Path(asgi_webdav.__file__)
    assert kwargs["reload_dirs"] == [package_path.parent.as_posix()]


def test_convert_aep_to_uvicorn_kwargs_production(clean_env: None) -> None:
    aep = AppEntryParameters(bind_host="0.0.0.0", bind_port=8000)
    kwargs = convert_aep_to_uvicorn_kwargs(aep)

    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8000
    assert kwargs["use_colors"] is True
    assert kwargs["lifespan"] == "off"
    assert kwargs["log_level"] == "warning"
    assert kwargs["access_log"] is False
    assert kwargs["forwarded_allow_ips"] == "*"
    assert isinstance(kwargs["app"], ASGIMiddlewareStaticFile)
