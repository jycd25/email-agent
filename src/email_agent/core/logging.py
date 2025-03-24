import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:  # already configured (tests, embedding)
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Third-party chatter we never want at INFO.
    for noisy in ("httpx", "httpcore", "googleapiclient", "urllib3", "mail.log"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
