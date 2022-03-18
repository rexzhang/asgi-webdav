import pytest

from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.config import update_config_from_obj
from asgi_webdav.dev import dev_config_object
from asgi_webdav.server import get_asgi_app


from .asgi_test_kit import ASGIRequest, ASGITestClient


def get_webdav_app():
    return get_asgi_app(
        AppEntryParameters(), update_config_from_obj(dev_config_object).dict()
    )


@pytest.mark.asyncio
async def test_base():
    client = ASGITestClient(get_webdav_app())
    response = await client.get("/")
    assert response.status_code == 200
