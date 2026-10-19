from pathlib import Path

import pytest

from asgi_webdav.config import Config
from asgi_webdav.constants import DAVPath, DAVUser
from asgi_webdav.property import DAVProperty
from asgi_webdav.provider.file_system import (
    FileSystemProvider,
    _dav_response_body_generator,
    _load_extra_property,
    _parser_property_from_json,
    _update_extra_property,
)
from tests.kits.asgi import create_dav_request_object

DAV_FILENAME = "/tmp/test.DAV"


@pytest.mark.asyncio
async def test_property_file() -> None:
    dav_file = Path(DAV_FILENAME)
    patches_data_1 = [(("ns1", "key1"), "v1", True)]
    patches_data_2 = [(("ns2", "key2"), "v2", True)]
    patches_data_3 = [(("ns2", "key2"), "v2", False)]

    if dav_file.exists():
        dav_file.unlink()

    assert await _update_extra_property(Path(DAV_FILENAME), patches_data_1)
    assert len(await _load_extra_property(dav_file)) == 1

    assert await _update_extra_property(Path(DAV_FILENAME), patches_data_2)
    assert len(await _load_extra_property(dav_file)) == 2

    assert await _update_extra_property(Path(DAV_FILENAME), patches_data_3)
    assert len(await _load_extra_property(dav_file)) == 1


# ---- unit: json sidecar error branches ----


async def test_parser_property_from_json_invalid_shapes() -> None:
    # non-dict root / missing or non-list "property" -> empty dict
    assert _parser_property_from_json("not a dict") == {}  # type: ignore[arg-type]
    assert _parser_property_from_json({"no_property": 1}) == {}
    assert _parser_property_from_json({"property": "not a list"}) == {}


async def test_load_extra_property_corrupt_json(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")

    assert await _load_extra_property(corrupt) == {}


async def test_update_extra_property_corrupt_json(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")

    assert (
        await _update_extra_property(corrupt, [(("ns1", "key1"), "v1", True)]) is False
    )


# ---- unit: body generator, etag, charset ----


def make_fs_provider(
    tmp_root: Path, charset_detect: bool = False
) -> FileSystemProvider:
    config = Config()
    config.text_file_charset_detect.enable = charset_detect
    return FileSystemProvider(
        config=config,
        prefix=DAVPath("/"),
        uri=f"file://{tmp_root}",
        home_dir=False,
        read_only=False,
        ignore_property_extra=False,
    )


@pytest.mark.asyncio
async def test_dav_response_body_generator_multi_block(tmp_path: Path) -> None:
    # a file larger than one block exercises the full-block loop branch
    big_file = tmp_path / "big.bin"
    block = bytes(range(256)) * 256  # 64KB
    big_file.write_bytes(block * 3)

    chunks = [
        (data, more) async for data, more in _dav_response_body_generator(big_file)
    ]

    # three full blocks plus the empty terminator yielded after EOF
    assert len(chunks) == 4
    assert [data for data, _ in chunks[:3]] == [block] * 3
    assert chunks[-1] == (b"", False)
    assert [more for _, more in chunks] == [True, True, True, False]


@pytest.mark.asyncio
async def test_get_res_etag(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path)
    target = tmp_path / "etag_file"
    target.write_bytes(b"etag content")

    request = create_dav_request_object(method="GET", path="/etag_file")
    request.dist_src_path = DAVPath("/etag_file")
    request.user = DAVUser("testuser", "password", [], False)

    etag = await provider._get_res_etag(request)
    assert isinstance(etag, str)
    assert etag == await provider._get_res_etag_from_res_dist_path(
        DAVPath("/etag_file")
    )


@pytest.mark.asyncio
async def test_dav_response_body_generator_content_range_multi_block(
    tmp_path: Path,
) -> None:
    # a content range spanning more than one block exercises the range
    # loop's full-block branch
    from asgi_webdav.constants import (
        DAVRangeType,
        DAVResponseContentRange,
    )

    big_file = tmp_path / "ranged.bin"
    block = bytes(range(256)) * 256
    big_file.write_bytes(block * 3)

    content_range = DAVResponseContentRange(
        DAVRangeType.RANGE, 0, len(block) * 3 - 1, len(block) * 3
    )
    chunks = [
        (data, more)
        async for data, more in _dav_response_body_generator(
            big_file,
            content_range=content_range,
        )
    ]

    # three full blocks plus the empty terminator
    assert [data for data, _ in chunks[:3]] == [block] * 3
    assert chunks[-1] == (b"", False)
    assert sum(len(data) for data, _ in chunks) == len(block) * 3


def test_copy_dir_depth0(tmp_path: Path) -> None:
    src = tmp_path / "d0_src"
    src.mkdir()
    (src / "keep_me").write_bytes(b"x")

    # fresh destination -> copies the (empty) collection
    dst = tmp_path / "d0_dst"
    assert FileSystemProvider._copy_dir_depth0(src, dst) is True
    assert dst.is_dir()
    assert list(dst.iterdir()) == []

    # existing destination without overwrite -> False
    assert FileSystemProvider._copy_dir_depth0(src, dst, overwrite=False) is False


@pytest.mark.asyncio
async def test_get_dav_property_d1_infinity_depth_exhausted(
    tmp_path: Path,
) -> None:
    provider = make_fs_provider(tmp_path)
    # depth_limit <= 0 stops the walk (the provider never passes 0 for
    # Depth:1 today, the guard protects the recursion contract)
    (tmp_path / "parent").mkdir()
    (tmp_path / "parent" / "sub").mkdir()

    request = create_dav_request_object(method="PROPFIND", path="/parent")
    dav_properties: dict[DAVPath, DAVProperty] = {}
    await provider._get_dav_property_d1_infinity(
        dav_properties,
        request,
        DAVPath("/parent"),
        tmp_path / "parent",
        infinity=False,
        depth_limit=0,
    )

    # only the immediate children were visited before the guard
    assert sorted(p.raw for p in dav_properties) == ["/parent/sub"]


async def test_create_dav_property_obj_charset_detect(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path, charset_detect=True)
    target = tmp_path / "charset.txt"
    target.write_text("charset probe", encoding="utf-8")

    request = create_dav_request_object(method="PROPFIND", path="/charset.txt")
    request.propfind_only_fetch_basic = False
    request.propfind_extra_keys = []

    dav_property = await provider._create_dav_property_obj(
        request, DAVPath("/charset.txt"), target, target.stat()
    )

    assert dav_property.basic_data.content_type == "text/plain"
    assert dav_property.basic_data.content_charset is not None


# ---- unit: _do_proppatch branches (fs implementation) ----


@pytest.mark.asyncio
async def test_do_proppatch_ignore_property_extra(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path)
    provider.ignore_property_extra = True
    target = tmp_path / "ignore_file"
    target.write_bytes(b"data")

    request = create_dav_request_object(method="PROPPATCH", path="/ignore_file")
    request.dist_src_path = DAVPath("/ignore_file")
    request.body_is_parsed_success = True
    request.proppatch_entries = [(("ns1", "key1"), "v1", True)]
    request.lock_ifs = []

    response = await provider.do_proppatch(request)

    # no-op success: nothing is written
    assert response.status == 207
    assert not list(tmp_path.rglob("*.DAV"))


@pytest.mark.asyncio
async def test_do_proppatch_missing_resource_404(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path)

    request = create_dav_request_object(method="PROPPATCH", path="/no_such_file")
    request.dist_src_path = DAVPath("/no_such_file")
    request.user = DAVUser("testuser", "password", [], False)
    request.body_is_parsed_success = True
    request.proppatch_entries = [(("ns1", "key1"), "v1", True)]
    request.lock_ifs = []

    response = await provider.do_proppatch(request)

    assert response.status == 404


@pytest.mark.asyncio
async def test_do_proppatch_corrupt_sidecar_409(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path)
    target = tmp_path / "broken_file"
    target.write_bytes(b"data")
    sidecar = provider._get_fs_properties_path(tmp_path / "broken_file")
    sidecar.write_text("{corrupt", encoding="utf-8")

    request = create_dav_request_object(method="PROPPATCH", path="/broken_file")
    request.dist_src_path = DAVPath("/broken_file")
    request.user = DAVUser("testuser", "password", [], False)
    request.body_is_parsed_success = True
    request.proppatch_entries = [(("ns1", "key1"), "v1", True)]
    request.lock_ifs = []

    response = await provider.do_proppatch(request)

    assert response.status == 409


@pytest.mark.asyncio
async def test_move_property_file_replaces_existing_dst_sidecar(
    tmp_path: Path,
) -> None:
    # moving onto a resource that already has a sidecar replaces it
    provider = make_fs_provider(tmp_path)
    src = tmp_path / "mv_src_file"
    dst = tmp_path / "mv_dst_file"
    src.write_bytes(b"src")
    dst.write_bytes(b"dst")

    src_sidecar = provider._get_fs_properties_path(src)
    dst_sidecar = provider._get_fs_properties_path(dst)
    src_sidecar.write_text(
        '{"property": [[["ns1", "src-key"], "src-value"]]}', encoding="utf-8"
    )
    dst_sidecar.write_text(
        '{"property": [[["ns1", "dst-key"], "dst-value"]]}', encoding="utf-8"
    )

    await provider._move_property_file(src, dst)

    assert not src_sidecar.exists()
    assert await _load_extra_property(dst_sidecar) == {("ns1", "src-key"): "src-value"}
