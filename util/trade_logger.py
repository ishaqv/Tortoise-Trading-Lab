import logging
import os
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

        - Depending on the `log_to_console` flag, logs will be written either to:
            • The console (terminal), or
            • A log file stored in the "logs" folder of your project.
        - If logging setup fails, it falls back to basic console logging and reports the error.
    """

    global logger
    with log_lock:
        if logger is not None:
            return logger

        logger = logging.getLogger("TradingScannerLogger")
        logger.setLevel(logging.DEBUG)  # Enable all log levels

        try:
            if log_to_console:
                # Console handler
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
                console_handler.setLevel(logging.DEBUG)
                logger.addHandler(console_handler)
            else:
                # File handler
                project_root = Path(__file__).resolve().parents[1]
                log_dir = project_root / trade_type.name.lower() / "logs" / timeframe
                log_dir.mkdir(parents=True, exist_ok=True)

                today = datetime.now(IST).strftime("%Y-%m-%d")
                log_file_path = log_dir / f"{trade_type.name.lower()}_trading_{timeframe}_scanner_{today}.log"

                file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
                file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
                file_handler.setFormatter(file_formatter)
                file_handler.setLevel(logging.DEBUG)
                logger.addHandler(file_handler)
        except Exception as e:
            # Fallback to console if anything fails
            fallback_handler = logging.StreamHandler()
            fallback_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
            logger.addHandler(fallback_handler)
            logger.error("⚠️ Failed to set up logger properly. Falling back to console.", exc_info=e)

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


def purge_old_logs(trade_type, timeframe, log_dir='logs', days=0.5):
    """
    Deletes log files older than a specified number of days from the given log directory.

    This function is useful for automatically cleaning up old log files and saving disk space.

    """

    # Resolve absolute path relative to the script file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_log_path = os.path.join(base_dir, '..', trade_type.name.lower(), log_dir, timeframe)
    full_log_path = os.path.abspath(full_log_path)  # normalize path

    now = time.time()
    cutoff_time = now - (days * 86400)  # 86400 seconds in a day

    if not os.path.exists(full_log_path):
        log("info", f"Log directory '{full_log_path}' does not exist.")
        return

    deleted_files = []

    for filename in os.listdir(full_log_path):
        file_path = os.path.join(full_log_path, filename)
        if os.path.isfile(file_path):
            file_mtime = os.path.getmtime(file_path)
            if file_mtime < cutoff_time:
                os.remove(file_path)
                deleted_files.append(filename)

    if deleted_files:
        log("info", f"Deleted {len(deleted_files)} old log file(s): {deleted_files}")
    else:
        log("info", "No old log files found to delete.")
