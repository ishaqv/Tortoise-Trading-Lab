import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from util.global_variables import IST

logger: Optional[logging.Logger] = None
log_lock = threading.Lock()

LOG_LEVELS = {
    "info": logging.INFO,
    "error": logging.ERROR,
    "debug": logging.DEBUG,
    "warning": logging.WARNING,
    "critical": logging.CRITICAL,
    "exception": logging.ERROR,  # Used with logger.exception()
}


def initialize_logger(trade_type, timeframe, log_to_console=False) -> logging.Logger:
    """
    Sets up and returns a logger for the trading scanner application.
    """
    global logger

    with log_lock:
        if logger is not None:
            return logger

        logger = logging.getLogger("TradingScannerLogger")
        logger.setLevel(logging.DEBUG)

        try:
            if log_to_console:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(
                    logging.Formatter("[%(levelname)s] %(message)s")
                )
                console_handler.setLevel(logging.DEBUG)
                logger.addHandler(console_handler)

            else:
                log_dir = get_log_directory(trade_type, timeframe)
                log_dir.mkdir(parents=True, exist_ok=True)

                log_file_name = get_log_file_name(
                    trade_type,
                    timeframe
                )

                log_file_path = log_dir / log_file_name

                file_handler = logging.FileHandler(
                    log_file_path,
                    encoding="utf-8"
                )

                file_handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(levelname)s - %(message)s"
                    )
                )

                file_handler.setLevel(logging.DEBUG)
                logger.addHandler(file_handler)

        except Exception as e:
            fallback_handler = logging.StreamHandler()
            fallback_handler.setFormatter(
                logging.Formatter("[%(levelname)s] %(message)s")
            )
            logger.addHandler(fallback_handler)

            logger.error(
                "⚠️ Failed to set up logger properly. "
                "Falling back to console.",
                exc_info=e
            )

        logger.propagate = False

        return logger


def log(level: str, message: str, exc_info: bool = False):
    """
        Logs a message using the configured logger at the specified log level.

        This is a wrapper function to simplify logging throughout the app.
    """
    global logger

    with log_lock:
        log_func = getattr(logger, level, None)
        if callable(log_func):
            log_func(message, exc_info=exc_info if level != "exception" else True)
        else:
            logger.warning(f"⚠️ Unknown log level '{level}'. Message: {message}")


def purge_old_logs(trade_type, timeframe, log_dir="logs", days=0.5):
    """
    Deletes log files older than the specified number of days.
    """

    full_log_path = get_log_directory(
        trade_type,
        timeframe,
        log_dir
    )

    now = time.time()
    cutoff_time = now - (days * 86400)

    if not full_log_path.exists():
        log(
            "info",
            f"Log directory '{full_log_path}' does not exist."
        )
        return

    deleted_files = []

    for file_path in full_log_path.iterdir():

        if not file_path.is_file():
            continue

        # Only process files matching our log naming convention
        if not file_path.name.startswith(
                get_log_file_name(trade_type, timeframe).split(
                    datetime.now(IST).strftime("%Y-%m-%d")
                )[0]
        ):
            continue

        if file_path.stat().st_mtime < cutoff_time:
            file_path.unlink()
            deleted_files.append(file_path.name)

    if deleted_files:
        log(
            "info",
            f"Deleted {len(deleted_files)} old log file(s): "
            f"{deleted_files}"
        )
    else:
        log("info", "No old log files found to delete.")


def get_log_directory(trade_type, timeframe, log_dir="logs") -> Path:
    """
    Returns the absolute log directory used by the application.
    """
    project_root = Path(__file__).resolve().parents[1]

    if trade_type is not None:
        return (
                project_root
                / trade_type.name.lower()
                / log_dir
                / timeframe
        )

    return project_root / log_dir / timeframe


def get_log_file_name(trade_type, timeframe, date=None) -> str:
    """
    Returns the log file name used by the application.
    """
    if date is None:
        date = datetime.now(IST).strftime("%Y-%m-%d")

    if trade_type is not None:
        trade_type_name = trade_type.name.lower()
        return (
            f"{trade_type_name}_"
            f"{timeframe}_{date}.log"
        )

    return f"{timeframe}_{date}.log"
