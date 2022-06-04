from dataclasses import dataclass, field

from asgi_webdav.constants import DAVPath, DAVPropertyIdentity, DAVTime
from asgi_webdav.helpers import generate_etag


@dataclass
class DAVPropertyBasicData:
    is_collection: bool

    display_name: str

    creation_date: DAVTime
    last_modified: DAVTime

    # resource_type: str = field(init=False)
    content_type: str | None = field(default=None)
    content_charset: str | None = None
    content_length: int = field(default=0)
    content_encoding: str | None = None

    def __post_init__(self):
        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Basics_of_HTTP/MIME_types
        if self.content_type is None:
            if self.is_collection:
                # self.content_type = "httpd/unix-directory"
                self.content_type = "application/index"
            else:
                self.content_type = "application/octet-stream"

        if self.content_length is None:
            self.content_length = 0

    @property
    def etag(self) -> str:
        return generate_etag(self.content_length, self.last_modified.timestamp)

    def get_get_head_response_headers(self) -> dict[bytes, bytes]:
        if self.content_type.startswith("text/") and self.content_charset:
            content_type = "{}; charset={}".format(
                self.content_type, self.content_charset
            )
        else:
            content_type = self.content_type

        headers = {
            b"ETag": self.etag.encode("utf-8"),
            b"Last-Modified": self.last_modified.http_date().encode("utf-8"),
            b"Content-Type": content_type.encode("utf-8"),
        }

        if self.is_collection:
            return headers

        headers.update(
            {
                b"Content-Length": str(self.content_length).encode("utf-8"),
            }
        )
        if self.content_encoding:
            headers.update(
                {
                    b"Content-Encodings": self.content_encoding.encode("utf-8"),
                }
            )

        return headers

    def as_dict(self) -> dict[str, str]:
        data = {
            "displayname": self.display_name,
            "getetag": self.etag,
            "creationdate": self.creation_date.dav_creation_date(),
            "getlastmodified": self.last_modified.http_date(),
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


@dataclass
class DAVProperty:
    # href_path = passport.prefix + passport.src_path + child
    #   or = request.src_path + child
    #   child maybe is empty
    href_path: DAVPath

    is_collection: bool

    # basic_data: dict[str, str]
    basic_data: DAVPropertyBasicData

    extra_data: dict[DAVPropertyIdentity, str] = field(default_factory=dict)
    extra_not_found: list[str] = field(default_factory=list)
