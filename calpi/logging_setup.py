import logging
import os
import sys


def setup_logging() -> None:
    level = os.environ.get("CALPI_LOG_LEVEL", "INFO").upper()
    from calpi.data.credentials import RedactingFormatter
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",   # journald adds timestamps
        stream=sys.stdout,
    )
    for h in logging.getLogger().handlers:              # also redacts tracebacks (US-13)
        h.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
