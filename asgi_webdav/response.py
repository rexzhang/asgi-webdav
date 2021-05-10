from typing import Optional, Union, Callable, AsyncGenerator, Dict
from datetime import datetime


class DAVResponse:
    """provider.implement => provider.DavProvider => DAVDistributor"""

    status: int
    headers: Dict[bytes, bytes]

    data: Union[bytes, AsyncGenerator]

    def __init__(
        self,
        status: int,
        headers: Optional[Dict[bytes, bytes]] = None,  # extend headers
        message: Optional[bytes] = None,
        data: Optional[AsyncGenerator] = None,
    ):
        self.status = status

        self.headers = dict()
        self.headers.update(
            {
                # (b'Content-Type', b'text/html'),
                b"Content-Type": b"application/xml",
            }
        )
        if headers:
            self.headers.update(headers)

        if message:
            self.data = message

            if b"Content-Length" not in self.headers:
                self.headers.update(
                    {
                        b"Content-Length": str(len(self.data)).encode("utf-8"),
                    }
                )

        elif data:
            self.data = data

        else:
            self.headers.update(
                {
                    b"Content-Length": b"0",
                }
            )
            self.data = b""

        self.headers.update(
            {
                b"Date": datetime.utcnow().isoformat().encode("utf-8"),
            }
        )

    async def send_in_one_call(self, send: Callable):
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": list(self.headers.items()),
            }
        )

        if isinstance(self.data, bytes):
            await send(
                {
                    "type": "http.response.body",
                    "body": self.data,
                }
            )

        else:
            async for data, more_body in self.data:
                await send(
                    {
                        "type": "http.response.body",
                        "body": data,
                        "more_body": more_body,
                    }
                )
        return

    def __repr__(self):
        fields = [self.status, self.data]
        s = "|".join([str(field) for field in fields])
        try:
            from prettyprinter import pformat

            s += "\n{}".format(pformat(self.headers))
        except ImportError:
            pass

        return s
