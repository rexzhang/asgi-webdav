"""
异常设计规则

    - 以模块(逻辑概念的)做一级分割
    - 如果需要再做二级分割
"""


class DAVException(Exception):
    pass


class DAVCodingError(DAVException):
    pass


class DAVRequestParseError(DAVException):
    pass


class DAVExceptionConfig(DAVException):
    pass


class DAVExceptionConfigFileNotFound(DAVExceptionConfig):
    pass


class DAVExceptionRequestParserFailed(DAVException):
    pass


class DAVExceptionProviderInitFailed(DAVException):
    pass


class DAVExceptionAuthFailed(DAVException):
    pass
