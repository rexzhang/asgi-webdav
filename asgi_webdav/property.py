from typing import Optional, List, Dict
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
    content_type: Optional[str] = field(default=None)
    content_length: int = field(default=0)
    encoding: str = field(default="utf-8")

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

        if self.encoding is None:
            self.encoding = "utf-8"

    @property
    def etag(self) -> str:
        return generate_etag(self.content_length, self.last_modified.timestamp)

    def get_get_head_response_headers(self) -> Dict[bytes, bytes]:
        headers = {
            b"ETag": self.etag.encode("utf-8"),
            b"Last-Modified": self.last_modified.iso_8601().encode("utf-8"),
            b"Content-Type": self.content_type.encode("utf-8"),
        }
        if not self.is_collection:
            headers.update(
                {
                    b"Content-Length": str(self.content_length).encode("utf-8"),
                    b"Content-Encodings": self.encoding.encode("utf-8"),
                    b"Accept-Ranges": b"bytes",
                }
            )

        return headers

    def as_dict(self) -> Dict[str, str]:
        data = {
            "displayname": self.display_name,
            "getetag": self.etag,
            "creationdate": self.creation_date.iso_8601(),
            "getlastmodified": self.last_modified.iso_850(),
            "getcontenttype": self.content_type,
        }
        if not self.is_collection:
            data.update(
                {"getcontentlength": self.content_length, "encoding": self.encoding}
            )
        return data


@dataclass
class DAVProperty:
    # href_path = passport.prefix + passport.src_path + child
    #   or = request.src_path + child
    #   child maybe is empty
    href_path: DAVPath

    is_collection: bool

    # basic_data: Dict[str, str]
    basic_data: DAVPropertyBasicData

    extra_data: Dict[DAVPropertyIdentity, str] = field(default_factory=dict)
    extra_not_found: List[str] = field(default_factory=list)
