"""Installed before any test module imports steward: the ground-truth audit hook (claim 1's trap).

Records every file opened and every subprocess spawned, from the very first import. A test that
asserts isolation reads `AUDIT` (see test_planted_isolation.py).
"""

import hashlib
import os
import sys
from pathlib import Path

PLANTED = (Path(__file__).resolve().parent.parent / "evals" / "ground_truth" / "planted.json").resolve()
PLANTED_DIGEST = hashlib.sha256(PLANTED.read_bytes()).hexdigest()
AUDIT: dict[str, list] = {"open": [], "subprocess": []}


def _hook(event, args):
    if event == "open" and args:
        p = args[0]
        if isinstance(p, int):
            return
        AUDIT["open"].append(os.fsdecode(p) if isinstance(p, str | bytes | os.PathLike) else str(p))
    elif event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.exec"):
        AUDIT["subprocess"].append(repr(args)[:200])


sys.addaudithook(_hook)


def is_ground_truth(path: str) -> bool:
    """Same file (realpath — symlinks), or a copy of it (content digest)."""
    try:
        rp = Path(path).resolve()
    except (OSError, RuntimeError):
        return False
    if rp == PLANTED:
        return True
    try:
        if rp.is_file() and rp.stat().st_size == PLANTED.stat().st_size:
            return hashlib.sha256(rp.read_bytes()).hexdigest() == PLANTED_DIGEST
    except OSError:
        return False
    return False
