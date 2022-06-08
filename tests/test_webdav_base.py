import pytest

from asgi_webdav.config import update_config_from_obj
from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.dev import dev_config_object as dev_config_object_default
from asgi_webdav.server import get_asgi_app

from .asgi_test_kit import ASGIRequest, ASGITestClient

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


def get_webdav_app(dev_config_object: dict = None):
    if dev_config_object is None:
        dev_config_object = dev_config_object_default

    return get_asgi_app(
        AppEntryParameters(), update_config_from_obj(dev_config_object).dict()
    )


@pytest.mark.asyncio
async def test_base():
    client = ASGITestClient(get_webdav_app(dev_config_object=CONFIG_DATA))
    response = await client.get(
        "/", client.create_basic_authorization_headers(USERNAME, PASSWORD)
    )
    assert response.status_code == 200
