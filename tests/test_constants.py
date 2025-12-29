from zoneinfo import ZoneInfo

from asgi_webdav.constants import DAVTime


def test_DAVTime():
    timezone_shanghai = ZoneInfo("Asia/Shanghai")

    dt = DAVTime(0.0)
    str(dt)
    assert dt.timestamp == 0.0
    assert dt.iso_8601 == "1970-01-01T00:00:00+00:00"
    assert dt.w3c == "1970-01-01 00:00:00+00:00"
    assert dt.http_date == "Thu, 01 Jan 1970 00:00:00 GMT"
    assert dt.display(timezone_shanghai) == "1970-01-01 08:00:00+08:00"
