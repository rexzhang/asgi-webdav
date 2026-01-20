from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DAVPath,
    DAVRangeType,
    DAVRequestRange,
    DAVTime,
    DAVUser,
)
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
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
    request.user = DAVUser("testuser", "password", [], False)
    request.src_path = DAVPath("/testfile.txt")
    request.dist_src_path = DAVPath("/testfile.txt")
    request.dist_dst_path = DAVPath()
    request.propfind_only_fetch_basic = True
    request.propfind_extra_keys = []
    request.overwrite = True
    request.ranges = list()
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

    fake_request.ranges = [DAVRequestRange(DAVRangeType.RANGE, 0, 100, 200)]
    status, basic_data, generator, _ = await mock_provider._do_get(fake_request)

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
        prefix=DAVPath(),
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
        prefix=DAVPath(),
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


@pytest.mark.asyncio
async def test_do_filestatus_failure(mock_provider, fake_request):
    mock_response = AsyncMock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="Error", request=MagicMock(), response=MagicMock(status_code=404)
    )
    mock_response.json = MagicMock(return_value={"FileStatus": {}})

    mock_provider.client.get.return_value = mock_response

    url_path = DAVPath("/notfound.txt")

    response = await mock_provider._do_filestatus(fake_request, url_path)
    assert response == (404, {})


@pytest.mark.asyncio
async def test_do_get_collection(mock_provider, fake_request):
    fake_status = {
        "type": "DIRECTORY",
        "length": 0,
        "modificationTime": 1234567890,
    }

    mock_provider._get_dav_property_d0 = AsyncMock(
        return_value=(
            200,
            await mock_provider._create_dav_property_obj(
                fake_request, DAVPath("/folder"), fake_status
            ),
        )
    )

    status, basic_data, generator, response_content_range = await mock_provider._do_get(
        fake_request
    )
    assert status == 200
    assert basic_data.is_collection is True
    assert generator is None
    assert response_content_range is None


@pytest.mark.asyncio
async def test_dav_response_data_generator(mock_provider, fake_request):
    async def fake_aiter_bytes():
        yield b"chunk1"
        yield b"chunk2"

    fake_response = MagicMock()
    fake_response.aiter_bytes = fake_aiter_bytes
    fake_response.raise_for_status = MagicMock()

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__.return_value = fake_response
    mock_stream_ctx.__aexit__.return_value = None

    mock_provider.client.stream = MagicMock(return_value=mock_stream_ctx)

    gen = mock_provider._dav_response_data_generator(
        fake_request,
        DAVPath("/testfile.txt"),
        content_range_start=None,
        content_range_end=None,
    )

    result = []
    async for chunk, more in gen:
        result.append((chunk, more))

    assert result == [(b"chunk1", True), (b"chunk2", False)]


@pytest.mark.asyncio
async def test_do_put(mock_provider, fake_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"FileStatus": {}})
    mock_response.raise_for_status = AsyncMock()

    mock_provider.client.get.return_value = mock_response

    response = await mock_provider._do_put(fake_request)

    assert response == 204


@pytest.mark.asyncio
async def test_do_copy(mock_provider, fake_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"FileStatus": {}})
    mock_response.raise_for_status = AsyncMock()

    mock_provider.client.get.return_value = mock_response

    with pytest.raises(NotImplementedError):
        await mock_provider._do_copy(fake_request)


@pytest.mark.asyncio
async def test_do_mkcol(mock_provider, fake_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"FileStatus": {}})
    mock_response.raise_for_status = AsyncMock()

    mock_provider.client.get.return_value = mock_response

    response = await mock_provider._do_mkcol(fake_request)

    assert response == 405


@pytest.mark.asyncio
async def test_do_propfind(mock_provider, fake_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"FileStatus": {}})
    mock_response.raise_for_status = AsyncMock()

    mock_provider.client.get.return_value = mock_response

    response = await mock_provider._do_propfind(fake_request)
    from icecream import ic

    ic(response)

    expected = {
        DAVPath("/testfile.txt"): DAVProperty(
            href_path=DAVPath("/user/testuser/testfile.txt"),
            is_collection=False,
            basic_data=DAVPropertyBasicData(
                is_collection=False,
                display_name="testfile.txt",
                creation_date=DAVTime(0),
                last_modified=DAVTime(0),
                content_type="text/plain",
                content_charset=None,
                content_length=0,
                content_encoding=None,
            ),
            extra_data={},
            extra_not_found=[],
        )
    }

    assert set(response.keys()) == set(expected.keys())

    for key in expected:
        resp_val = response[key]
        exp_val = expected[key]

        assert resp_val.href_path == exp_val.href_path
        assert resp_val.is_collection == exp_val.is_collection

        assert resp_val.basic_data.is_collection == exp_val.basic_data.is_collection
        assert resp_val.basic_data.display_name == exp_val.basic_data.display_name
        assert resp_val.basic_data.content_type == exp_val.basic_data.content_type
        assert resp_val.basic_data.content_charset == exp_val.basic_data.content_charset
        assert resp_val.basic_data.content_length == exp_val.basic_data.content_length
        assert (
            resp_val.basic_data.content_encoding == exp_val.basic_data.content_encoding
        )

        assert resp_val.extra_data == exp_val.extra_data
        assert resp_val.extra_not_found == exp_val.extra_not_found


@pytest.mark.asyncio
async def test_do_head(mock_provider, fake_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"FileStatus": {}})
    mock_response.raise_for_status = AsyncMock()

    mock_provider.client.get.return_value = mock_response

    response = await mock_provider._do_head(fake_request)

    assert response[0] == 200


@pytest.mark.asyncio
async def test_do_precheck_destination(mock_provider, fake_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"FileStatus": {}})
    mock_response.raise_for_status = AsyncMock()

    mock_provider.client.get.return_value = mock_response

    response = await mock_provider._precheck_destination(fake_request)

    assert response == (True, False, True)


@pytest.mark.asyncio
async def test_do_move(mock_provider, fake_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = MagicMock(return_value={"FileStatus": {}})
    mock_response.raise_for_status = AsyncMock()

    mock_provider.client.get.return_value = mock_response

    response = await mock_provider._do_move(fake_request)

    assert response == 204
