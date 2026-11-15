"""
Tests for Google Drive link parsing, direct download handling, and image verification.
"""

import pytest
import io
from PIL import Image
from unittest.mock import patch, MagicMock
from src.drive import (
    extract_drive_file_id,
    get_direct_download_url,
    download_drive_image,
)


def create_dummy_image_bytes(format="JPEG") -> bytes:
    """Helper to generate minimal valid image bytes."""
    img = Image.new("RGB", (10, 10), color="blue")
    buf = io.BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def test_extract_drive_file_id():
    # Format 1: /file/d/ID/view
    url1 = "https://drive.google.com/file/d/1A2B3C4D5E6F7G8H9I0JkLmNoP/view?usp=sharing"
    assert extract_drive_file_id(url1) == "1A2B3C4D5E6F7G8H9I0JkLmNoP"

    # Format 2: open?id=ID
    url2 = "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWxYz"
    assert extract_drive_file_id(url2) == "1AbCdEfGhIjKlMnOpQrStUvWxYz"

    # Format 3: uc?id=ID
    url3 = "https://drive.google.com/uc?export=download&id=112233445566778899aabb"
    assert extract_drive_file_id(url3) == "112233445566778899aabb"

    # Format 4: direct alphanumeric ID
    assert extract_drive_file_id("1A2B3C4D5E6F7G8H9I0JkLmNoP") == "1A2B3C4D5E6F7G8H9I0JkLmNoP"

    # Format 5: invalid link
    assert extract_drive_file_id("https://example.com/not-drive") is None
    assert extract_drive_file_id("") is None


def test_get_direct_download_url():
    fid = "1A2B3C4D5E"
    assert get_direct_download_url(fid) == "https://drive.google.com/uc?export=download&id=1A2B3C4D5E"


@patch("requests.Session.get")
def test_download_drive_image_success(mock_get):
    img_bytes = create_dummy_image_bytes()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/jpeg"}
    mock_resp.content = img_bytes
    mock_get.return_value = mock_resp

    content, err = download_drive_image("test_file_id")
    assert err is None
    assert content == img_bytes


@patch("requests.Session.get")
def test_download_drive_image_not_public(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "text/html"}
    mock_resp.content = b"<html><body>You need permission to access this page</body></html>"
    mock_resp.url = "https://accounts.google.com/signin"
    mock_get.return_value = mock_resp

    content, err = download_drive_image("private_file_id")
    assert content is None
    assert "NOT public" in err


@patch("requests.Session.get")
def test_download_drive_image_large_file_confirm(mock_get):
    # First request returns HTML with confirm token
    confirm_html = b'<html><body><a href="/uc?export=download&confirm=t_12345&id=abc">Confirm</a></body></html>'
    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.headers = {"Content-Type": "text/html"}
    mock_resp1.content = confirm_html
    mock_resp1.url = "https://drive.google.com/uc"

    # Second request returns actual image
    valid_img = create_dummy_image_bytes()
    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.headers = {"Content-Type": "image/jpeg"}
    mock_resp2.content = valid_img
    mock_resp2.url = "https://drive.google.com/uc?export=download&id=abc&confirm=t_12345"

    mock_get.side_effect = [mock_resp1, mock_resp2]

    content, err = download_drive_image("abc")
    assert err is None
    assert content == valid_img


@patch("requests.Session.get")
def test_download_drive_image_invalid_bytes(mock_get):
    # Returns 200 OK but plain text garbage
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/octet-stream"}
    mock_resp.content = b"This is just some plain text, definitely not a valid image."
    mock_get.return_value = mock_resp

    content, err = download_drive_image("corrupt_file_id")
    assert content is None
    assert "not a valid image format" in err
