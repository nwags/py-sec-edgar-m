from __future__ import annotations

import logging

from py_sec_edgar.logging_utils import configure_logging


def test_configure_logging_sets_level_and_file_handler(tmp_path) -> None:
    log_file = tmp_path / "run.log"
    configure_logging(log_level="INFO", log_file=str(log_file))

    logger = logging.getLogger("py_sec_edgar.tests")
    logger.info("hello logger")

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello logger" in content


def test_configure_logging_replaces_managed_handlers(tmp_path) -> None:
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"

    configure_logging(log_level="INFO", log_file=str(first))
    configure_logging(log_level="DEBUG", log_file=str(second))

    logger = logging.getLogger("py_sec_edgar.tests")
    logger.debug("debug line")

    first_content = first.read_text(encoding="utf-8") if first.exists() else ""
    second_content = second.read_text(encoding="utf-8")
    assert "debug line" not in first_content
    assert "debug line" in second_content
