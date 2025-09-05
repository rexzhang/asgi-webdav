class DAVException(Exception):
    pass


class DAVExceptionConfigPaserFailed(DAVException):
    pass


class DAVExceptionRequestParserFailed(DAVException):
    pass


class DAVExceptionProviderInitFailed(DAVException):
    pass


class DAVExceptionAuthFailed(DAVException):
    pass
