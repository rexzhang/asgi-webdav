"""Unit tests for the PROPFIND 207 multistatus renderer.

All cases build DAVProperty objects directly and assert on the rendered
bytes; well-formedness is verified with xml.etree.ElementTree.
"""

import logging
from uuid import UUID
from xml.etree import ElementTree

import pytest

from asgi_webdav.constants import (
    DAV_PROPERTY_BASIC_KEYS,
    DAVDepth,
    DAVLockObj,
    DAVLockScope,
    DAVPath,
    DAVPropertyIdentity,
    DAVTime,
)
from asgi_webdav.property import (
    DAVProperty,
    DAVPropertyBasicData,
    PropfindEntry,
    render_propfind_multistatus,
)

FIXED_TIME = DAVTime(1_767225600.0)
FIXED_TOKEN = UUID("01234567-89ab-cdef-0123-456789abcdef")
XML_DECLARATION = b'<?xml version="1.0" encoding="utf-8"?>'
# generate_etag(0, 1767225600.0)
ETAG_EMPTY = 'W/"c2e6218f73b4172a22dab933c2e65f75"'
# generate_etag(4096, 1767225600.0)
ETAG_4096 = 'W/"a3564135255a2171c9f13dcbaf4787ca"'


def _make_entry(
    href: str,
    *,
    is_collection: bool = False,
    display_name: str | None = None,
    content_length: int = 0,
    content_type: str | None = None,
    extra_data: dict[DAVPropertyIdentity, str] | None = None,
    extra_not_found: list[DAVPropertyIdentity] | None = None,
    lock_obj: DAVLockObj | None = None,
) -> PropfindEntry:
    dav_property = DAVProperty(
        href_path=DAVPath(href),
        is_collection=is_collection,
        basic_data=DAVPropertyBasicData(
            is_collection=is_collection,
            display_name=display_name if display_name is not None else "name",
            creation_date=FIXED_TIME,
            last_modified=FIXED_TIME,
            content_type=content_type if content_type is not None else "",
            content_length=content_length,
        ),
        extra_data=extra_data if extra_data is not None else {},
        extra_not_found=extra_not_found if extra_not_found is not None else [],
    )
    return PropfindEntry(dav_property=dav_property, lock_obj=lock_obj)


def _make_lock(
    href: str = "/prefix/locked",
    scope: DAVLockScope = DAVLockScope.EXCLUSIVE,
) -> DAVLockObj:
    return DAVLockObj(
        owner="owner-1",
        path=DAVPath(href),
        depth=DAVDepth.INFINITY,
        token=FIXED_TOKEN,
        scope=scope,
        timeout=3600,
    )


def _parse(content: bytes) -> ElementTree.Element:
    return ElementTree.fromstring(content)


def test_render_file_allprop_exact_bytes() -> None:
    entry = _make_entry(
        "/fs/entry-0001.txt",
        display_name="entry-0001.txt",
        content_length=4096,
        content_type="text/plain",
    )

    result = render_propfind_multistatus([entry], None)

    assert result == (
        XML_DECLARATION
        + b'<D:multistatus xmlns:D="DAV:">'
        + b"<D:response><D:href>/fs/entry-0001.txt</D:href>"
        + b"<D:propstat><D:prop>"
        + b"<D:displayname>entry-0001.txt</D:displayname>"
        + f"<D:getetag>{ETAG_4096}</D:getetag>".encode()
        + b"<D:creationdate>2026-01-01T00:00:00+00:00</D:creationdate>"
        + b"<D:getlastmodified>Thu, 01 Jan 2026 00:00:00 GMT</D:getlastmodified>"
        + b"<D:getcontenttype>text/plain</D:getcontenttype>"
        + b"<D:getcontentlength>4096</D:getcontentlength>"
        + b"<D:resourcetype/>"
        + b"<D:lockdiscovery/>"
        + b"</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        + b"</D:response></D:multistatus>"
    )
    _parse(result)


def test_render_collection_allprop_exact_bytes() -> None:
    entry = _make_entry("/fs/dir", is_collection=True, display_name="dir")

    result = render_propfind_multistatus([entry], None)

    assert result == (
        XML_DECLARATION
        + b'<D:multistatus xmlns:D="DAV:">'
        + b"<D:response><D:href>/fs/dir</D:href>"
        + b"<D:propstat><D:prop>"
        + b"<D:displayname>dir</D:displayname>"
        + f"<D:getetag>{ETAG_EMPTY}</D:getetag>".encode()
        + b"<D:creationdate>2026-01-01T00:00:00+00:00</D:creationdate>"
        + b"<D:getlastmodified>Thu, 01 Jan 2026 00:00:00 GMT</D:getlastmodified>"
        + b"<D:getcontenttype>application/index</D:getcontenttype>"
        + b"<D:resourcetype><D:collection/></D:resourcetype>"
        + b"<D:lockdiscovery/>"
        + b"</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        + b"</D:response></D:multistatus>"
    )
    _parse(result)


def test_render_named_mode_deterministic_order() -> None:
    entry = _make_entry(
        "/fs/entry-0001.txt",
        display_name="entry-0001.txt",
        content_length=4096,
        content_type="text/plain",
    )
    # set input is hash-ordered; emission must follow as_dict() order
    basic_keys = {"getcontentlength", "displayname", "getlastmodified"}

    result = render_propfind_multistatus([entry], basic_keys)

    content = result.decode("utf-8")
    assert content.index("<D:displayname>") < content.index("<D:getlastmodified>")
    assert content.index("<D:getlastmodified>") < content.index("<D:getcontentlength>")
    # resourcetype is emitted only when requested in named mode
    assert b"<D:resourcetype" not in result
    # keys outside the requested set are not emitted
    assert b"<D:getetag>" not in result
    assert b"<D:creationdate>" not in result
    assert b"<D:getcontenttype>" not in result
    _parse(result)


def test_render_named_mode_resourcetype_when_requested() -> None:
    entry = _make_entry("/fs/dir", is_collection=True, display_name="dir")

    result = render_propfind_multistatus([entry], {"resourcetype"})

    assert b"<D:resourcetype><D:collection/></D:resourcetype>" in result
    assert b"<D:displayname>" not in result
    _parse(result)


def test_render_named_mode_unknown_basic_key_emits_nothing() -> None:
    entry = _make_entry("/fs/entry-0001.txt", display_name="entry-0001.txt")

    result = render_propfind_multistatus([entry], {"getcontentlanguage"})

    assert b"<D:getcontentlanguage>" not in result
    assert b"<D:displayname>" not in result
    assert b"<D:resourcetype" not in result
    _parse(result)


def test_render_extra_ns_numbering_and_root_declaration() -> None:
    entry_a = _make_entry(
        "/fs/a",
        display_name="a",
        extra_data={("http://a", "author"): "alice"},
    )
    entry_b = _make_entry(
        "/fs/b",
        display_name="b",
        extra_data={("http://b", "editor"): "bob"},
    )

    result = render_propfind_multistatus([entry_a, entry_b], None)

    assert result.count(b' xmlns:ns1="http://a"') == 1
    assert result.count(b' xmlns:ns2="http://b"') == 1
    root_start = result.index(b"<D:multistatus")
    first_response = result.index(b"<D:response>")
    # declarations live on the root element only
    assert root_start < result.index(b' xmlns:ns1="http://a"') < first_response
    assert result.index(b' xmlns:ns1="http://a"') < result.index(
        b' xmlns:ns2="http://b"'
    )
    assert b"<ns1:author>alice</ns1:author>" in result
    assert b"<ns2:editor>bob</ns2:editor>" in result
    _parse(result)


def test_render_extra_empty_ns_bare_key() -> None:
    entry = _make_entry("/fs/a", display_name="a", extra_data={("", "author"): "alice"})

    result = render_propfind_multistatus([entry], None)

    assert b"<author>alice</author>" in result
    assert b"xmlns:ns" not in result
    _parse(result)


def test_render_extra_not_found_propstat() -> None:
    entry = _make_entry(
        "/fs/a",
        display_name="a",
        extra_data={("http://a", "author"): "alice"},
        extra_not_found=[("http://b", "missing")],
    )

    result = render_propfind_multistatus([entry], None)

    assert (
        b"<D:propstat><D:prop><ns2:missing/></D:prop>"
        b"<D:status>HTTP/1.1 404 Not Found</D:status></D:propstat>" in result
    )
    _parse(result)


def test_render_extra_not_found_all_invalid_skipped() -> None:
    entry = _make_entry(
        "/fs/a",
        display_name="a",
        extra_not_found=[("http://a", "bad name"), ("http://a", "a<b")],
    )

    result = render_propfind_multistatus([entry], None)

    assert b"404 Not Found" not in result
    assert result.count(b"<D:propstat>") == 1
    _parse(result)


def test_render_lockdiscovery_exclusive_full() -> None:
    lock_obj = _make_lock(scope=DAVLockScope.EXCLUSIVE)
    entry = _make_entry("/prefix/locked", display_name="locked", lock_obj=lock_obj)

    result = render_propfind_multistatus([entry], None)

    assert result == (
        XML_DECLARATION
        + b'<D:multistatus xmlns:D="DAV:">'
        + b"<D:response><D:href>/prefix/locked</D:href>"
        + b"<D:propstat><D:prop>"
        + b"<D:displayname>locked</D:displayname>"
        + f"<D:getetag>{ETAG_EMPTY}</D:getetag>".encode()
        + b"<D:creationdate>2026-01-01T00:00:00+00:00</D:creationdate>"
        + b"<D:getlastmodified>Thu, 01 Jan 2026 00:00:00 GMT</D:getlastmodified>"
        + b"<D:getcontenttype>application/octet-stream</D:getcontenttype>"
        + b"<D:getcontentlength>0</D:getcontentlength>"
        + b"<D:resourcetype/>"
        + b"<D:lockdiscovery><D:activelock>"
        + b"<D:locktype><D:write/></D:locktype>"
        + b"<D:lockscope><D:exclusive/></D:lockscope>"
        + b"<D:depth>infinity</D:depth>"
        + b"<D:owner>owner-1</D:owner>"
        + b"<D:timeout>Second-3600</D:timeout>"
        + b"<D:locktoken><D:href>opaquelocktoken:"
        + str(FIXED_TOKEN).encode()
        + b"</D:href></D:locktoken>"
        + b"<D:lockroot><D:href>/prefix/locked</D:href></D:lockroot>"
        + b"</D:activelock></D:lockdiscovery>"
        + b"</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        + b"</D:response></D:multistatus>"
    )
    _parse(result)


def test_render_lockdiscovery_shared_and_lockroot_quoted() -> None:
    lock_obj = _make_lock(href="/prefix/a b", scope=DAVLockScope.SHARED)
    entry = _make_entry("/prefix/a b", display_name="a b", lock_obj=lock_obj)

    result = render_propfind_multistatus([entry], None)

    assert b"<D:lockscope><D:shared/></D:lockscope>" in result
    assert b"<D:lockroot><D:href>/prefix/a%20b</D:href></D:lockroot>" in result
    # lockdiscovery sits inside D:prop, after extras
    content = result.decode("utf-8")
    assert content.index("</D:prop>") > content.index("<D:lockdiscovery>")
    assert content.index("<D:lockdiscovery>") > content.index("<D:displayname>")
    _parse(result)


def test_render_propstat_children_structure() -> None:
    entry = _make_entry("/fs/a", display_name="a")

    root = _parse(render_propfind_multistatus([entry], None))

    response = root.find("{DAV:}response")
    assert response is not None
    propstat = response.find("{DAV:}propstat")
    assert propstat is not None
    # RFC 4918 14.24: propstat children are exactly (prop, status)
    assert [child.tag for child in propstat] == ["{DAV:}prop", "{DAV:}status"]


def test_render_escaping_and_newline_preservation() -> None:
    entry = _make_entry(
        "/fs/a&b<c>d.txt",
        display_name="a&b<c>d\"e'f 中文",
        extra_data={("http://a", "note"): "x&y<z>"},
    )
    lock_obj = DAVLockObj(
        owner="o&<w>",
        path=DAVPath("/prefix/locked"),
        depth=DAVDepth.INFINITY,
        token=FIXED_TOKEN,
        scope=DAVLockScope.EXCLUSIVE,
        timeout=3600,
    )
    locked = PropfindEntry(dav_property=entry.dav_property, lock_obj=lock_obj)

    result = render_propfind_multistatus([locked], None)

    assert (
        b"<D:displayname>a&amp;b&lt;c&gt;d\"e'f \xe4\xb8\xad\xe6\x96\x87"
        b"</D:displayname>"
    ) in result
    assert b"<ns1:note>x&amp;y&lt;z&gt;</ns1:note>" in result
    assert b"<D:owner>o&amp;&lt;w&gt;</D:owner>" in result
    # generated values are not escaped
    assert b"<D:getcontenttype>application/octet-stream</D:getcontenttype>" in result
    # href percent-quoting
    assert b"<D:href>/fs/a%26b%3Cc%3Ed.txt</D:href>" in result
    _parse(result)


def test_render_newline_in_displayname_preserved() -> None:
    # regression: the old whole-document replace("\n", "") stripped it
    entry = _make_entry("/fs/a", display_name="line1\nline2")

    result = render_propfind_multistatus([entry], None)

    assert b"<D:displayname>line1\nline2</D:displayname>" in result
    _parse(result)


def test_render_invalid_extra_name_dropped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = _make_entry(
        "/fs/a",
        display_name="a",
        extra_data={("http://a", "bad name"): "v", ("http://a", "a<b"): "v"},
    )

    with caplog.at_level(logging.WARNING):
        result = render_propfind_multistatus([entry], None)

    assert b"bad name" not in result
    assert b"a<b" not in result
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2
    _parse(result)


def test_render_many_entries() -> None:
    entries = [
        _make_entry(f"/fs/dir-1000/entry-{i:04d}.txt", display_name=f"e{i}")
        for i in range(1000)
    ]

    result = render_propfind_multistatus(entries, None)

    assert result.count(b"<D:response>") == 1000
    assert result.count(b"<D:multistatus") == 1
    _parse(result)


def test_render_href_percent_quoting() -> None:
    entry = _make_entry("/fs/a b&c>d.txt", display_name="x")

    result = render_propfind_multistatus([entry], None)

    assert b"<D:href>/fs/a%20b%26c%3Ed.txt</D:href>" in result
    _parse(result)


def test_encoding_property_removed() -> None:
    entry = _make_entry(
        "/fs/entry-0001.txt",
        display_name="entry-0001.txt",
        content_length=1,
        content_type="text/plain",
    )
    entry.dav_property.basic_data.content_encoding = "gzip"

    result = render_propfind_multistatus([entry], None)

    assert b"D:encoding" not in result
    assert b"<encoding>" not in result
    assert "encoding" not in DAV_PROPERTY_BASIC_KEYS
    _parse(result)


def test_render_empty_entries() -> None:
    result = render_propfind_multistatus([], None)

    assert (
        result == XML_DECLARATION + b'<D:multistatus xmlns:D="DAV:">'
        b"</D:multistatus>"
    )
    _parse(result)


def test_propfind_entry_is_immutable() -> None:
    entry = _make_entry("/fs/a", display_name="a")

    with pytest.raises(AttributeError):
        entry.lock_obj = None  # type: ignore[misc]
