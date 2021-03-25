from asgi_webdav.constants import (
    DAVPath,
)


def test_basic():
    path = DAVPath("/a/b/c")

    assert path.raw == "/a/b/c"
    assert path.parts == ["a", "b", "c"]
    assert path.count == 3
    assert path.parent == DAVPath("/a/b")
    assert path.name == "c"
    assert path.startswith(DAVPath("/a/b"))
    assert path.get_child(DAVPath("/a/b")) == DAVPath("/c")
    assert path.add_child("d") == DAVPath("/a/b/c/d")
    assert path.add_child(DAVPath("/d/e")) == DAVPath("/a/b/c/d/e")


def test_some_error():
    path = DAVPath("/a/b/c")
    print(path.add_child("/d/e"))
    assert path.add_child("/d/e") != DAVPath("/a/b/c/de")
