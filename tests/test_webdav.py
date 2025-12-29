import pytest

from .testkit_asgi import ASGITestClient, get_webdav_app

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
async def test_basic():
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
