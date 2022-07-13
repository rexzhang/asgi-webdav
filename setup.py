#!/usr/bin/env python
# coding=utf-8

# Template:
# https://github.com/rexzhang/pypi-package-project-template/blob/master/setup.py


# To use a consistent encoding
from codecs import open
from pathlib import Path

# Always prefer setuptools over distutils
from setuptools import find_packages, setup

import asgi_webdav as module

root_path = Path(__file__).parent
requirements_path = root_path.joinpath("requirements")

# Get the long description from the README file
with open(root_path.joinpath("README.md").as_posix(), encoding="utf-8") as f:
    long_description = f.read()


# Get install_requires from requirements.txt
def _read_requires_from_requirements_txt(
    base_path: Path, filename: str, ignore_base: bool = False
) -> list[str]:
    _requires = []
    with open(base_path.joinpath(filename).as_posix(), encoding="utf-8") as req_f:
        lines = req_f.readlines()
        for line in lines:
            if line == "\n" or line == "" or line[0] == "#":
                continue

            words = line.rstrip("\n").split(" ")
            if words[0] == "-r":
                if ignore_base and words[1] == "base.txt":
                    continue

                else:
                    _requires.extend(
                        _read_requires_from_requirements_txt(
                            base_path=base_path, filename=words[1]
                        )
                    )

            else:
                _requires.append(words[0])

    return _requires


install_requires = _read_requires_from_requirements_txt(
    base_path=requirements_path, filename="base.txt"
)
extras_require_dev = list(
    set(
        _read_requires_from_requirements_txt(
            base_path=requirements_path, filename="dev.txt"
        )
    )
)

# Setup
setup(
    # This is the name of your project. The first time you publish this
    # package, this name will be registered for you. It will determine how
    # users can install this project, e.g.:
    #
    # $ pip install sampleproject
    #
    # And where it will live on PyPI: https://pypi.org/project/sampleproject/
    #
    # There are some restrictions on what makes a valid project name
    # specification here:
    # https://packaging.python.org/specifications/core-metadata/#name
    name=module.__name__,  # Required
    # Versions should comply with PEP 440:
    # https://www.python.org/dev/peps/pep-0440/
    #
    # For a discussion on single-sourcing the version across setup.py and the
    # project code, see
    # https://packaging.python.org/en/latest/single_source_version.html
    version=module.__version__,  # Required
    # This is a one-line description or tagline of what your project does. This
    # corresponds to the "Summary" metadata field:
    # https://packaging.python.org/specifications/core-metadata/#summary
    description=module.__description__,  # Optional
    # This is an optional longer description of your project that represents
    # the body of text which users will see when they visit PyPI.
    #
    # Often, this is the same as your README, so you can just read it in from
    # that file directly (as we have already done above)
    #
    # This field corresponds to the "Description" metadata field:
    # https://packaging.python.org/specifications/core-metadata/#description-optional
    long_description=long_description,  # Optional
    # Denotes that our long_description is in Markdown; valid values are
    # text/plain, text/x-rst, and text/markdown
    #
    # Optional if long_description is written in reStructuredText (rst) but
    # required for plain-text or Markdown; if unspecified, "applications should
    # attempt to render [the long_description] as text/x-rst; charset=UTF-8 and
    # fall back to text/plain if it is not valid rst" (see link below)
    #
    # This field corresponds to the "Description-Content-Type" metadata field:
    # https://packaging.python.org/specifications/core-metadata/#description-content-type-optional
    long_description_content_type="text/markdown",  # Optional (see note above)
    # This should be a valid link to your project's main homepage.
    #
    # This field corresponds to the "Home-Page" metadata field:
    # https://packaging.python.org/specifications/core-metadata/#home-page-optional
    url=module.__project_url__,  # Optional
    # This should be your name or the name of the organization which owns the
    # project.
    author=module.__author__,  # Optional
    # This should be a valid email address corresponding to the author listed
    # above.
    author_email=module.__author_email__,  # Optional
    # # Choose your license
    # license=module.__licence__,
    # Classifiers help users find your project by categorizing it.
    #
    # For a list of valid classifiers, see https://pypi.org/classifiers/
    classifiers=[  # Optional
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        "Development Status :: 4 - Beta",
        # Indicate who your project is intended for
        # Pick your license as you wish
        "License :: OSI Approved :: MIT License",
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        # These classifiers are *not* checked by 'pip install'. See instead
        # 'python_requires' below.
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    # This field adds keywords for your project which will appear on the
    # project page. What does your project relate to?
    #
    # Note that this is a string of words separated by whitespace, not a list.
    keywords="asgi webdav asyncio",  # Optional
    # When your source code is in a subdirectory under the project root, e.g.
    # `src/`, it is necessary to specify the `package_dir` argument.
    # package_dir={'': 'src'},  # Optional
    # You can just specify package directories manually here if your project is
    # simple. Or you can use find_packages().
    #
    # Alternatively, if you just want to distribute a single Python file, use
    # the `py_modules` argument instead as follows, which will expect a file
    # called `my_module.py` to exist:
    #
    #   py_modules=["my_module"],
    #
    # packages=find_packages(where='src'),  # Required
    packages=find_packages(exclude=["contrib", "docs", "tests", "examples"]),
    # Specify which Python versions you support. In contrast to the
    # 'Programming Language' classifiers above, 'pip install' will check this
    # and refuse to install the project if the version does not match. If you
    # do not support Python 2, you can simplify this to '>=3.5' or similar, see
    # https://packaging.python.org/guides/distributing-packages-using-setuptools/#python-requires
    python_requires=">=3.10",
    # This field lists other packages that your project depends on to run.
    # Any package you put here will be installed by pip when your project is
    # installed, so they must be valid existing projects.
    #
    # For an analysis of "install_requires" vs pip's requirements files see:
    # https://packaging.python.org/en/latest/requirements.html
    install_requires=install_requires,  # Optional
    # List additional groups of dependencies here (e.g. development
    # dependencies). Users will be able to install these using the "extras"
    # syntax, for example:
    #
    #   $ pip install sampleproject[dev]
    #
    # Similar to `install_requires` above, these must be valid existing
    # projects.
    # extras_require={  # Optional
    #     "dev": extras_require_dev,
    #     "test": ["coverage"],
    # },
    # To provide executable scripts, use entry points in preference to the
    # "scripts" keyword. Entry points provide cross-platform support and allow
    # `pip` to create the appropriate form of executable for the target
    # platform.
    #
    # For examples, the following would provide a command called `sample` which
    # executes the function `main` from this package when invoked:
    entry_points={
        "console_scripts": [
            "asgi-webdav=asgi_webdav.cli:main",
        ],
    },
)
