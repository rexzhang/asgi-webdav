class DAVException(Exception):
    pass


class DAVExceptionRequestParserFailed(DAVException):
    pass


class DAVExceptionProviderInitFailed(DAVException):
    """will be trigger sys.exit(?)"""

    pass


class DAVExceptionAuthFailed(DAVException):
    pass
