"""Types shared by all converters."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[float], None]  # 0.0 .. 1.0


class ConversionError(RuntimeError):
    pass


class Cancelled(ConversionError):
    pass


@dataclass
class ConversionResult:
    source: Path
    target: Path | None
    ok: bool
    error: str | None = None


@dataclass
class CancelToken:
    _event: threading.Event = field(default_factory=threading.Event)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


def finalize(tmp: Path, target: Path) -> None:
    """Move the finished temp file into place. On Windows this fails while another program has the
    target open (viewer, antivirus, sync client), so turn that into a readable error."""
    try:
        tmp.replace(target)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise ConversionError(
            f"Cannot write {target.name}: the file may be open in another program or access is denied ({e}).") from e
