"""
Tests for Facebook Graph API client and error parsing.
"""

import pytest
import os
import io
import logging
from unittest.mock import patch, MagicMock
from src.facebook import (
    post_to_facebook,
    test_facebook_connection as check_facebook_connection,
    parse_facebook_error,
    FacebookGraphError,
)
from src.utils import SecretMaskingFilter


def test_secret_masking_filter():
    filt = SecretMaskingFilter()
    # Mock record
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Error calling endpoint with token EAABw1234567890abcdefghijklmnopqrstuvwxyz",
        args=(),
        exc_info=None,
    )
    filt.filter(record)
    assert "EAABw" not in record.msg
    assert "[REDACTED_SECRET]" in record.msg


def test_parse_facebook_error_token_expired():
    error_payload = {
        "error": {
            "message": "Error validating access token: Session has expired on...",
            "type": "OAuthException",
            "code": 190,
            "error_subcode": 463,
        }
    }
    advice = parse_facebook_error(error_payload, 400)
    assert "INVALID or has EXPIRED" in advice
    assert "FB_PAGE_ACCESS_TOKEN" in advice


def test_parse_facebook_error_permissions():
    error_payload = {
        "error": {
            "message": "(#200) Requires pages_manage_posts permission",
            "type": "OAuthException",
            "code": 200,
        }
    }
    advice = parse_facebook_error(error_payload, 403)
    assert "Missing required permissions" in advice
    assert "pages_manage_posts" in advice


def test_parse_facebook_error_rate_limit():
    error_payload = {
        "error": {
            "message": "(#4) Application request limit reached",
            "type": "OAuthException",
            "code": 4,
        }
    }
    advice = parse_facebook_error(error_payload, 400)
    assert "rate limit reached" in advice


@patch.dict(os.environ, {
    "FB_PAGE_ID": "1000123456789",
    "FB_PAGE_ACCESS_TOKEN": "EAABdummyPageToken",
})
@patch("requests.post")
def test_post_to_facebook_photo_success(mock_post, tmp_path):
    img_file = tmp_path / "test.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)  # fake jpeg header

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "photo_id_999", "post_id": "1000123456789_999"}
    mock_post.return_value = mock_resp

    res = post_to_facebook("Caption text", image_path=img_file)
    assert res["post_id"] == "1000123456789_999"
    assert "facebook.com/1000123456789_999" in res["facebook_link"]


@patch.dict(os.environ, {
    "FB_PAGE_ID": "1000123456789",
    "FB_PAGE_ACCESS_TOKEN": "EAABdummyPageToken",
})
@patch("requests.post")
def test_post_to_facebook_text_only_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "1000123456789_888"}
    mock_post.return_value = mock_resp

    res = post_to_facebook("Caption text without image", image_path=None)
    assert res["post_id"] == "1000123456789_888"


@patch.dict(os.environ, {
    "FB_PAGE_ID": "1000123456789",
    "FB_PAGE_ACCESS_TOKEN": "EAABdummyPageToken",
})
@patch("requests.post")
def test_post_to_facebook_failure_raises_graph_error(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": {
            "message": "Invalid OAuth access token.",
            "type": "OAuthException",
            "code": 190,
        }
    }
    mock_post.return_value = mock_resp

    with pytest.raises(FacebookGraphError) as exc_info:
        post_to_facebook("Caption text", image_path=None)

    assert "INVALID or has EXPIRED" in str(exc_info.value)


@patch.dict(os.environ, {
    "FB_PAGE_ID": "1000123456789",
    "FB_PAGE_ACCESS_TOKEN": "EAABdummyPageToken",
})
@patch("requests.get")
def test_verify_facebook_connection(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "1000123456789",
        "name": "My Tech Page",
        "link": "https://facebook.com/1000123456789",
    }
    mock_get.return_value = mock_resp

    result = check_facebook_connection()
    assert result["success"] is True
    assert result["page_id"] == "1000123456789"
    assert "My Tech Page" in result["message"]

