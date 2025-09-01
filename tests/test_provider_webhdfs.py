from unittest.mock import AsyncMock, MagicMock

import pytest

from asgi_webdav.config import Config
from asgi_webdav.constants import DAVPath
from asgi_webdav.provider.webhdfs import WebHDFSProvider
from asgi_webdav.request import DAVRequest


@pytest.fixture
def mock_provider(mock_config):
    provider = WebHDFSProvider(
        uri="http://fake-hdfs:9870/webhdfs/v1",
        config=mock_config,
        home_dir="/user",
        prefix="",
        read_only=False,
        ignore_property_extra=False,
    )
    provider.client = AsyncMock()
    return provider


@pytest.fixture
def mock_config():
    mock = MagicMock()
    mock.guess_type_extension.enable = False
    return mock


@pytest.fixture
def fake_request():
    request = MagicMock(spec=DAVRequest)
    request.user.username = "testuser"
    request.src_path = DAVPath("/testfile.txt")
    request.dist_src_path = DAVPath("/testfile.txt")
    request.propfind_only_fetch_basic = True
    request.propfind_extra_keys = []
    return request


@pytest.mark.asyncio
async def test_get_url_path_with_home(mock_provider):
    path = DAVPath("/testfile.txt")
    result = mock_provider._get_url_path(path, "john")
    assert str(result).startswith("/user/john")
    assert "testfile.txt" in str(result)


@pytest.mark.asyncio
async def test_do_filestatus_success(mock_provider, fake_request):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = AsyncMock()

    mock_response.json = MagicMock(
        return_value={
            "FileStatus": {
                "type": "FILE",
                "length": 123,
                "modificationTime": 1234567890,
            }
        }
    )

    mock_provider.client.get.return_value = mock_response

    url_path = DAVPath("/testfile.txt")
    status_code, file_status = await mock_provider._do_filestatus(
        fake_request, url_path
    )

    assert status_code == 200
    assert file_status["type"] == "FILE"


@pytest.mark.asyncio
async def test_do_get_file(mock_provider, fake_request):
    fake_status = {
        "type": "FILE",
        "length": 100,
        "modificationTime": 1234567890,
    }

    mock_provider._get_dav_property_d0 = AsyncMock(
        return_value=(
            200,
            await mock_provider._create_dav_property_obj(
                fake_request, DAVPath("/testfile.txt"), fake_status
            ),
        )
    )
    mock_provider._dav_response_data_generator = AsyncMock(return_value=AsyncMock())

    status, basic_data, generator = await mock_provider._do_get(fake_request)

    assert status == 200
    assert basic_data.content_length == 100
    assert generator is not None


@pytest.mark.asyncio
async def test_do_delete_success(mock_provider, fake_request):
    mock_provider._precheck_source = AsyncMock(return_value=(True, True, False))
    mock_provider.client.delete.return_value = AsyncMock(
        status_code=204, raise_for_status=AsyncMock()
    )

    result = await mock_provider._do_delete(fake_request)
    assert result == 204


@pytest.mark.asyncio
async def test_do_delete_not_found(mock_provider, fake_request):
    mock_provider._precheck_source = AsyncMock(return_value=(True, False, False))
    result = await mock_provider._do_delete(fake_request)
    assert result == 404


def test_get_url():
    root = WebHDFSProvider(
        config=Config(),
        prefix=DAVPath(""),
        uri="http://my_domain.com:9870/webhdfs/v1",
        home_dir=True,
        read_only=False,
        ignore_property_extra=False,
    )
    url = root._get_url_path(path=DAVPath("/new_folder/file.txt"), user_name=None)
    user_url = root._get_url_path(path=DAVPath("/new_folder/file.txt"), user_name="me")
    url_2 = root._get_url_path(path=DAVPath("/new_folder/file#1.txt"), user_name=None)
    user_url_2 = root._get_url_path(
        path=DAVPath("/new_folder/file#1.txt"), user_name="me"
    )
    assert url == DAVPath("/new_folder/file.txt")
    assert user_url == DAVPath("/user/me/new_folder/file.txt")
    assert url_2 == DAVPath("/new_folder/file%231.txt")
    assert user_url_2 == DAVPath("/user/me/new_folder/file%231.txt")
    root_2 = WebHDFSProvider(
        config=Config(),
        prefix=DAVPath(""),
        uri="http://my_domain.com:9870/webhdfs/v1",
        home_dir=True,
        read_only=False,
        ignore_property_extra=False,
    )
    url_3 = root_2._get_url_path(path=DAVPath("/new_folder/file.txt"), user_name=None)
    user_url_3 = root_2._get_url_path(
        path=DAVPath("/new_folder/file.txt"), user_name="me"
    )
    url_4 = root_2._get_url_path(path=DAVPath("/new_folder/file#1.txt"), user_name=None)
    user_url_4 = root_2._get_url_path(
        path=DAVPath("/new_folder/file#1.txt"), user_name="me"
    )
    assert url_3 == DAVPath("/new_folder/file.txt")
    assert user_url_3 == DAVPath("/user/me/new_folder/file.txt")
    assert url_4 == DAVPath("/new_folder/file%231.txt")
    assert user_url_4 == DAVPath("/user/me/new_folder/file%231.txt")
