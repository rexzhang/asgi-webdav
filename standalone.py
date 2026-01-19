#!/usr/bin/env python


"""
The standalone entry point.

please visit docs/howto/howto-pyinstaller.en.md for more information.
"""


from asgi_webdav.cli import main as cli_main


def main() -> None:
    import sys

    try:
        sys.exit(cli_main())

    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
