"""PROPFIND 207 multistatus renderer (RFC 4918 9.1).

Direct string writer replacing xmltodict.unparse on the PROPFIND response
path; PROPPATCH and LOCK responses still go through
helpers.get_xml_from_dict (xmltodict).
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from logging import getLogger
from xml.sax.saxutils import escape, quoteattr

from asgi_webdav.constants import DAVLockObj
from asgi_webdav.property.common import DAVProperty

logger = getLogger(__name__)

_XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'
_STATUS_OK = "HTTP/1.1 200 OK"
_STATUS_NOT_FOUND = "HTTP/1.1 404 Not Found"

# basic property values are safe by construction (etag = md5 hex, dates in
# RFC 3339/1123 form by DAVTime, content types from mimetypes, ints) and
# skip escaping; displayname carries user-controlled text and must escape.
# a future as_dict() key lands here only if proven safe, otherwise it stays
# out of this set and escapes by default.
_BASIC_SAFE_KEYS = frozenset(
    {"getetag", "creationdate", "getlastmodified", "getcontenttype"}
)

# defense in depth for extra property names: keys parsed from a request body
# are valid XML names already (expat guarantees it), but never let an
# unvalidated name reach a tag. stricter than the XML Name production -- an
# exotic-but-legal name is dropped with a warning instead of rendered.
_EXTRA_NAME_RE = re.compile(r"\w[\w.\-]*\Z")


@dataclass(frozen=True, slots=True)
class PropfindEntry:
    dav_property: DAVProperty
    lock_obj: DAVLockObj | None


def _extra_element_name(ns_map: dict[str, str], ns: str, key: str) -> str | None:
    """Prefixed element name for an extra property; None when the key must
    be dropped (invalid XML name -> logged warning, never markup)."""
    if _EXTRA_NAME_RE.match(key) is None:
        logger.warning(f"drop property with invalid XML name: {key!r}")
        return None

    if len(ns) == 0:
        # no namespace -> bare local name
        return key

    ns_id = ns_map.setdefault(ns, f"ns{len(ns_map) + 1}")
    return f"{ns_id}:{key}"


def _render_lock_discovery(lock_obj: DAVLockObj) -> str:
    # keep element order in sync with DAVProvider._create_data_lock_discovery
    # (provider/common.py, LOCK response path)
    lockroot_href = urllib.parse.quote(lock_obj.path.raw, encoding="utf-8")
    return (
        "<D:lockdiscovery><D:activelock>"
        "<D:locktype><D:write/></D:locktype>"
        f"<D:lockscope><D:{lock_obj.scope.value}/></D:lockscope>"
        f"<D:depth>{lock_obj.depth.value}</D:depth>"
        f"<D:owner>{escape(lock_obj.owner)}</D:owner>"
        f"<D:timeout>Second-{lock_obj.timeout}</D:timeout>"
        "<D:locktoken>"
        f"<D:href>opaquelocktoken:{lock_obj.token}</D:href>"
        "</D:locktoken>"
        f"<D:lockroot><D:href>{lockroot_href}</D:href></D:lockroot>"
        "</D:activelock></D:lockdiscovery>"
    )


def render_propfind_multistatus(
    entries: Sequence[PropfindEntry],
    basic_keys: Collection[str] | None,
) -> bytes:
    """Render a PROPFIND 207 multistatus body.

    basic_keys=None means allprop mode (emit every basic property);
    otherwise only basic properties named in the collection are emitted,
    in DAVPropertyBasicData.as_dict() order. resourcetype is emitted in
    allprop mode or when requested (RFC 4918 9.1: named-prop mode returns
    only the requested properties). lockdiscovery is always emitted:
    named-prop requests for it currently route through the extra-property
    path and 404 (known defect), so gating it on the request would regress
    those clients.
    """
    parts: list[str] = []
    ns_map: dict[str, str] = {}

    for entry in entries:
        dav_property = entry.dav_property
        parts.append("<D:response><D:href>")
        parts.append(urllib.parse.quote(dav_property.href_path.raw, encoding="utf-8"))
        parts.append("</D:href><D:propstat><D:prop>")

        basic_data = dav_property.basic_data.as_dict()
        for k, v in basic_data.items():
            if basic_keys is not None and k not in basic_keys:
                continue
            if k in _BASIC_SAFE_KEYS or not isinstance(v, str):
                parts.append(f"<D:{k}>{v}</D:{k}>")
            else:
                parts.append(f"<D:{k}>{escape(v)}</D:{k}>")

        if basic_keys is None or "resourcetype" in basic_keys:
            if dav_property.is_collection:
                parts.append("<D:resourcetype><D:collection/></D:resourcetype>")
            else:
                parts.append("<D:resourcetype/>")

        for (ns, key), value in dav_property.extra_data.items():
            name = _extra_element_name(ns_map, ns, key)
            if name is None:
                continue
            parts.append(f"<{name}>{escape(value)}</{name}>")

        if entry.lock_obj is None:
            parts.append("<D:lockdiscovery/>")
        else:
            parts.append(_render_lock_discovery(entry.lock_obj))

        parts.append(f"</D:prop><D:status>{_STATUS_OK}</D:status></D:propstat>")

        not_found_names: list[str] = []
        for ns, key in dav_property.extra_not_found:
            name = _extra_element_name(ns_map, ns, key)
            if name is not None:
                not_found_names.append(name)
        if len(not_found_names) > 0:
            parts.append("<D:propstat><D:prop>")
            parts.extend(f"<{name}/>" for name in not_found_names)
            parts.append(
                f"</D:prop><D:status>{_STATUS_NOT_FOUND}</D:status></D:propstat>"
            )

        parts.append("</D:response>")

    # namespaces are known in full only after the body is rendered, so they
    # are declared once on the root element here
    ns_attrs = "".join(
        f" xmlns:{ns_id}={quoteattr(ns)}" for ns, ns_id in ns_map.items()
    )
    return (
        f'{_XML_DECLARATION}<D:multistatus xmlns:D="DAV:"{ns_attrs}>'
        + "".join(parts)
        + "</D:multistatus>"
    ).encode("utf-8")
