from pathlib import Path

import pytest

from asgi_webdav.config import Config
from asgi_webdav.constants import DAVDepth, DAVPath, DAVTime, DAVUser
from asgi_webdav.property import DAVPropertyBasicData
from asgi_webdav.provider.memory import MemoryFS, MemoryFSNode, MemoryProvider

from .kits.asgi import create_dav_request_object

root_path = DAVPath("/")
p1_path = root_path.add_child("p1")

file_content_1 = b"file content 1"
file_content_2 = b"file content 2"


def get_node_or_fail(fs: MemoryFS, path: DAVPath) -> MemoryFSNode:
    node = fs.get_node(path)
    assert node is not None
    return node


@pytest.fixture
def fs() -> MemoryFS:
    """default FS"""
    fs = MemoryFS(root_path)
    fs.add_node(DAVPath("/f1"), content=file_content_1)
    fs.add_node(DAVPath("/f2"), content=file_content_2)
    fs.add_node(p1_path)
    fs.add_node(p1_path.add_child("f1_1"), content=file_content_1)
    fs.add_node(p1_path.add_child("f1_2"), content=file_content_2)

    return fs


def test_memory_fs_basic(fs: MemoryFS) -> None:
    assert fs.has_node(DAVPath("/"))
    assert fs.has_node(DAVPath("/f1"))
    assert fs.has_node(DAVPath("/f2"))
    assert fs.has_node(DAVPath("/p1"))
    assert fs.has_node(DAVPath("/p1/f1_1"))
    assert fs.has_node(DAVPath("/p1/f1_2"))

    assert not fs.has_node(DAVPath("/xxx"))

    assert get_node_or_fail(fs, DAVPath("/f1")).content == file_content_1
    assert get_node_or_fail(fs, DAVPath("/f2")).content == file_content_2

    assert fs.has_child(DAVPath("/"), "f1")
    assert fs.has_child(DAVPath("/"), "p1")

    assert fs.has_child(DAVPath("/p1"), "f1_1")
    assert fs.has_child(DAVPath("/p1"), "f1_2")

    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/")))) == 3
    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/p1")))) == 2


def test_delete_one(fs: MemoryFS) -> None:
    assert not fs.has_node(DAVPath("/p1/xxx"))

    assert fs.del_node(get_node_or_fail(fs, DAVPath("/p1/f1_1")))
    assert not fs.has_node(DAVPath("/p1/f1_1"))
    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/p1")))) == 1

    assert fs.del_node(get_node_or_fail(fs, DAVPath("/p1/f1_2")))
    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/p1")))) == 0

    assert fs.del_node(get_node_or_fail(fs, DAVPath("/p1")))
    assert not fs.has_node(DAVPath("/p1"))

    assert fs.del_node(get_node_or_fail(fs, DAVPath("/f1")))
    assert fs.del_node(get_node_or_fail(fs, DAVPath("/f2")))
    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/")))) == 0

    with pytest.raises(KeyError):
        fs.del_node(get_node_or_fail(fs, DAVPath("/")))


def test_delete_tree(fs: MemoryFS) -> None:
    assert fs.del_node(get_node_or_fail(fs, DAVPath("/p1")))
    assert not fs.has_node(DAVPath("/p1"))
    assert not fs.has_node(DAVPath("/p1/f1_1"))
    assert not fs.has_node(DAVPath("/p1/f1_2"))


def test_get_node_children(fs: MemoryFS) -> None:
    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/")))) == 3
    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/p1")))) == 2
    assert len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/p1/f1_1")))) == 0

    assert (
        len(fs.get_node_children(get_node_or_fail(fs, DAVPath("/")), recursive=True))
        == 5
    )


# ---- defect regressions: collection COPY/MOVE subtree integrity ----


def _make_tree(fs: MemoryFS) -> None:
    # tree: /tree + /tree/sub + /tree/file1 + /tree/sub/file2
    fs.add_node(DAVPath("/tree"))
    fs.add_node(DAVPath("/tree/sub"))
    fs.add_node(DAVPath("/tree/file1"), content=b"file1")
    fs.add_node(DAVPath("/tree/sub/file2"), content=b"file2")


def test_move_collection_with_subdir_keeps_contents() -> None:
    # RFC 4918 9.9.2: MOVE is always recursive — a subdirectory must travel
    # with its contents (the non-recursive move_tree call emptied it)
    fs = MemoryFS(root_path)
    _make_tree(fs)

    src_node = get_node_or_fail(fs, DAVPath("/tree"))
    assert fs.move_node(
        src_node=src_node,
        src_node_parent=get_node_or_fail(fs, DAVPath("/")),
        dst_path=DAVPath("/moved"),
        dst_node_parent=get_node_or_fail(fs, DAVPath("/")),
    )

    assert not fs.has_node(DAVPath("/tree"))
    moved_file = fs.get_node(DAVPath("/moved/sub/file2"))
    assert moved_file is not None
    assert moved_file.content == b"file2"


def test_copy_collection_children_keep_own_properties() -> None:
    # RFC 4918 9.8.3: copied child resources keep their own properties (the
    # old code deep-copied the collection's basic data onto every child)
    fs = MemoryFS(root_path)
    _make_tree(fs)

    src_node = get_node_or_fail(fs, DAVPath("/tree"))
    assert fs.copy_node(
        src_node=src_node,
        dst_path=DAVPath("/copied"),
        dst_node_parent=get_node_or_fail(fs, DAVPath("/")),
        depth=DAVDepth.INFINITY,
    )

    child = fs.get_node(DAVPath("/copied/file1"))
    assert child is not None
    assert child.property_basic_data.display_name == "file1"
    assert child.content == b"file1"


# ---- unit: small branches (defensive returns) ----


def test_add_node_raises_without_parent() -> None:
    fs = MemoryFS(root_path)

    with pytest.raises(ValueError):
        fs.add_node(dst_node_path=DAVPath("/no_parent/orphan"))


def test_has_child_missing_path_false() -> None:
    fs = MemoryFS(root_path)

    assert fs.has_child(DAVPath("/no_such_dir"), "child") is False


def test_del_node_detached_node_false() -> None:
    fs = MemoryFS(root_path)
    detached = MemoryFSNode(
        node_path=DAVPath("/no_parent/detached"),
        is_file=True,
        property_basic_data=DAVPropertyBasicData(
            is_collection=False,
            display_name="detached",
            creation_date=DAVTime(),
            last_modified=DAVTime(),
        ),
        property_extra_data={},
        content=b"",
    )

    assert fs.del_node(detached) is False


def test_copy_node_dst_exists_no_overwrite_false() -> None:
    fs = MemoryFS(root_path)
    _make_tree(fs)
    fs.add_node(DAVPath("/dst"), content=b"original")

    src_node = get_node_or_fail(fs, DAVPath("/tree/file1"))
    assert (
        fs.copy_node(
            src_node=src_node,
            dst_path=DAVPath("/dst"),
            dst_node_parent=get_node_or_fail(fs, DAVPath("/")),
            depth=DAVDepth.INFINITY,
            overwrite=False,
        )
        is False
    )

    dst_node = get_node_or_fail(fs, DAVPath("/dst"))
    assert dst_node.content == b"original"


def test_move_node_dst_exists_no_overwrite_false() -> None:
    fs = MemoryFS(root_path)
    _make_tree(fs)
    fs.add_node(DAVPath("/dst"), content=b"original")

    src_node = get_node_or_fail(fs, DAVPath("/tree/file1"))
    assert (
        fs.move_node(
            src_node=src_node,
            src_node_parent=get_node_or_fail(fs, DAVPath("/tree")),
            dst_path=DAVPath("/dst"),
            dst_node_parent=get_node_or_fail(fs, DAVPath("/")),
            overwrite=False,
        )
        is False
    )

    # the source stayed, the destination kept its content
    assert fs.has_node(DAVPath("/tree/file1"))
    dst_node = get_node_or_fail(fs, DAVPath("/dst"))
    assert dst_node.content == b"original"


async def test_get_res_etag_missing_node_returns_empty(tmp_path: Path) -> None:
    provider = MemoryProvider(
        config=Config(),
        prefix=DAVPath("/memory"),
        uri="memory:///",
        home_dir=False,
        read_only=False,
        ignore_property_extra=False,
    )

    assert (
        await provider._get_res_etag_from_res_dist_path(DAVPath("/no_such_file")) == ""
    )


# ---- defect regressions: collection COPY/MOVE subtree integrity ----


@pytest.mark.asyncio
async def test_do_mkcol_root_returns_201() -> None:
    # MKCOL on the provider root (dist path "/") answers 201 as a no-op
    provider = MemoryProvider(
        config=Config(),
        prefix=DAVPath("/memory"),
        uri="memory:///",
        home_dir=False,
        read_only=False,
        ignore_property_extra=False,
    )
    request = create_dav_request_object(method="MKCOL", path="/memory")
    request.dist_src_path = DAVPath("/")
    request.lock_ifs = []

    response = await provider.do_mkcol(request)

    assert response.status == 201


@pytest.mark.asyncio
async def test_do_proppatch_ignore_and_missing(tmp_path: Path) -> None:
    # ignore_property_extra: PROPPATCH is a no-op 207
    provider = MemoryProvider(
        config=Config(),
        prefix=DAVPath("/memory"),
        uri="memory:///",
        home_dir=False,
        read_only=False,
        ignore_property_extra=True,
    )
    request = create_dav_request_object(method="PROPPATCH", path="/no_such_file")
    request.dist_src_path = DAVPath("/no_such_file")
    request.user = DAVUser("testuser", "password", [], False)
    request.body_is_parsed_success = True
    request.proppatch_entries = [(("ns1", "key1"), "v1", True)]
    request.lock_ifs = []

    response = await provider.do_proppatch(request)
    assert response.status == 207

    # with the flag off, a PROPPATCH on a missing resource answers 404
    provider.ignore_property_extra = False
    response = await provider.do_proppatch(request)
    assert response.status == 404
