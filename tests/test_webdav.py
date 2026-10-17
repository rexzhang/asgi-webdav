import pytest

from asgi_webdav.config import generate_config_from_dict
from asgi_webdav.server import DAVApp

from .kits.asgi import ASGITestClient, get_webdav_app

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
        {
            "prefix": "/webhdfs",
            "uri": "https://localhost",
        },
    ],
}


@pytest.mark.asyncio
async def test_basic() -> None:
    client = ASGITestClient(get_webdav_app(config_object=CONFIG_DATA))

    response = await client.get(
        "/", client.create_basic_authorization_headers(USERNAME, PASSWORD)
    )
    assert response.status_code == 200

    response = await client.get(
        "/webhdfs",
        client.create_basic_authorization_headers(USERNAME, PASSWORD),
    )
    assert response.status_code == 403


def test_webdav_instances_do_not_share_provider_mapping() -> None:
    # every WebDAV instance must own its provider mapping; instances in
    # the same process must not see each other's providers
    config = generate_config_from_dict(CONFIG_DATA)
    web_dav_first = DAVApp(config).web_dav
    web_dav_second = DAVApp(config).web_dav

    first_count = len(web_dav_first.prefix_provider_mapping)
    assert first_count > 0
    assert len(web_dav_second.prefix_provider_mapping) == first_count
