import pytest

from asgi_webdav.config import init_config_from_obj
from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.server import get_asgi_app

from .asgi_test_kit import ASGITestClient

USERNAME = "username"
PASSWORD = "password"

CONFIG_DATA = {
    "account_mapping": [
        {"username": USERNAME, "password": PASSWORD, "permissions": ["+^/$"]},
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "memory:///",
        },
    ],
}


def get_webdav_app(config_object: dict = None):
    return get_asgi_app(
        AppEntryParameters(), init_config_from_obj(config_object).model_dump()
    )


@pytest.mark.asyncio
async def test_base():
    client = ASGITestClient(get_webdav_app(config_object=CONFIG_DATA))
    response = await client.get(
        "/", client.create_basic_authorization_headers(USERNAME, PASSWORD)
    )
    assert response.status_code == 200
