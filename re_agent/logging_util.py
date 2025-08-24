import os
from datetime import datetime
from loguru import logger


def setup_logging(verbose: bool = False):
    # Clear previous handlers
    logger.remove()

    level_console = "DEBUG" if verbose else "INFO"
    logger.add(lambda msg: print(msg, end=""), level=level_console, enqueue=False, colorize=True)

    os.makedirs("logs", exist_ok=True)
    log_path = os.path.join("logs", f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logger.add(log_path, level="DEBUG", enqueue=False, rotation=None)

    return logger

