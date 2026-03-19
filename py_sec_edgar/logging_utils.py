from __future__ import annotations

import logging
from pathlib import Path
import sys


_MANAGED_HANDLER_ATTR = "_py_sec_edgar_managed"


def configure_logging(*, log_level: str = "WARNING", log_file: str | None = None) -> None:
    root = logging.getLogger()
    _remove_managed_handlers(root)

    level = getattr(logging, str(log_level).upper(), logging.WARNING)
    root.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(formatter)
    setattr(stderr_handler, _MANAGED_HANDLER_ATTR, True)
    root.addHandler(stderr_handler)

    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        setattr(file_handler, _MANAGED_HANDLER_ATTR, True)
        root.addHandler(file_handler)


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, _MANAGED_HANDLER_ATTR, False):
            logger.removeHandler(handler)
            handler.close()
