import logging
import sys
from collections import deque
from copy import copy

import click


class DefaultFormatter(logging.Formatter):
    logging_level_color = {
        logging.DEBUG: "cyan",
        logging.INFO: "green",
        logging.WARNING: "yellow",
        logging.ERROR: "red",
        logging.CRITICAL: "bright_red",
    }

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        use_colors: bool | None = None,
    ):
        if use_colors in (True, False):
            self.use_colors = use_colors and sys.stdout.isatty()
        else:
            self.use_colors = False

        super().__init__(fmt=fmt, datefmt=datefmt, style=style)

    @staticmethod
    def status_code_color(status: int) -> str:
        if status < 200:
            return "bright_red"
        elif status < 400:
            return "cyan"
        elif status < 500:
            return "yellow"

        return "red"

    def formatMessage(self, record: logging.LogRecord) -> str:
        record_copy = copy(record)
        # print(record.__dict__)
        if self.use_colors:
            record_copy.levelname = click.style(
                record.levelname,
                fg=self.logging_level_color.get(record.levelno, "bright_red"),
            )

            if len(record.args) == 6 and isinstance(record.args[3], int):
                status = record.args[3]
                record_copy.args = (
                    record.args[0],
                    record.args[1],
                    click.style(record.args[2].raw, fg=self.status_code_color(status)),
                    record.args[1],
                    record.args[1],
                    record.args[1],
                )
        return super().formatMessage(record_copy)


def get_dav_logging_config(
    level: str = "INFO", display_datetime: bool = True, use_colors: bool = True
) -> dict:
    if display_datetime:
        default_format = "%(asctime)s %(levelname)s: [%(name)s] %(message)s"
    else:
        default_format = "%(levelname)s: [%(name)s] %(message)s"

    logging_config = {
        "version": 1,
        "formatters": {
            "default": {
                "()": "asgi_webdav.log.DefaultFormatter",
                "fmt": default_format,
                "use_colors": use_colors,
            },
            "webdav_web_admin": {
                "format": "%(asctime)s %(levelname)s: [%(name)s] %(message)s"
            },
        },
        "handlers": {
            "default": {
                "level": level,
                "formatter": "default",
                "class": "logging.StreamHandler",
            },
            "admin_page": {
                "level": level,
                "formatter": "webdav_web_admin",
                "class": "asgi_webdav.log.DAVLogHandler",
            },
        },
        "loggers": {
            "asgi_webdav": {
                "handlers": ["default", "admin_page"],
                "propagate": False,
                "level": level,
            },
            "uvicorn": {"handlers": ["default"], "level": level},
            "uvicorn.error": {"level": level},
            # "uvicorn.access": {
            #     # "handlers": ["access"],
            #     "handlers": ["default"],
            #     "level": "INFO",
            #     "propagate": False,
            # },
        },
    }
    return logging_config


_log_messages = deque(maxlen=100)


class DAVLogHandler(logging.Handler):
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
