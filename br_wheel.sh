#!/usr/bin/env bash

pip install -U wheel pip

rm -rf build dist
python setup.py sdist bdist_wheel

pip uninstall -y ASGI-WebDAV
pip install dist/ASGI_WebDAV-0.7.0-py2.py3-none-any.whl
