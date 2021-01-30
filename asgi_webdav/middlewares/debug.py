from pprint import pprint


class DebugMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if self.debug_check(scope):
            await self.print_debug_info(scope, receive)

        await self.app(scope, receive, send)

    def debug_check(self, scope) -> bool:
        if scope.get('method') != 'MOVE':
            return False

        # if scope.get('src_path') != '/litmus/ccsrc/':
        #     return False

        return True

    @staticmethod
    async def print_debug_info(scope, receive):
        print('---- scope ----')
        pprint(scope)
        headers = dict(scope.get('headers'))
        # pprint(headers)
        print('---- authorization ----')
        print(headers.get(b'authorization'))

        # print('{} {} {} {}'.format(
        #     scope.get('client'), scope.get('method'),
        #     scope.get('root_path'), scope.get('src_path')
        # ))
        print('---- receive ----')
        print(await receive())

        print('---- DEBUG info END ----')
