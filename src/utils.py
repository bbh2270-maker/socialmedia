"""
Utility functions for logging, time slots, retry logic, secret masking, and image validation.
"""

import os
import re
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional, Callable, Any
from io import BytesIO
from PIL import Image

# Base project paths
BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

for directory in (LOGS_DIR, DATA_DIR, OUTPUT_DIR):
    directory.mkdir(parents=True, exist_ok=True)


class SecretMaskingFilter(logging.Filter):
    """
    Masks known secret keys and common auth tokens from all log output
    to prevent accidental credential leakage in logs or console.
    """
    def __init__(self):
        super().__init__()
        self._secret_patterns = []
        self._refresh_secrets()

    def _refresh_secrets(self):
        secret_values = set()
        for env_var in [
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "OPENROUTER_API_KEY",
            "FB_PAGE_ACCESS_TOKEN",
            "FB_PAGE_ID",
        ]:
            val = os.getenv(env_var, "").strip()
            if val and len(val) >= 5:
                secret_values.add(re.escape(val))

        patterns = []
        if secret_values:
            combined = "|".join(sorted(secret_values, key=len, reverse=True))
            patterns.append(re.compile(combined))

        # Generic token patterns (Facebook access tokens, Bearer tokens, query param key=...)
        patterns.append(re.compile(r"EAA[a-zA-Z0-9_-]{30,}"))
        patterns.append(re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE))
        patterns.append(re.compile(r"([?&]key=)[a-zA-Z0-9_\-]{15,}", re.IGNORECASE))

        self._secret_patterns = patterns

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.msg, str):
            record.msg = str(record.msg)
        
        # In case new env vars were set after initial setup
        for pattern in self._secret_patterns:
            record.msg = pattern.sub("[REDACTED_SECRET]", record.msg)
            
        if record.args:
            # Handle string formatting args
            if isinstance(record.args, dict):
                cleaned_args = {}
                for k, v in record.args.items():
                    s_v = str(v)
                    for pattern in self._secret_patterns:
                        s_v = pattern.sub("[REDACTED_SECRET]", s_v)
                    cleaned_args[k] = s_v
                record.args = cleaned_args
            elif isinstance(record.args, tuple):
                cleaned_list = []
                for v in record.args:
                    s_v = str(v)
                    for pattern in self._secret_patterns:
                        s_v = pattern.sub("[REDACTED_SECRET]", s_v)
                    cleaned_list.append(s_v)
                record.args = tuple(cleaned_list)

        return True


def setup_logger(name: str = "autoposter") -> logging.Logger:
    """
    Configures a logger with both rotating file and stdout output,
    with secret redaction enabled.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_format = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    mask_filter = SecretMaskingFilter()

    # Rotating File Handler (5 MB max per file, 3 backups)
    log_file = LOGS_DIR / "app.log"
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_format)
    file_handler.addFilter(mask_filter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    console_handler.addFilter(mask_filter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()


def get_current_slot(
    timezone_name: str = "Asia/Dhaka",
    morning_cutoff_hour: int = 14,
    override_now: Optional[datetime] = None,
) -> Tuple[str, str, datetime]:
    """
    Determines the current scheduling slot ('morning' or 'evening') and date string
    for the configured timezone.
    
    Default: Asia/Dhaka (UTC+6)
    Runs at 04:00 UTC = 10:00 AM Dhaka -> 'morning'
    Runs at 14:00 UTC = 08:00 PM Dhaka -> 'evening'
    
    Returns:
        (slot_name, date_str, local_datetime) e.g. ('morning', '2026-11-08', dt)
    """
    tz = None
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(timezone_name)
    except Exception:
        # Fallback for standard Bangladesh / UTC+6 if zoneinfo is not compiled with tzdata
        if timezone_name == "Asia/Dhaka":
            tz = timezone(timedelta(hours=6))
        else:
            tz = timezone.utc

    now = override_now or datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    slot = "morning" if now.hour < morning_cutoff_hour else "evening"
    return slot, date_str, now


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[type, ...] = (Exception,),
):
    """
    Decorator for retrying network calls with exponential backoff.
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            delay = initial_delay
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            f"Action '{func.__name__}' failed on final attempt {attempt}/{max_retries}: {e}"
                        )
                        raise
                    logger.warning(
                        f"Action '{func.__name__}' failed (attempt {attempt}/{max_retries}): {e}. Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay *= backoff_factor
            if last_exception:
                raise last_exception
        return wrapper
    return decorator


def validate_image_file(file_path: Path) -> bool:
    """
    Validates whether a file on disk is an actual valid image
    (not an HTML error page, empty file, or corrupt binary).
    """
    try:
        if not file_path.exists() or file_path.stat().st_size == 0:
            return False
        with Image.open(file_path) as img:
            img.verify()
        return True
    except Exception as e:
        logger.debug(f"Image validation failed for {file_path}: {e}")
        return False


def validate_image_bytes(data: bytes) -> bool:
    """
    Validates whether bytes represent a valid image.
    """
    try:
        if not data or len(data) < 100:
            return False
        with Image.open(BytesIO(data)) as img:
            img.verify()
        return True
    except Exception:
        return False
