"""Run WebDAV litmus compliance tests against a running ASGI-WebDAV server.

The tool drives a dedicated Lima VM (created automatically on first use,
Debian by default): litmus is installed inside the VM, and each test target
is reached through ``host.lima.internal`` so the server must be bound to
``0.0.0.0`` on the macOS host. The server itself is NOT managed here — start
it before invoking ``run``::

    python -m asgi_webdav -c examples/config/litmus.toml -H 0.0.0.0
    .venv/bin/python -m tools.litmus run

Machine-local configuration comes from the repo-root ``.env`` (gitignored),
every variable prefixed with ``TOOLS_``. All variables are optional; the
defaults match ``examples/config/litmus.toml``:

    TOOLS_LITMUS_VM_NAME       lima VM name          (asgi-webdav-tools-d13)
    TOOLS_LITMUS_VM_TEMPLATE   lima VM template      (template:debian)
    TOOLS_LITMUS_VM_DISK       VM disk size in GiB   (10)
    TOOLS_LITMUS_APT_MIRROR    apt mirror host for   ()
                               the guest, empty =
                               deb.debian.org
    TOOLS_LITMUS_SERVER_PORT   host server port      (8000)
    TOOLS_LITMUS_GUEST_HOST    guest->host hostname  (host.lima.internal)
    TOOLS_LITMUS_TARGETS       target names          (fs-basic,fs-digest,
                                                     memory-basic,memory-digest)
    TOOLS_LITMUS_SUITES        litmus suites via the ()  basic copymove props
                               $TESTS env var, empty =   locks http
                               run all suites
    TOOLS_LITMUS_LOG_DIR       log dir, empty =      (tests/test_zone/litmus)
                               disable logging

Per-target overrides follow the pattern
``TOOLS_LITMUS_TARGET_{NAME}_{URL|USERNAME|PASSWORD}`` where ``{NAME}`` is
the upper-cased target name with ``-`` replaced by ``_``. Precedence:
``.env`` file > process environment > hardcoded default.

Exit codes: 0 = all targets passed, 1 = at least one litmus failure,
2 = infrastructure error (limactl/apt/preflight), 130 = interrupted.
"""
