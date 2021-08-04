#!/usr/bin/env bash

pip install -U wheel pip

rm -rf build dist
python setup.py sdist bdist_wheel
wheel_package=`ls dist/*.whl`

pip uninstall -y ASGI-WebDAV-Server
pip install $wheel_package
