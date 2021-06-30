class WebDAVException(Exception):
    pass


class NotASGIRequestException(WebDAVException):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ProviderInitException(WebDAVException):
    pass
