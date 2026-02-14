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


def test_DAVTime_from_milliseconds():
    """测试从毫秒时间戳创建 DAVTime 实例"""
    # 测试 0 毫秒，对应 Unix 纪元
    dt = DAVTime.from_milliseconds(0.0)
    assert isinstance(dt, DAVTime)
    assert dt.timestamp == 0.0
    assert dt.iso_8601 == "1970-01-01T00:00:00+00:00"

    # 测试 1 秒（1,000 毫秒）
    dt = DAVTime.from_milliseconds(1000.0)
    assert dt.timestamp == 1.0
    assert dt.iso_8601 == "1970-01-01T00:00:01+00:00"

    # 测试负毫秒值（1970 年之前的时间）
    dt = DAVTime.from_milliseconds(-1000.0)
    assert dt.timestamp == -1.0
    assert dt.iso_8601 == "1969-12-31T23:59:59+00:00"

    # 测试浮点数毫秒值（带小数部分）
    dt = DAVTime.from_milliseconds(1500.5)
    assert dt.timestamp == 1.5005  # 1.5 秒 + 0.5 毫秒

    # 验证通过 from_milliseconds 创建的实例与直接使用秒级时间戳创建的实例行为一致
    milliseconds = 2123.456
    dt_from_milli = DAVTime.from_milliseconds(milliseconds)
    dt_from_seconds = DAVTime(milliseconds / 1000)
    assert dt_from_milli.timestamp == dt_from_seconds.timestamp
    assert dt_from_milli.iso_8601 == dt_from_seconds.iso_8601

    # 可选：验证其他格式化属性，如 http_date, w3c 等
    assert dt_from_milli.http_date == dt_from_seconds.http_date
    assert dt_from_milli.w3c == dt_from_seconds.w3c


def test_DAVTime_from_microseconds():
    """测试从微秒时间戳创建 DAVTime 实例"""
    # 测试 0 微秒，对应 Unix 纪元
    dt = DAVTime.from_microseconds(0.0)
    assert isinstance(dt, DAVTime)
    assert dt.timestamp == 0.0
    assert dt.iso_8601 == "1970-01-01T00:00:00+00:00"

    # 测试 1 秒（1,000,000 微秒）
    dt = DAVTime.from_microseconds(1_000_000.0)
    assert dt.timestamp == 1.0
    # 验证转换后的日期时间字符串
    assert dt.iso_8601 == "1970-01-01T00:00:01+00:00"

    # 测试负微秒值（1970 年之前的时间）
    dt = DAVTime.from_microseconds(-1_000_000.0)
    assert dt.timestamp == -1.0
    assert dt.iso_8601 == "1969-12-31T23:59:59+00:00"

    # 测试浮点数微秒值（带小数部分）
    dt = DAVTime.from_microseconds(1_500_000.5)
    assert dt.timestamp == 1.5000005  # 1.5 秒 + 0.5 微秒
    # 注意：isoformat() 可能只显示到微秒精度

    # 验证通过 from_microseconds 创建的实例与直接使用秒级时间戳创建的实例行为一致
    microseconds = 2_123_456.789
    dt_from_micro = DAVTime.from_microseconds(microseconds)
    dt_from_seconds = DAVTime(microseconds / 1_000_000)
    assert dt_from_micro.timestamp == dt_from_seconds.timestamp
    assert dt_from_micro.iso_8601 == dt_from_seconds.iso_8601
