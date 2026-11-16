"""Safe, consistent logging configuration for application entry points."""

from __future__ import annotations

import logging
import os

LOGGER_NAME = "bitwarden_autofiller"
_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def configure_logging(level: str | None = None) -> None:
    """Configure stderr logging without including vault or credential data."""
    selected = level or os.environ.get("BITWARDEN_AUTOFILLER_LOG_LEVEL", "WARNING")
    selected = selected.upper()
    if selected not in _LEVELS:
        selected = "WARNING"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, selected))
    if logger.handlers or logging.getLogger().handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False
