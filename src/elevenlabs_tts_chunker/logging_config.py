"""
Logging configuration for elevenlabs-tts-chunker.
"""

import logging

from elevenlabs_tts_chunker.settings import get_settings


def configure_logging() -> logging.Logger:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger = logging.getLogger(name="tts_chunker")
    logger.setLevel(level)
    return logger


logger = configure_logging()
