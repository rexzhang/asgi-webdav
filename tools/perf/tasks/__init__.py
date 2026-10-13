"""Scripts executed as subprocesses under target interpreters or inside the
lima VM (``python -m tools.perf.tasks.<name>``).

Keep this __init__ import-light: tasks.driver runs under a bare VM python3
where only stdlib is guaranteed.
"""
