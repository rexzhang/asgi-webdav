from __future__ import annotations

from pprint import pprint

from asgiref.typing import (
    ASGI3Application,
    ASGIReceiveCallable,
    ASGISendCallable,
    HTTPScope,
)


class DebugMiddleware:

    def __init__(self, app: ASGI3Application):
        self.app = app

    async def __call__(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        if self.debug_check(scope):
            await self.print_debug_info(scope, receive)

        await self.app(scope, receive, send)

    def debug_check(self, scope: HTTPScope) -> bool:
        if scope.get("method") != "PROPFIND":
            return False

        # if scope.get('src_path') != '/litmus/ccsrc/':
        #     return False

        return True

    @staticmethod
    async def print_debug_info(scope: HTTPScope, receive: ASGIReceiveCallable) -> None:
        print("---- scope ----")
        pprint(scope)
        headers = dict(scope.get("headers"))
        # pprint(headers)
        print("---- authorization ----")
        print(headers.get(b"authorization"))

        # print('{} {} {} {}'.format(
        #     scope.get('client'), scope.get('method'),
        #     scope.get('root_path'), scope.get('src_path')
        # ))
        print("---- receive ----")
        request_data = await receive()
        print("type", request_data.get("type"))
        print("body", request_data.get("body"))
        print("more_body", request_data.get("more_body"))

        print("---- DEBUG info END ----")
