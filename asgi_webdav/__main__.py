#!/usr/bin/env python
# coding=utf-8


"""
The main entry point.
Invoke as `python_module_project' or `python -m python_module_project'.
"""

import sys


def main():
    try:
        from .cli import cli

        sys.exit(cli())
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
