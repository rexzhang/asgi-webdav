from __future__ import annotations

from dataclasses import dataclass, field

from asgi_webdav.constants import DAVPath, DAVPropertyIdentity, DAVTime
from asgi_webdav.helpers import generate_etag


@dataclass(slots=True)
class DAVPropertyBasicData:
    is_collection: bool

    display_name: str

    creation_date: DAVTime
    last_modified: DAVTime

    # resource_type: str = field(init=False)
    content_type: str = ""
    content_charset: str | None = None
    content_length: int = 0
    content_encoding: str | None = None

    def __post_init__(self) -> None:
        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Basics_of_HTTP/MIME_types
        if not self.content_type:
            if self.is_collection:
                # self.content_type = "httpd/unix-directory"
                self.content_type = "application/index"
            else:
                self.content_type = "application/octet-stream"

    _etag: str | None = None

    @property
    def etag(self) -> str:
        if self._etag is None:
            self._etag = generate_etag(
                self.content_length, self.last_modified.timestamp
            )
        return self._etag

    def get_get_head_response_headers(self) -> dict[bytes, bytes]:
        if self.content_type.startswith("text/") and self.content_charset:
            content_type = "{}; charset={}".format(
                self.content_type, self.content_charset
            )
        else:
            content_type = self.content_type

        headers = {
            b"ETag": self.etag.encode("utf-8"),
            b"Last-Modified": self.last_modified.http_date.encode("utf-8"),
            b"Content-Type": content_type.encode("utf-8"),
        }

        if self.is_collection:
            return headers

        if self.content_encoding:
            headers.update(
                {
                    b"Content-Encodings": self.content_encoding.encode("utf-8"),
                }
            )

        return headers

    def as_dict(self) -> dict[str, str | int]:
        data: dict[str, str | int] = {
            "displayname": self.display_name,
            "getetag": self.etag,
            "creationdate": self.creation_date.iso_8601,
            "getlastmodified": self.last_modified.http_date,
            "getcontenttype": self.content_type,
        }

        if self.is_collection:
            return data

        data.update(
            {
                "getcontentlength": self.content_length,
            }
        )
        if self.content_encoding:
            data.update(
                {
                    "encoding": self.content_encoding,  # TODO ???
                }
            )

        return data


@dataclass(slots=True)
class DAVProperty:
    # href_path = passport.prefix + passport.src_path + child
    #   or = request.src_path + child
    #   child maybe is empty
    href_path: DAVPath

    is_collection: bool

    # basic_data: dict[str, str]
    basic_data: DAVPropertyBasicData

    extra_data: dict[DAVPropertyIdentity, str] = field(default_factory=dict)
    extra_not_found: list[DAVPropertyIdentity] = field(default_factory=list)
