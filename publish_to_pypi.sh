#!/usr/bin/env sh

python -m pip install -U -r requirements/pypi.txt

rm -rf build/*
rm -rf dist/*
python setup.py sdist bdist_wheel

python -m twine upload --repository-url https://upload.pypi.org/legacy/ dist/*
