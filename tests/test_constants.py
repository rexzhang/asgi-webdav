from zoneinfo import ZoneInfo

import pytest
from icecream import ic

from asgi_webdav.constants import DAVPath, DAVTime
from asgi_webdav.exceptions import DAVCodingError


def test_DAVPath_basic():
    path = DAVPath("/a/b/c")

    assert path.raw == "/a/b/c"
    assert path.parts == ["a", "b", "c"]
    assert path.parts_count == 3
    assert path.parent == DAVPath("/a/b")
    assert path.name == "c"
    assert path.get_child(DAVPath("/a/b")) == DAVPath("/c")
    assert path.add_child("d") == DAVPath("/a/b/c/d")
    assert path.add_child(DAVPath("/d/e")) == DAVPath("/a/b/c/d/e")

    path = DAVPath("/")
    assert path.raw == "/"

    path = DAVPath()
    assert path.raw == "/"


def test_DAVPathis_parent_of():
    path = DAVPath("/a/b/c")

    # is_parent_of()
    assert path.is_parent_of(DAVPath("/a/b/c/d"))
    assert path.is_parent_of(DAVPath("/a/b/c/d/e"))

    assert path.is_parent_of(DAVPath("/a/b/c")) is False
    assert path.is_parent_of(DAVPath("/a/b")) is False

    assert path.is_parent_of(DAVPath("/x/b/c/d/")) is False

    # ---
    assert path.is_parent_of(DAVPath("/x/b/cd")) is False

    # is_parent_of_or_is_self()
    assert path.is_parent_of_or_is_self(DAVPath("/a/b/c")) is True
    assert path.is_parent_of_or_is_self(DAVPath("/a/b/c/d")) is True
    assert path.is_parent_of_or_is_self(DAVPath("/a/b/cd")) is False

    assert path.is_parent_of_or_is_self(DAVPath("/a/bc")) is False


def test_DAVPathis_parent_of_extra():
    path = DAVPath("/")

    assert path.is_parent_of(DAVPath("/a")) is True
    assert path.is_parent_of(DAVPath("/a/b")) is True

    assert path.is_parent_of_or_is_self(DAVPath("/")) is True
    assert path.is_parent_of_or_is_self(DAVPath("/a")) is True
    assert path.is_parent_of_or_is_self(DAVPath("/a/b")) is True


def test_DAVPath_init_ext():
    assert DAVPath(b"/a/b/c") == DAVPath("/a/b/c")

    assert DAVPath("/a/b/c") == DAVPath("a/b/c") == DAVPath("/a/b/c/")

    with pytest.raises(ValueError):
        path = DAVPath("a/   /c")
        ic(path.parts)

    with pytest.raises(DAVCodingError):
        DAVPath(1)

    with pytest.raises(ValueError):
        DAVPath("./b/c")

    with pytest.raises(ValueError):
        DAVPath("../b/c")


def test_DAVPath_method():
    assert DAVPath("/a/b/c").parent == DAVPath("/a/b")
    assert DAVPath("/a").parent == DAVPath("/")
    assert DAVPath("/").parent == DAVPath("/")

    assert DAVPath("/a/b/c").name == "c"
    assert DAVPath("/").name == "/"

    assert DAVPath("/a/b/c").get_child(DAVPath("/a/b")) == DAVPath("/c")

    assert DAVPath("/a/b/c").add_child("d") == DAVPath("/a/b/c/d")


def test_DAVPath_magic_method():
    # hash
    data = {DAVPath("/a/b/c"): 1}
    assert data[DAVPath("/a/b/c")] == 1

    # ==
    assert DAVPath("/a/b/c") == DAVPath("/a/b/c")
    assert DAVPath("/a/b/c") != DAVPath("/a/b/cd")
    assert DAVPath("/a/b/c") != "/a/b/c"

    # <
    assert DAVPath("/a/b/c") < DAVPath("/a/b/c/d")

    # <=
    assert DAVPath("/a/b/c") <= DAVPath("/a/b/c")
    assert DAVPath("/a/b/c") < DAVPath("/a/b/c/d")

    # >
    assert DAVPath("/a/b/c/d") > DAVPath("/a/b/c")

    # >=
    assert DAVPath("/a/b/c") >= DAVPath("/a/b/c")
    assert DAVPath("/a/b/c/d") > DAVPath("/a/b/c")


def test_DAVTime():
    timezone_shanghai = ZoneInfo("Asia/Shanghai")

    dt = DAVTime(0.0)
    str(dt)
    assert dt.timestamp == 0.0
    assert dt.iso_8601 == "1970-01-01T00:00:00+00:00"
    assert dt.w3c == "1970-01-01 00:00:00+00:00"
    assert dt.http_date == "Thu, 01 Jan 1970 00:00:00 GMT"
    assert dt.display(timezone_shanghai) == "1970-01-01 08:00:00+08:00"
