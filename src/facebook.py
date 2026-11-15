"""
Facebook Graph API client for automated Page posting.
Supports photo posts (/{page-id}/photos) and text feed posts (/{page-id}/feed)
with detailed, beginner-friendly error classification.
"""

import os
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from src.utils import logger, retry_with_backoff


GRAPH_API_DEFAULT_VERSION = "v21.0"


class FacebookGraphError(Exception):
    """Custom exception containing structured Facebook Graph API errors."""
    def __init__(self, message: str, code: Optional[int] = None, subcode: Optional[int] = None, fb_type: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.fb_type = fb_type


def parse_facebook_error(response_json: Dict[str, Any], status_code: int) -> str:
    """
    Parses Facebook Graph API error JSON into clear, actionable advice.
    """
    error = response_json.get("error", {})
    code = error.get("code")
    subcode = error.get("error_subcode")
    message = error.get("message", "Unknown Facebook API error")
    error_type = error.get("type", "OAuthException")

    advice = []

    # Token Expiration or Invalid Token
    if code == 190 or "token" in message.lower() or "session" in message.lower():
        advice.append(
            "[ACTION REQUIRED] Your Facebook Page Access Token is INVALID or has EXPIRED. "
            "Please generate a new long-lived Page Access Token from Facebook Graph API Explorer "
            "and update FB_PAGE_ACCESS_TOKEN in your .env file."
        )

    # Permission errors
    elif code == 200 or "permission" in message.lower():
        advice.append(
            "[ACTION REQUIRED] Missing required permissions. "
            "Ensure your Page Access Token has the following permissions granted: "
            "'pages_manage_posts', 'pages_read_engagement', and 'pages_show_list'. "
            "Also verify you are using a PAGE token, not a USER token."
        )

    # Rate Limiting
    elif code in (4, 17, 32, 613) or "rate limit" in message.lower():
        advice.append(
            "[ACTION REQUIRED] Facebook API rate limit reached. "
            "Too many requests have been made in a short time. Please wait an hour before posting again."
        )

    # Invalid Page ID or Target
    elif code == 100 and ("node" in message.lower() or "page" in message.lower()):
        advice.append(
            "[ACTION REQUIRED] Invalid Page ID or endpoint. "
            "Verify FB_PAGE_ID in your .env matches your numeric Facebook Page ID exactly."
        )

    else:
        advice.append(
            f"[ACTION REQUIRED] Graph API Error (Code: {code}, Subcode: {subcode}, Type: {error_type}). "
            f"Details: {message}"
        )

    return f"Facebook Error ({status_code}): {message}\n" + "\n".join(advice)


def get_fb_credentials(config: Optional[Dict[str, Any]] = None) -> Tuple[str, str, str]:
    """
    Retrieves and validates FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN, and API version.
    """
    page_id = os.getenv("FB_PAGE_ID", "").strip()
    token = os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()
    version = GRAPH_API_DEFAULT_VERSION

    if config:
        version = config.get("facebook", {}).get("api_version", GRAPH_API_DEFAULT_VERSION)

    if not page_id:
        raise ValueError("FB_PAGE_ID is missing or empty in .env. Please configure your numeric Page ID.")
    if not token:
        raise ValueError("FB_PAGE_ACCESS_TOKEN is missing or empty in .env. Please configure your Page Access Token.")

    return page_id, token, version


def test_facebook_connection(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Verifies that the Page Access Token is valid and can access the Page.
    Used by CLI flag `--test-facebook`.
    """
    try:
        page_id, token, version = get_fb_credentials(config)
    except ValueError as e:
        return {"success": False, "message": str(e)}

    url = f"https://graph.facebook.com/{version}/{page_id}"
    params = {
        "fields": "id,name,link,is_published",
        "access_token": token,
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if resp.status_code == 200 and "id" in data:
            name = data.get("name", "Unknown Page")
            link = data.get("link", f"https://facebook.com/{page_id}")
            return {
                "success": True,
                "page_id": data.get("id"),
                "page_name": name,
                "page_link": link,
                "message": f"Successfully authenticated with Page: '{name}' (ID: {data.get('id')})",
            }
        else:
            explanation = parse_facebook_error(data, resp.status_code)
            return {"success": False, "message": explanation}
    except requests.RequestException as e:
        return {"success": False, "message": f"Network connection failed: {e}"}


def post_to_facebook(
    caption: str,
    image_path: Optional[Path] = None,
    config: Optional[Dict[str, Any]] = None,
    timeout: int = 45,
) -> Dict[str, Any]:
    """
    Publishes a post to the Facebook Page via the Graph API.
    If image_path is provided, posts via /{page-id}/photos.
    If image_path is None, posts via /{page-id}/feed.

    Returns:
        {"post_id": "...", "post_link": "..."}
    """
    page_id, token, version = get_fb_credentials(config)

    if image_path and image_path.exists():
        # Photo post
        endpoint = f"https://graph.facebook.com/{version}/{page_id}/photos"
        logger.info(f"Uploading photo to Facebook Page ({page_id})...")

        with open(image_path, "rb") as f:
            files = {"source": f}
            data = {
                "caption": caption,
                "access_token": token,
            }
            resp = requests.post(endpoint, data=data, files=files, timeout=timeout)

    else:
        # Text-only post
        endpoint = f"https://graph.facebook.com/{version}/{page_id}/feed"
        logger.info(f"Publishing text-only post to Facebook Page ({page_id})...")
        payload = {
            "message": caption,
            "access_token": token,
        }
        resp = requests.post(endpoint, data=payload, timeout=timeout)

    try:
        result = resp.json()
    except Exception:
        result = {"error": {"message": resp.text}}

    if resp.status_code == 200 and ("id" in result or "post_id" in result):
        post_id = result.get("post_id") or result.get("id")
        logger.info(f"Successfully posted to Facebook! ID: {post_id}")
        return {
            "post_id": post_id,
            "facebook_link": f"https://www.facebook.com/{post_id}",
        }
    else:
        err_msg = parse_facebook_error(result, resp.status_code)
        logger.error(err_msg)
        raise FacebookGraphError(err_msg)
