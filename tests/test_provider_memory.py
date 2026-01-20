import pytest

from asgi_webdav.constants import DAVPath
from asgi_webdav.provider.memory import MemoryFS

root_path = DAVPath("/")
p1_path = root_path.add_child("p1")

file_content_1 = b"file content 1"
file_content_2 = b"file content 2"


@pytest.fixture
def fs():
    """default FS"""
    fs = MemoryFS(root_path)
    fs.add_node(DAVPath("/f1"), content=file_content_1)
    fs.add_node(DAVPath("/f2"), content=file_content_2)
    fs.add_node(p1_path)
    fs.add_node(p1_path.add_child("f1_1"), content=file_content_1)
    fs.add_node(p1_path.add_child("f1_2"), content=file_content_2)

    return fs


def test_memory_fs_basic(fs):
    assert fs.has_node(DAVPath("/"))
    assert fs.has_node(DAVPath("/f1"))
    assert fs.has_node(DAVPath("/f2"))
    assert fs.has_node(DAVPath("/p1"))
    assert fs.has_node(DAVPath("/p1/f1_1"))
    assert fs.has_node(DAVPath("/p1/f1_2"))

    assert not fs.has_node(DAVPath("/xxx"))

    assert fs.get_node(DAVPath("/f1")).content == file_content_1
    assert fs.get_node(DAVPath("/f2")).content == file_content_2

    assert fs.has_child(DAVPath("/"), "f1")
    assert fs.has_child(DAVPath("/"), "p1")

    assert fs.has_child(DAVPath("/p1"), "f1_1")
    assert fs.has_child(DAVPath("/p1"), "f1_2")

    assert len(fs.get_node_children(fs.get_node(DAVPath("/")))) == 3
    assert len(fs.get_node_children(fs.get_node(DAVPath("/p1")))) == 2


def test_delete_one(fs):
    assert not fs.has_node(DAVPath("/p1/xxx"))

    assert fs.del_node(fs.get_node(DAVPath("/p1/f1_1")))
    assert not fs.has_node(DAVPath("/p1/f1_1"))
    assert len(fs.get_node_children(fs.get_node(DAVPath("/p1")))) == 1

    assert fs.del_node(fs.get_node(DAVPath("/p1/f1_2")))
    assert len(fs.get_node_children(fs.get_node(DAVPath("/p1")))) == 0

    assert fs.del_node(fs.get_node(DAVPath("/p1")))
    assert not fs.has_node(DAVPath("/p1"))

    assert fs.del_node(fs.get_node(DAVPath("/f1")))
    assert fs.del_node(fs.get_node(DAVPath("/f2")))
    assert len(fs.get_node_children(fs.get_node(DAVPath("/")))) == 0

    with pytest.raises(KeyError):
        fs.del_node(fs.get_node(DAVPath("/")))


def test_delete_tree(fs):
    assert fs.del_node(fs.get_node(DAVPath("/p1")))
    assert not fs.has_node(DAVPath("/p1"))
    assert not fs.has_node(DAVPath("/p1/f1_1"))
    assert not fs.has_node(DAVPath("/p1/f1_2"))


def test_get_node_children(fs):
    assert len(fs.get_node_children(fs.get_node(DAVPath("/")))) == 3
    assert len(fs.get_node_children(fs.get_node(DAVPath("/p1")))) == 2
    assert len(fs.get_node_children(fs.get_node(DAVPath("/p1/f1_1")))) == 0

    assert len(fs.get_node_children(fs.get_node(DAVPath("/")), recursive=True)) == 5
