"""Shared clobber policy for local generators. No network or host mutation."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WriteResult:
    exit_code: int
    report: str


def write_files(files: dict[Path, str], *, force: bool = False) -> WriteResult:
    """Preflight all targets; publish each complete file atomically.

    A batch is not a filesystem transaction. Reports identify completed writes
    on an I/O failure. Without force, atomic hard-link creation also protects
    against another writer creating the destination after preflight.
    """
    for path in files:
        if path.is_symlink() or path.is_dir():
            return WriteResult(2, f"error: target is a symlink or directory: {path}\n")
    existing = [str(path) for path in files if path.exists()]
    if existing and not force:
        return WriteResult(
            1,
            "refusing to overwrite existing files (pass --force to replace):\n"
            + "".join(f"- {path}\n" for path in existing),
        )
    written = []
    try:
        for path, text in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(text)
                    stream.flush()
                    os.fsync(stream.fileno())
                if force:
                    os.replace(temporary, path)
                else:
                    os.link(temporary, path)
                written.append(f"wrote {path}")
            finally:
                temporary.unlink(missing_ok=True)
    except OSError as exc:
        return WriteResult(
            2, "\n".join([*written, f"error: cannot write files: {exc.strerror}"]) + "\n"
        )
    return WriteResult(0, "\n".join(written) + "\n")
