import asyncio
import builtins
import errno
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, BinaryIO

import aiofiles
import pytest
from pytest_mock import MockerFixture

from asgi_webdav.config import Config
from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE, DAVPath, DAVUser
from asgi_webdav.property import DAVProperty
from asgi_webdav.provider.file_system import (
    FileSystemProvider,
    _dav_response_body_generator,
    _FileProbe,
    _load_extra_property,
    _open_tmp_exclusive,
    _open_tmp_stream,
    _parser_property_from_json,
    _put_error_status,
    _put_precheck,
    _PutPrecheckResult,
    _read_block,
    _run_probe,
    _stat_open_read_block,
    _stat_open_read_block_async,
    _stat_open_tmp,
    _stat_open_tmp_async,
    _update_extra_property,
    _write_all,
    _write_file_atomic,
)
from asgi_webdav.request import DAVRequest
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

    probe = await _stat_open_read_block_async(big_file, RESPONSE_DATA_BLOCK_SIZE)
    chunks = [
        (data, more)
        async for data, more in _dav_response_body_generator(
            probe, big_file.stat().st_size
        )
    ]

    # three blocks, the last one carrying more_body=False (no trailing
    # empty chunk — aligned with the memory provider generator)
    assert chunks == [(block, True), (block, True), (block, False)]


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
    probe = await _stat_open_tmp_async(big_file, RESPONSE_DATA_BLOCK_SIZE)
    chunks = [
        (data, more)
        async for data, more in _dav_response_body_generator(
            probe,
            len(block) * 3,
            content_range,
        )
    ]

    # the range span is fully ledgered; the last read closes the fp
    assert [data for data, _ in chunks] == [block] * 3
    assert [more for _, more in chunks] == [True, True, False]
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


# ---- unit: GET/HEAD fused stat probe (no exists precheck, no sidecar) ----


def make_get_request(
    path: str, headers: Sequence[tuple[bytes, bytes]] | None = None
) -> DAVRequest:
    request = create_dav_request_object(method="GET", path=path, headers=headers)
    request.dist_src_path = DAVPath(path)
    request.user = DAVUser("testuser", "password", [], False)
    return request


@pytest.mark.asyncio
async def test_do_get_missing_resource_404(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path)

    status, basic_data, body, content_range = await provider._do_get(
        make_get_request("/no_such_file")
    )

    assert status == 404
    assert basic_data is None
    assert body is None
    assert content_range is None


@pytest.mark.asyncio
async def test_do_get_stat_oserror_maps_404(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # parity with the old exists() precheck: any OSError maps to 404,
    # never a 500
    provider = make_fs_provider(tmp_path)
    target = tmp_path / "locked.bin"
    target.write_bytes(b"data")
    mocker.patch("os.stat", side_effect=OSError(errno.EACCES, "permission denied"))

    status, _, _, _ = await provider._do_get(make_get_request("/locked.bin"))

    assert status == 404


@pytest.mark.asyncio
async def test_do_get_dir_returns_no_body(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path)
    (tmp_path / "a_dir").mkdir()

    status, basic_data, body, _ = await provider._do_get(make_get_request("/a_dir"))

    assert status == 200
    assert basic_data is not None
    assert basic_data.is_collection is True
    assert body is None


@pytest.mark.asyncio
async def test_do_get_file_skips_sidecar(tmp_path: Path, mocker: MockerFixture) -> None:
    # extras are enabled, but GET responses carry basic data only — the
    # sidecar must not even be probed
    provider = make_fs_provider(tmp_path)
    assert provider.ignore_property_extra is False
    target = tmp_path / "data.bin"
    target.write_bytes(b"file body")
    provider._get_fs_properties_path(target).write_text(
        '{"property": [[["ns1", "key1"], "v1"]]}', encoding="utf-8"
    )
    mocker.patch(
        "asgi_webdav.provider.file_system._load_extra_property",
        side_effect=AssertionError("GET must not load the sidecar"),
    )

    status, basic_data, body, _ = await provider._do_get(make_get_request("/data.bin"))

    assert status == 200
    assert basic_data is not None
    assert basic_data.content_length == len(b"file body")
    assert body is not None
    chunks = [data async for data, _ in body]
    assert b"".join(chunks) == b"file body"


@pytest.mark.asyncio
async def test_do_head_missing_resource_404(tmp_path: Path) -> None:
    provider = make_fs_provider(tmp_path)

    status, basic_data = await provider._do_head(make_get_request("/no_such_file"))

    assert status == 404
    assert basic_data is None


@pytest.mark.asyncio
async def test_do_head_skips_sidecar(tmp_path: Path, mocker: MockerFixture) -> None:
    provider = make_fs_provider(tmp_path)
    target = tmp_path / "head.bin"
    target.write_bytes(b"head body")
    provider._get_fs_properties_path(target).write_text(
        '{"property": [[["ns1", "key1"], "v1"]]}', encoding="utf-8"
    )
    mocker.patch(
        "asgi_webdav.provider.file_system._load_extra_property",
        side_effect=AssertionError("HEAD must not load the sidecar"),
    )

    status, basic_data = await provider._do_head(make_get_request("/head.bin"))

    assert status == 200
    assert basic_data is not None
    assert basic_data.content_length == len(b"head body")


@pytest.mark.asyncio
async def test_create_dav_property_obj_fetch_extra_default_loads_sidecar(
    tmp_path: Path,
) -> None:
    # regression: the default fetch_extra=True keeps PROPFIND sidecar loading
    provider = make_fs_provider(tmp_path)
    target = tmp_path / "prop.bin"
    target.write_bytes(b"x")
    provider._get_fs_properties_path(target).write_text(
        '{"property": [[["ns1", "key1"], "v1"]]}', encoding="utf-8"
    )

    request = create_dav_request_object(method="PROPFIND", path="/prop.bin")
    request.propfind_only_fetch_basic = False
    request.propfind_extra_keys = [("ns1", "key1")]

    dav_property = await provider._create_dav_property_obj(
        request, DAVPath("/prop.bin"), target, target.stat()
    )

    assert dav_property.extra_data == {("ns1", "key1"): "v1"}


# ---- unit: GET single-hop probe workers ----


def test_stat_open_read_block_missing(tmp_path: Path) -> None:
    probe = _stat_open_read_block(tmp_path / "nope", RESPONSE_DATA_BLOCK_SIZE)
    assert probe.stat_result is None
    assert probe.fp is None


def test_stat_open_read_block_dir_never_opens(tmp_path: Path) -> None:
    a_dir = tmp_path / "d"
    a_dir.mkdir()
    probe = _stat_open_read_block(a_dir, RESPONSE_DATA_BLOCK_SIZE)
    assert probe.stat_result is not None
    assert probe.fp is None


def test_stat_open_read_block_short_read_closes_fp(tmp_path: Path) -> None:
    # a short read proves EOF: the worker closes the fp, the caller
    # never owns it
    target = tmp_path / "small.bin"
    target.write_bytes(b"hello")

    probe = _stat_open_read_block(target, RESPONSE_DATA_BLOCK_SIZE)

    assert probe.fp is None
    assert probe.first_data == b"hello"


def test_stat_open_read_block_full_read_keeps_fp(tmp_path: Path) -> None:
    target = tmp_path / "full.bin"
    target.write_bytes(b"x" * RESPONSE_DATA_BLOCK_SIZE)

    probe = _stat_open_read_block(target, RESPONSE_DATA_BLOCK_SIZE)

    assert probe.fp is not None
    assert probe.first_data == b"x" * RESPONSE_DATA_BLOCK_SIZE
    assert probe.fp is not None and probe.fp.closed is False
    probe.fp.close()


def test_stat_open_read_block_open_race_maps_missing(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # the file vanishes between stat and open — mapped to the missing
    # sentinel (404), matching the former exists() semantics
    target = tmp_path / "race.bin"
    target.write_bytes(b"data")

    real_open = builtins.open

    def open_but_vanished(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if Path(file) == target:
            raise FileNotFoundError(errno.ENOENT, "gone")
        return real_open(file, mode, *args, **kwargs)

    mocker.patch("builtins.open", side_effect=open_but_vanished)

    probe = _stat_open_read_block(target, RESPONSE_DATA_BLOCK_SIZE)

    assert probe.stat_result is None
    assert probe.fp is None


def test_stat_open_read_block_read_failure_self_heals(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    target = tmp_path / "io.bin"
    target.write_bytes(b"data")
    mock_fp = mocker.MagicMock()
    mock_fp.read.side_effect = OSError(errno.EIO, "io")
    mocker.patch("builtins.open", return_value=mock_fp)

    with pytest.raises(OSError):
        _stat_open_read_block(target, RESPONSE_DATA_BLOCK_SIZE)

    mock_fp.close.assert_called_once()


def test_stat_open_tmp_returns_open_fp(tmp_path: Path) -> None:
    target = tmp_path / "t.bin"
    target.write_bytes(b"range body")

    probe = _stat_open_tmp(target, RESPONSE_DATA_BLOCK_SIZE)

    assert probe.fp is not None
    assert probe.first_data == b""
    probe.fp.close()


def test_read_block_closes_only_on_last(tmp_path: Path) -> None:
    target = tmp_path / "rb.bin"
    target.write_bytes(b"0123456789")
    probe = _stat_open_tmp(target, RESPONSE_DATA_BLOCK_SIZE)
    assert probe.fp is not None
    fp = probe.fp

    data = _read_block(fp, 4, False)
    assert data == b"0123"
    assert not fp.closed

    data = _read_block(fp, 4, False)
    assert data == b"4567"
    assert not fp.closed

    data = _read_block(fp, 2, True)
    assert data == b"89"
    assert fp.closed


def test_read_block_seek_positions_read(tmp_path: Path) -> None:
    target = tmp_path / "rs.bin"
    target.write_bytes(b"0123456789")
    probe = _stat_open_tmp(target, RESPONSE_DATA_BLOCK_SIZE)
    assert probe.fp is not None
    fp = probe.fp

    data = _read_block(fp, 3, True, seek_to=5)

    assert data == b"567"
    assert fp.closed


# ---- unit: GET body generator (probe-seeded, ledgered) ----


def make_plain_probe(target: Path) -> _FileProbe:
    return _stat_open_read_block(target, RESPONSE_DATA_BLOCK_SIZE)


@pytest.mark.asyncio
async def test_body_generator_chunk_parity(tmp_path: Path) -> None:
    # ledgered chunking: no trailing empty chunk for block-multiple
    # files (aligned with the memory provider generator)
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    probe = make_plain_probe(empty)
    chunks = [(d, m) async for d, m in _dav_response_body_generator(probe, 0)]
    assert chunks == [(b"", False)]

    small = tmp_path / "small.bin"
    small.write_bytes(b"tiny")
    probe = make_plain_probe(small)
    chunks = [(d, m) async for d, m in _dav_response_body_generator(probe, 4)]
    assert chunks == [(b"tiny", False)]

    exact = tmp_path / "exact.bin"
    exact.write_bytes(b"x" * RESPONSE_DATA_BLOCK_SIZE)
    probe = make_plain_probe(exact)
    chunks = [
        (d, m)
        async for d, m in _dav_response_body_generator(probe, RESPONSE_DATA_BLOCK_SIZE)
    ]
    assert chunks == [(b"x" * RESPONSE_DATA_BLOCK_SIZE, False)]


@pytest.mark.asyncio
async def test_body_generator_range_within_block(tmp_path: Path) -> None:
    from asgi_webdav.constants import DAVRangeType, DAVResponseContentRange

    target = tmp_path / "r.bin"
    target.write_bytes(b"0123456789")
    content_range = DAVResponseContentRange(DAVRangeType.RANGE, 2, 5, 10)

    probe = await _stat_open_tmp_async(target, RESPONSE_DATA_BLOCK_SIZE)
    chunks = [
        (d, m) async for d, m in _dav_response_body_generator(probe, 10, content_range)
    ]

    assert chunks == [(b"2345", False)]


@pytest.mark.asyncio
async def test_probe_cancel_drains_and_closes_fp(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    target = tmp_path / "c.bin"
    target.write_bytes(b"x" * (RESPONSE_DATA_BLOCK_SIZE * 2))
    opened: list[BinaryIO] = []
    real = _stat_open_read_block

    async def slow_probe(*args: Any) -> _FileProbe:
        await asyncio.sleep(0.05)
        probe = real(*args)
        if probe.fp is not None:
            opened.append(probe.fp)
        return probe

    mocker.patch(
        "asgi_webdav.provider.file_system._stat_open_read_block_async",
        side_effect=slow_probe,
    )
    task = asyncio.ensure_future(_run_probe(target, False, RESPONSE_DATA_BLOCK_SIZE))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert opened
    assert opened[0].closed


@pytest.mark.asyncio
async def test_probe_second_cancellation_still_closes(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    target = tmp_path / "c2.bin"
    target.write_bytes(b"x" * (RESPONSE_DATA_BLOCK_SIZE * 2))
    opened: list[BinaryIO] = []
    real = _stat_open_read_block

    async def slow_probe(*args: Any) -> _FileProbe:
        await asyncio.sleep(0.05)
        probe = real(*args)
        if probe.fp is not None:
            opened.append(probe.fp)
        return probe

    mocker.patch(
        "asgi_webdav.provider.file_system._stat_open_read_block_async",
        side_effect=slow_probe,
    )
    task = asyncio.ensure_future(_run_probe(target, False, RESPONSE_DATA_BLOCK_SIZE))
    await asyncio.sleep(0.01)
    task.cancel()  # first delivery — the drain begins
    await asyncio.sleep(0.005)
    task.cancel()  # second delivery lands inside the drain
    with pytest.raises(asyncio.CancelledError):
        await task

    # the task ends cancelled before the executor hop completes; the
    # reaper closes the fp when the hop finishes
    await asyncio.sleep(0.08)
    assert opened
    assert opened[0].closed


@pytest.mark.asyncio
async def test_probe_cancel_with_failing_worker(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # cancel during a probe whose worker fails: the reaper sees the
    # exception and takes no closing action
    async def slow_fail(*args: Any) -> _FileProbe:
        await asyncio.sleep(0.05)
        raise OSError(errno.ENOENT, "gone")

    mocker.patch(
        "asgi_webdav.provider.file_system._stat_open_read_block_async",
        side_effect=slow_fail,
    )
    task = asyncio.ensure_future(
        _run_probe(tmp_path / "x.bin", False, RESPONSE_DATA_BLOCK_SIZE)
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.08)  # let the hop finish under the reaper


@pytest.mark.asyncio
async def test_body_generator_aclose_closes_fp(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    target = tmp_path / "m.bin"
    target.write_bytes(b"x" * (RESPONSE_DATA_BLOCK_SIZE * 2))
    opened: list[BinaryIO] = []
    real = _stat_open_read_block

    async def capture_probe(*args: Any) -> _FileProbe:
        probe = real(*args)
        if probe.fp is not None:
            opened.append(probe.fp)
        return probe

    mocker.patch(
        "asgi_webdav.provider.file_system._stat_open_read_block_async",
        side_effect=capture_probe,
    )
    provider = make_fs_provider(tmp_path)
    status, _, body, _ = await provider._do_get(make_get_request("/m.bin"))
    assert status == 200
    assert body is not None
    _, more_body = await body.__anext__()
    assert more_body is True

    await body.aclose()

    assert opened
    assert opened[0].closed


@pytest.mark.asyncio
async def test_do_get_range_unsatisfiable_closes_probe_fp(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # the ranged probe opens the fp before the range is judged: the
    # 416 branch must close it explicitly
    provider = make_fs_provider(tmp_path)
    target = tmp_path / "r416.bin"
    target.write_bytes(b"0123456789")
    mock_fp = mocker.MagicMock()
    mock_fp.closed = False

    async def fake_probe_ranged(*args: Any) -> _FileProbe:
        return _FileProbe(target.stat(), mock_fp, b"")

    mocker.patch(
        "asgi_webdav.provider.file_system._stat_open_tmp_async",
        side_effect=fake_probe_ranged,
    )
    request = make_get_request("/r416.bin", headers=[(b"range", b"bytes=999999-")])
    status, _, body, _ = await provider._do_get(request)

    assert status == 416
    assert body is None
    mock_fp.close.assert_called_once()


@pytest.mark.asyncio
async def test_do_get_if_range_mismatch_closes_probe_fp_and_reprobes(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    provider = make_fs_provider(tmp_path)
    target = tmp_path / "irm.bin"
    target.write_bytes(b"0123456789")
    mock_fp = mocker.MagicMock()
    mock_fp.closed = False

    async def fake_probe_ranged(*args: Any) -> _FileProbe:
        return _FileProbe(target.stat(), mock_fp, b"")

    mocker.patch(
        "asgi_webdav.provider.file_system._stat_open_tmp_async",
        side_effect=fake_probe_ranged,
    )
    request = make_get_request(
        "/irm.bin", headers=[(b"range", b"bytes=2-5"), (b"if-range", b'"nope"')]
    )
    status, _, body, content_range = await provider._do_get(request)

    # validator mismatch: ignore Range, respond the entire file — the
    # ranged probe's fp is closed and a plain probe re-reads the file
    assert status == 200
    assert content_range is None
    assert mock_fp.close.called is True
    assert body is not None
    chunks = [d async for d, _ in body]
    assert b"".join(chunks) == b"0123456789"


@pytest.mark.asyncio
async def test_body_generator_close_oserror_suppressed(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # a failing close (in the ledgered last read, then in the
    # finalization) must not turn into an unexpected error
    target = tmp_path / "oe.bin"
    block = b"x" * RESPONSE_DATA_BLOCK_SIZE
    target.write_bytes(block * 2)
    mock_fp = mocker.MagicMock()
    mock_fp.closed = False
    mock_fp.read.side_effect = [block, b""]
    mock_fp.close.side_effect = [None, OSError(errno.EIO, "close io")]

    probe = _FileProbe(target.stat(), mock_fp, block)
    chunks = [
        (d, m) async for d, m in _dav_response_body_generator(probe, 2 * len(block))
    ]

    assert chunks == [(block, True), (block, False)]
    assert mock_fp.close.call_count == 2


def test_stat_open_tmp_missing(tmp_path: Path) -> None:
    probe = _stat_open_tmp(tmp_path / "nope", RESPONSE_DATA_BLOCK_SIZE)
    assert probe.stat_result is None
    assert probe.fp is None


def test_stat_open_tmp_dir_never_opens(tmp_path: Path) -> None:
    a_dir = tmp_path / "d"
    a_dir.mkdir()
    probe = _stat_open_tmp(a_dir, RESPONSE_DATA_BLOCK_SIZE)
    assert probe.stat_result is not None
    assert probe.fp is None


def test_stat_open_tmp_open_race_maps_missing(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    target = tmp_path / "race.bin"
    target.write_bytes(b"data")

    real_open = builtins.open

    def open_but_vanished(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if Path(file) == target:
            raise FileNotFoundError(errno.ENOENT, "gone")
        return real_open(file, mode, *args, **kwargs)

    mocker.patch("builtins.open", side_effect=open_but_vanished)

    probe = _stat_open_tmp(target, RESPONSE_DATA_BLOCK_SIZE)

    assert probe.stat_result is None
    assert probe.fp is None


def test_read_block_read_failure_self_heals(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    target = tmp_path / "io.bin"
    target.write_bytes(b"data")
    mock_fp = mocker.MagicMock()
    mock_fp.read.side_effect = OSError(errno.EIO, "io")
    mocker.patch("builtins.open", return_value=mock_fp)

    with pytest.raises(OSError):
        _read_block(mock_fp, RESPONSE_DATA_BLOCK_SIZE, False)

    mock_fp.close.assert_called_once()


@pytest.mark.asyncio
async def test_body_generator_do_get_ranged_missing_404(tmp_path: Path) -> None:
    # ranged GET on a missing file goes through the ranged probe's
    # missing sentinel
    provider = make_fs_provider(tmp_path)
    request = make_get_request("/no_such_file", headers=[(b"range", b"bytes=0-3")])
    status, _, body, _ = await provider._do_get(request)

    assert status == 404
    assert body is None


@pytest.mark.asyncio
async def test_body_generator_do_get_ranged_dir_200(tmp_path: Path) -> None:
    # ranged GET on a directory: the probe never opens, the dir branch
    # answers without a body
    provider = make_fs_provider(tmp_path)
    (tmp_path / "d").mkdir()
    request = make_get_request("/d", headers=[(b"range", b"bytes=0-3")])
    status, basic_data, body, _ = await provider._do_get(request)

    assert status == 200
    assert basic_data is not None
    assert basic_data.is_collection is True
    assert body is None


@pytest.mark.asyncio
async def test_body_generator_plain_truncation_race_breaks(
    tmp_path: Path,
) -> None:
    # file_size larger than the real content: the ledger reads past EOF,
    # the short read ends the stream cleanly and closes the fp
    target = tmp_path / "shrink.bin"
    block = b"x" * RESPONSE_DATA_BLOCK_SIZE
    target.write_bytes(block * 2)

    probe = _stat_open_read_block(target, RESPONSE_DATA_BLOCK_SIZE)
    assert probe.fp is not None
    fp = probe.fp

    chunks = [
        (d, m) async for d, m in _dav_response_body_generator(probe, 3 * len(block))
    ]

    assert chunks[-1][1] is False
    assert fp.closed


@pytest.mark.asyncio
async def test_body_generator_range_truncation_race_breaks(
    tmp_path: Path,
) -> None:
    # a range spanning past the real content ends on the short read
    from asgi_webdav.constants import DAVRangeType, DAVResponseContentRange

    target = tmp_path / "shrink-r.bin"
    target.write_bytes(b"0123456789")
    content_range = DAVResponseContentRange(DAVRangeType.RANGE, 0, 99, 100)

    probe = await _stat_open_tmp_async(target, RESPONSE_DATA_BLOCK_SIZE)
    chunks = [
        (d, m) async for d, m in _dav_response_body_generator(probe, 100, content_range)
    ]

    assert b"".join(d for d, _ in chunks) == b"0123456789"
    assert chunks[-1][1] is False


@pytest.mark.asyncio
async def test_body_generator_range_none_fp_returns(tmp_path: Path) -> None:
    # defensive guard: a dir/missing probe with a range yields nothing
    from asgi_webdav.constants import DAVRangeType, DAVResponseContentRange

    content_range = DAVResponseContentRange(DAVRangeType.RANGE, 0, 9, 10)
    probe = _FileProbe(None, None, b"")

    chunks = [
        (d, m) async for d, m in _dav_response_body_generator(probe, 10, content_range)
    ]

    assert chunks == []


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


# ---- unit: PUT buffered write helpers ----


def test_put_precheck_statuses(tmp_path: Path) -> None:
    # target is a dir -> 405
    target_dir = tmp_path / "a_dir"
    target_dir.mkdir()
    assert _put_precheck(target_dir) == _PutPrecheckResult(405, True)

    # missing target, parent exists -> ok, create
    assert _put_precheck(tmp_path / "new_file") == _PutPrecheckResult(None, False)

    # dangling symlink target -> stat fails, treated as create
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "never_existed")
    assert _put_precheck(dangling) == _PutPrecheckResult(None, False)

    # missing parent -> 409
    assert _put_precheck(tmp_path / "no_such_dir" / "f") == _PutPrecheckResult(
        409, False
    )

    # parent exists but is a file -> 409
    parent_file = tmp_path / "a_file"
    parent_file.write_bytes(b"data")
    assert _put_precheck(parent_file / "child") == _PutPrecheckResult(409, False)


def test_put_error_status_mapping(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fs_path = tmp_path / "t.bin"
    assert _put_error_status(PermissionError(), fs_path) == 403
    assert _put_error_status(OSError(errno.ENOSPC, "no space"), fs_path) == 507
    assert _put_error_status(OSError(errno.EIO, "i/o"), fs_path) == 500
    assert _put_error_status(OSError("no errno"), fs_path) == 500

    # only the unexpected-500 arm leaves a diagnostic behind
    with caplog.at_level(logging.ERROR, logger="asgi_webdav.provider.file_system"):
        _put_error_status(OSError(errno.EIO, "i/o"), fs_path)
    assert any("PUT write failed" in record.message for record in caplog.records)


def test_write_all_handles_partial_writes(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # os.write may accept fewer bytes than handed — the loop must keep
    # pushing the remainder
    real_write = os.write
    written: list[bytes] = []

    def one_byte_write(fd: int, data: "bytes | bytearray | memoryview") -> int:
        view = memoryview(data)
        written.append(bytes(view[:1]))
        return real_write(fd, bytes(view[:1]))

    mocker.patch("os.write", side_effect=one_byte_write)

    target = tmp_path / "partial.bin"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT, 0o666)
    try:
        _write_all(fd, b"chunked!")
    finally:
        os.close(fd)

    assert b"".join(written) == b"chunked!"
    assert target.read_bytes() == b"chunked!"


def test_open_tmp_exclusive_names(tmp_path: Path) -> None:
    fs_path = tmp_path / "target.bin"
    fd, tmp_path_created = _open_tmp_exclusive(fs_path)
    try:
        os.write(fd, b"x")
    finally:
        os.close(fd)

    assert tmp_path_created.parent == tmp_path
    assert tmp_path_created.name.startswith("target.bin.")
    assert tmp_path_created.name.endswith(".davtmp")
    assert tmp_path_created.read_bytes() == b"x"


def test_write_file_atomic_create_and_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "atomic.bin"

    # create -> 201
    assert _write_file_atomic(target, [b"first-", b"second"]) == 201
    assert target.read_bytes() == b"first-second"

    # overwrite -> 204, previous content fully replaced
    assert _write_file_atomic(target, [b"next"]) == 204
    assert target.read_bytes() == b"next"

    # empty body creates an empty file
    assert _write_file_atomic(tmp_path / "empty.bin", []) == 201
    assert (tmp_path / "empty.bin").read_bytes() == b""


@pytest.mark.asyncio
async def test_open_tmp_stream_collision_retry(tmp_path: Path) -> None:
    f, tmp_created = await _open_tmp_stream(tmp_path / "t.bin")
    await f.close()
    assert tmp_created.name.startswith("t.bin.")
    assert tmp_created.name.endswith(".davtmp")


@pytest.mark.asyncio
async def test_open_tmp_stream_cancellation_drains(tmp_path: Path) -> None:
    # a cancellation during the executor open still drains the result: the
    # descriptor closes and the partial temp is removed before the
    # CancelledError propagates
    task = asyncio.create_task(_open_tmp_stream(tmp_path / "t.bin"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.glob("*.davtmp"))


@pytest.mark.asyncio
async def test_open_tmp_stream_cancellation_with_failing_open(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # the drain must also hold when the executor open fails while the
    # cancellation is being delivered
    async def failing_open(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.05)
        raise PermissionError()

    mocker.patch("aiofiles.open", side_effect=failing_open)
    task = asyncio.create_task(_open_tmp_stream(tmp_path / "t.bin"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.glob("*.davtmp"))


@pytest.mark.asyncio
async def test_open_tmp_stream_second_cancellation_still_cleans(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    # a second cancellation delivered while the drain awaits (double-cancel
    # delivery, anyio-style scopes) must not skip the temp removal
    real_open = aiofiles.open

    async def slow_open(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.05)
        return await real_open(*args, **kwargs)

    mocker.patch("aiofiles.open", side_effect=slow_open)
    task = asyncio.create_task(_open_tmp_stream(tmp_path / "t.bin"))
    await asyncio.sleep(0.01)  # the handler suspends on the shield await
    task.cancel()  # first delivery — the drain begins
    await asyncio.sleep(0.005)  # the drain is now awaiting the inner task
    task.cancel()  # second delivery lands inside the drain
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.glob("*.davtmp"))
