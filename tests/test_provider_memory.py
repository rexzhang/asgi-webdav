import pytest

from asgi_webdav.constants import DAVPath
from asgi_webdav.provider.memory import MemoryFS, MemoryFSNode

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
