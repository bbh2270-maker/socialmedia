"""
AI Image Generation module.
Supports Gemini Imagen (e.g. imagen-3.0-generate-002) and OpenRouter image models,
with automated prompt crafting and robust fallback to Google Drive or text-only.
"""

import os
import json
import base64
import random
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from src.utils import logger, OUTPUT_DIR, validate_image_bytes
from src.drive import get_next_drive_image


def build_image_prompt(topic: str, brand_niche: str) -> str:
    """
    Creates a clean, detailed visual prompt for the image generator based on the topic.
    """
    return (
        f"A modern, vibrant, clean digital illustration representing '{topic}' "
        f"in the context of {brand_niche}. Professional social media graphics, "
        "crisp lighting, high resolution, 4k quality, minimalist aesthetic, "
        "no distorted text, no random watermarks."
    )


def generate_gemini_image(
    prompt: str, model: str, api_key: str, timeout: int = 45
) -> bytes:
    """
    Calls Google Gemini Imagen endpoint (predict) via REST API.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={api_key}"
    payload = {
        "instances": [
            {"prompt": prompt}
        ],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "1:1",
            "outputMimeType": "image/jpeg",
        },
    }
    headers = {"Content-Type": "application/json"}
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini Imagen API error {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        predictions = data.get("predictions", [])
        if not predictions:
            raise RuntimeError(f"No predictions returned by Gemini Imagen: {data}")
        b64_data = predictions[0].get("bytesBase64Encoded")
        if not b64_data:
            raise RuntimeError(f"Missing base64 image data in response: {data}")
        return base64.b64decode(b64_data)
    except Exception as e:
        raise RuntimeError(f"Failed to decode Gemini image output: {e}") from e


def generate_openrouter_image(
    prompt: str, model: str, api_key: str, timeout: int = 45
) -> bytes:
    """
    Calls OpenRouter for image generation models (e.g. Flux, SDXL).
    Supports both direct image endpoints or chat returning markdown/data image.
    """
    # First attempt: standard chat/completions (supported by Flux on OpenRouter)
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com",
        "X-Title": "AutoPoster",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": f"Generate image: {prompt}"}
        ],
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter image API error {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        # Check choices content
        content = data["choices"][0]["message"]["content"]
        # Look for URL or base64
        import re
        url_match = re.search(r"https?://[^\s\)\"\']+", content)
        if url_match:
            img_url = url_match.group(0)
            img_resp = requests.get(img_url, timeout=30)
            if img_resp.status_code == 200 and validate_image_bytes(img_resp.content):
                return img_resp.content

        # Look for base64 inline
        b64_match = re.search(r"data:image/[^;]+;base64,([a-zA-Z0-9+/=]+)", content)
        if b64_match:
            return base64.b64decode(b64_match.group(1))

        raise RuntimeError(f"Could not extract image data or URL from OpenRouter response: {content[:150]}")
    except Exception as e:
        raise RuntimeError(f"Failed processing OpenRouter image response: {e}") from e


def create_ai_image(
    topic: str, config: Dict[str, Any]
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Generates an AI image based on topic using Gemini or OpenRouter.

    Returns:
        (image_path, error_message)
    """
    ai_cfg = config.get("ai", {})
    provider = ai_cfg.get("image_provider", "gemini").lower().strip()
    image_models = ai_cfg.get("image_models", {})
    brand_niche = config.get("brand", {}).get("niche", "Technology")

    prompt = build_image_prompt(topic, brand_niche)
    logger.info(f"Generating AI image using provider '{provider}'...")

    try:
        img_bytes = None
        if provider == "gemini":
            key = os.getenv("GEMINI_API_KEY", "").strip()
            if not key:
                return None, "GEMINI_API_KEY missing in .env"
            model = image_models.get("gemini", "imagen-3.0-generate-002")
            img_bytes = generate_gemini_image(prompt, model, key)

        elif provider == "openrouter":
            key = os.getenv("OPENROUTER_API_KEY", "").strip()
            if not key:
                return None, "OPENROUTER_API_KEY missing in .env"
            model = image_models.get("openrouter", "black-forest-labs/flux-schnell")
            img_bytes = generate_openrouter_image(prompt, model, key)

        else:
            return None, f"Unsupported image provider '{provider}'"

        if img_bytes and validate_image_bytes(img_bytes):
            filename = f"ai_gen_{abs(hash(topic)) % 10000000}.jpg"
            out_path = OUTPUT_DIR / filename
            out_path.write_bytes(img_bytes)
            logger.info(f"AI image successfully generated and saved to: {out_path}")
            return out_path, None
        else:
            return None, "Generated data did not pass image validation"

    except Exception as e:
        logger.warning(f"AI image generation failed with provider '{provider}': {e}")
        return None, str(e)


def resolve_post_image(
    topic: str,
    config: Dict[str, Any],
    db_path: Optional[Path] = None,
) -> Tuple[Optional[Path], str]:
    """
    Resolves the final image to be posted based on config['image_mode'] ('ai', 'drive', 'mixed')
    with automatic graceful fallbacks:
      - If 'ai' mode fails -> fallback to Google Drive -> fallback to text-only (if configured)
      - If 'drive' mode fails -> fallback to AI image -> fallback to text-only (if configured)
      - If 'mixed' -> choose randomly between 'ai' and 'drive' with same fallbacks

    Returns:
        (image_path, source_name) where source_name is 'ai', 'drive', or 'none'
    """
    image_mode = config.get("image_mode", "ai").lower().strip()
    drive_links = config.get("drive_images", [])
    fallback_to_drive = config.get("fallback_to_drive_on_ai_fail", True)
    fallback_to_text = config.get("fallback_to_text_only", True)

    # Determine primary choice
    primary = image_mode
    if image_mode == "mixed":
        primary = random.choice(["ai", "drive"])
        logger.info(f"Mixed mode selected primary target: '{primary}'")

    if primary == "ai":
        img_path, err = create_ai_image(topic, config)
        if img_path:
            return img_path, "ai"

        logger.warning(f"AI image generation failed: {err}")
        if fallback_to_drive and drive_links:
            logger.info("Falling back to Google Drive image source...")
            drive_path, _, _ = get_next_drive_image(drive_links, db_path=db_path)
            if drive_path:
                return drive_path, "drive"

        if fallback_to_text:
            logger.info("Falling back to text-only post.")
            return None, "none"
        raise RuntimeError("AI image generation and all fallbacks failed; text-only posting is disabled.")

    elif primary == "drive":
        drive_path, _, _ = get_next_drive_image(drive_links, db_path=db_path)
        if drive_path:
            return drive_path, "drive"

        logger.warning("Google Drive image fetch failed.")
        logger.info("Attempting fallback to AI image generation...")
        img_path, err = create_ai_image(topic, config)
        if img_path:
            return img_path, "ai"

        if fallback_to_text:
            logger.info("Falling back to text-only post.")
            return None, "none"
        raise RuntimeError("Google Drive and AI image fallbacks failed; text-only posting is disabled.")

    else:
        # Default or text-only mode
        logger.info(f"Image mode set to '{image_mode}'. Proceeding without image.")
        return None, "none"
