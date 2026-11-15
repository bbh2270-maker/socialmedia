"""
Google Drive integration module.
Parses share links, converts to direct download links, handles large-file
confirmation warnings, validates image integrity, and cycles images without reuse.
"""

import re
import requests
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from urllib.parse import urlparse, parse_qs
from src.utils import logger, OUTPUT_DIR, validate_image_bytes, retry_with_backoff
from src.db import get_drive_usage_stats, record_drive_usage

# Supported link patterns
FILE_ID_PATTERNS = [
    re.compile(r"/file/d/([a-zA-Z0-9_-]{15,})"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]{15,})"),
]


def extract_drive_file_id(url_or_id: str) -> Optional[str]:
    """
    Extracts the Google Drive file ID from various sharing formats:
    - https://drive.google.com/file/d/ID/view?usp=sharing
    - https://drive.google.com/open?id=ID
    - https://drive.google.com/uc?id=ID
    - Bare FILE_ID (if already an ID)
    """
    if not url_or_id:
        return None

    cleaned = url_or_id.strip()

    # If it's a bare alphanumeric ID
    if re.match(r"^[a-zA-Z0-9_-]{20,50}$", cleaned):
        return cleaned

    for pattern in FILE_ID_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            return match.group(1)

    return None


def get_direct_download_url(file_id: str) -> str:
    """
    Constructs the direct download endpoint for Google Drive.
    """
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def download_drive_image(
    file_id: str, timeout: int = 30, session: Optional[requests.Session] = None
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Downloads file content from Google Drive, handling large-file virus scan warnings
    and validating that the result is an image rather than an HTML permissions error.

    Returns:
        (image_bytes, error_message)
    """
    sess = session or requests.Session()
    url = get_direct_download_url(file_id)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            return None, f"HTTP status {resp.status_code} while downloading file {file_id}"

        content_type = resp.headers.get("Content-Type", "").lower()
        content = resp.content

        # Check if Google returned an HTML page (confirmation or access denied)
        if "text/html" in content_type or content.strip().startswith(b"<!DOCTYPE") or content.strip().startswith(b"<html"):
            html_text = content.decode("utf-8", errors="ignore")

            # Check for permission errors
            if "You need permission" in html_text or "Access denied" in html_text or "accounts.google.com" in resp.url:
                return (
                    None,
                    f"Google Drive file '{file_id}' is NOT public. "
                    "Please set sharing to 'Anyone with the link' (Viewer).",
                )

            # Check for large-file confirmation token
            # Google typically puts confirm token in form action or cookie
            confirm_token = None
            for key, val in sess.cookies.items():
                if "download_warning" in key:
                    confirm_token = val
                    break

            if not confirm_token:
                # Search HTML for confirm link/param
                confirm_match = re.search(r"confirm=([0-9A-Za-z_]+)", html_text)
                if confirm_match:
                    confirm_token = confirm_match.group(1)

            if confirm_token:
                confirm_url = f"{url}&confirm={confirm_token}"
                logger.info(f"Large file confirmation detected for Drive ID '{file_id}'. Following token...")
                resp2 = sess.get(confirm_url, headers=headers, timeout=timeout, allow_redirects=True)
                if resp2.status_code == 200 and not ("text/html" in resp2.headers.get("Content-Type", "").lower()):
                    content = resp2.content
                else:
                    return None, f"Failed to bypass large file confirmation for Drive file '{file_id}'"
            else:
                return (
                    None,
                    f"Google Drive returned an HTML page instead of an image for '{file_id}'. "
                    "Ensure the link points to an image file and is shared as 'Anyone with the link'.",
                )

        # Validate that the bytes are a legitimate image
        if not validate_image_bytes(content):
            return (
                None,
                f"Downloaded file for Drive ID '{file_id}' is not a valid image format (JPEG, PNG, WEBP, etc.).",
            )

        return content, None

    except requests.RequestException as e:
        return None, f"Network error downloading Drive file '{file_id}': {e}"


def get_next_drive_image(
    configured_urls: List[str], db_path: Optional[Path] = None
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """
    Selects the next Drive image from the configured list in order of least used,
    downloads and verifies it. If one fails (e.g., permissions or invalid image),
    it logs a clear warning and attempts the next available image.

    Returns:
        (saved_image_path, file_id, original_url) or (None, None, None)
    """
    if not configured_urls:
        logger.warning("No Google Drive image URLs provided in configuration.")
        return None, None, None

    # Map URLs to file IDs
    valid_entries: List[Tuple[str, str]] = []
    for url in configured_urls:
        fid = extract_drive_file_id(url)
        if fid:
            valid_entries.append((fid, url))
        else:
            logger.warning(f"Could not extract a valid Google Drive file ID from: {url}")

    if not valid_entries:
        logger.error("No valid Google Drive file IDs could be parsed from config.")
        return None, None, None

    # Retrieve usage counts from DB
    file_ids = [fid for fid, _ in valid_entries]
    stats = get_drive_usage_stats(file_ids, db_path=db_path)

    # Sort entries: lowest use_count first; then oldest last_used_at
    def sort_key(entry: Tuple[str, str]):
        fid = entry[0]
        stat = stats.get(fid)
        if not stat:
            return (0, "")
        return (stat["use_count"], stat["last_used_at"])

    sorted_candidates = sorted(valid_entries, key=sort_key)
    logger.info(
        f"Evaluated {len(sorted_candidates)} Google Drive candidate images based on usage history."
    )

    sess = requests.Session()
    for fid, original_url in sorted_candidates:
        logger.info(f"Attempting download for Google Drive file ID: {fid}")
        content, error = download_drive_image(fid, session=sess)
        if error:
            logger.warning(f"Skipping Drive image '{fid}': {error}")
            continue

        # Save downloaded image to output directory
        target_path = OUTPUT_DIR / f"drive_{fid}.jpg"
        try:
            target_path.write_bytes(content)
            record_drive_usage(fid, original_url, db_path=db_path)
            logger.info(f"Successfully saved validated Drive image to: {target_path}")
            return target_path, fid, original_url
        except Exception as e:
            logger.error(f"Failed to write image file '{target_path}': {e}")
            continue

    logger.error("All configured Google Drive images failed download or validation.")
    return None, None, None


def test_drive_links(configured_urls: List[str]) -> List[Dict[str, Any]]:
    """
    Tests all configured Drive URLs for accessibility and image validity.
    Used by CLI flag `--test-drive`.
    """
    results = []
    sess = requests.Session()
    for url in configured_urls:
        fid = extract_drive_file_id(url)
        if not fid:
            results.append({"url": url, "file_id": None, "valid": False, "error": "Invalid Drive URL format"})
            continue

        content, error = download_drive_image(fid, timeout=15, session=sess)
        if error:
            results.append({"url": url, "file_id": fid, "valid": False, "error": error})
        else:
            results.append({
                "url": url,
                "file_id": fid,
                "valid": True,
                "bytes": len(content),
                "error": None,
            })
    return results
