from collections import deque
from logging import Handler


LOGGING_CONFIG = {
    "version": 1,
    "formatters": {
        "webdav": {"format": "%(asctime)s %(levelname)s: [%(name)s] %(message)s"},
        "uvicorn": {"format": "%(asctime)s %(levelname)s: [uvicorn] %(message)s"},
        "webdav_docker": {"format": "%(levelname)s: [%(name)s] %(message)s"},
        "uvicorn_docker": {"format": "%(levelname)s: [uvicorn] %(message)s"},
        "admin_logging": {
            "format": "%(asctime)s %(levelname)s: [%(name)s] %(message)s"
        },
    },
    "handlers": {
        "webdav": {
            "class": "logging.StreamHandler",
            "formatter": "webdav",
            "level": "DEBUG",
        },
        "uvicorn": {
            "class": "logging.StreamHandler",
            "formatter": "uvicorn",
            "level": "INFO",
        },
        "admin_logging": {
            "class": "asgi_webdav.logging.DAVLogHandler",
            "formatter": "admin_logging",
            "level": "INFO",
        },
    },
    "loggers": {
        "asgi_webdav": {
            "handlers": ["webdav", "admin_logging"],
            "propagate": False,
            "level": "DEBUG",
        },
        "uvicorn": {
            "handlers": [
                "uvicorn",
            ],
            "propagate": False,
            "level": "INFO",
        },
    },
    # 'root': {
    #     'handlers': ['console', ],
    #     'propagate': False,
    #     'level': 'INFO',
    # },
}

_log_messages = deque(maxlen=100)


class DAVLogHandler(Handler):
    def __init__(self):
        super().__init__()

    def emit(self, record):
        """
        Emit a record.

        Writes the LogRecord to the queue, preparing it for pickling first.
        """
        try:
            if self.filter(record):
                _log_messages.append(self.format(record))

        except Exception:
            self.handleError(record)


def get_log_messages():
    return _log_messages
