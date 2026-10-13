"""Performance and compatibility measurement tool for ASGI-WebDAV.

Measures the project under the GIL / free-threaded / free-threaded+JIT
interpreter matrix on macOS and inside a lima VM (the Linux leg), using the
Python 3.15 ``profiling.sampling`` (Tachyon) where available. The tool
manages the server-under-test subprocess itself and never asks for
credentials or root; every degraded path is recorded in the run output.

Machine-local configuration comes from the repo-root ``.env`` (gitignored),
every variable prefixed with ``TOOLS_PERF_``. All variables are optional:

    TOOLS_PERF_PYTHON_314    path to 3.14 interpreter (default: .venv314/bin/python)
    TOOLS_PERF_PYTHON_315    path to 3.15 interpreter (default: .venv/bin/python)
    TOOLS_PERF_PYTHON_315T   path to free-threaded 3.15t (default: empty =
                             skip; the FT legs run inside the lima VM)
    TOOLS_PERF_LOADGEN       oha | driver | auto        (auto)
    TOOLS_PERF_DURATION      seconds per bench sample   (10)
    TOOLS_PERF_REPEATS       repeats per combo          (5)
    TOOLS_PERF_WARMUP        warmup samples discarded   (1)
    TOOLS_PERF_CONCURRENCIES csv concurrency levels     (1,4,16)
    TOOLS_PERF_COOLDOWN      seconds between combos     (2.0)
    TOOLS_PERF_FIXTURES_DIR  fixtures root              (output/perf/fixtures)
    TOOLS_PERF_LOG_DIR       run-dir root               (output/perf)
    TOOLS_PERF_SAMPLING_RATE Tachyon rate               (10khz)
    TOOLS_PERF_PROFILE_DURATION  profile seconds        (20)
    TOOLS_PERF_VM_NAME       lima VM name               (asgi-webdav-tools-d13)
    TOOLS_PERF_VM_TEMPLATE   lima VM template           (template:debian)
    TOOLS_PERF_VM_DISK       VM disk GiB                (40)
    TOOLS_PERF_APT_MIRROR    apt mirror host            (empty)

Precedence: ``.env`` file > process environment > hardcoded default.
Exit codes: 0 = success, 1 = measurement failures recorded, 2 = tool error,
130 = interrupted.
"""
