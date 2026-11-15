#!/usr/bin/env python3
"""
Social Media Auto-Poster (Facebook Page)
Main orchestration CLI script designed for scheduled cron execution on Hostinger Cloud.
"""

import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Ensure local src package is importable
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from src.utils import (
    logger,
    get_current_slot,
    OUTPUT_DIR,
    BASE_DIR as PROJECT_DIR,
)
from src.db import (
    init_db,
    has_slot_posted_today,
    record_post,
    update_post_status,
    get_recent_captions,
)
from src.topics import select_topic
from src.drive import test_drive_links
from src.ai_text import generate_caption, test_text_providers
from src.ai_image import resolve_post_image
from src.facebook import post_to_facebook, test_facebook_connection, FacebookGraphError


def load_config(config_path: Path) -> dict:
    """Loads and validates config.json with helpful error messages."""
    if not config_path.exists():
        logger.error(f"Configuration file not found at: {config_path}")
        print(f"Error: Missing configuration file '{config_path}'. Please copy and configure config.json.")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse config.json: {e}")
        print(f"Error: Invalid JSON syntax in config.json: {e}")
        sys.exit(1)


def validate_environment(config: dict, require_facebook: bool = True) -> bool:
    """Validates that necessary environment variables and config values exist."""
    missing = []
    
    # Check AI keys
    text_providers = config.get("ai", {}).get("text_providers", ["gemini", "groq", "openrouter"])
    has_any_ai_key = any([
        ("gemini" in text_providers and sys.modules.get("os", {}).getenv("GEMINI_API_KEY")),
        ("groq" in text_providers and sys.modules.get("os", {}).getenv("GROQ_API_KEY")),
        ("openrouter" in text_providers and sys.modules.get("os", {}).getenv("OPENROUTER_API_KEY")),
    ])
    
    import os
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    if not (gemini_key or groq_key or openrouter_key):
        logger.warning("No AI API keys (GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY) found in .env.")

    if require_facebook:
        fb_id = os.getenv("FB_PAGE_ID")
        fb_token = os.getenv("FB_PAGE_ACCESS_TOKEN")
        if not fb_id:
            missing.append("FB_PAGE_ID")
        if not fb_token:
            missing.append("FB_PAGE_ACCESS_TOKEN")

    if missing:
        msg = f"Missing required environment variable(s) in .env: {', '.join(missing)}"
        logger.error(msg)
        print(f"[CONFIGURATION ERROR] {msg}\nPlease populate them in your .env file.")
        return False
    return True


def handle_test_ai(config: dict) -> int:
    """Runs connectivity and latency tests for configured AI providers."""
    print("=" * 60)
    print("TESTING CONFIGURED AI PROVIDERS")
    print("=" * 60)
    results = test_text_providers(config)
    all_ok = True
    for r in results:
        status_color = "[PASS]" if r["status"] == "PASSED" else f"[{r['status']}]"
        print(f"{status_color:8} Provider: {r['provider']:12} Model: {r['model']:30} Details: {r['message']}")
        if r["status"] == "FAILED":
            all_ok = False
    print("=" * 60)
    return 0 if all_ok else 1


def handle_test_facebook(config: dict) -> int:
    """Tests the Facebook Page Access Token and Page connectivity."""
    print("=" * 60)
    print("TESTING FACEBOOK PAGE CONNECTION")
    print("=" * 60)
    res = test_facebook_connection(config)
    if res["success"]:
        print(f"[PASS] {res['message']}")
        print(f"       Page Link: {res.get('page_link')}")
        print("=" * 60)
        return 0
    else:
        print(f"[FAIL] {res['message']}")
        print("=" * 60)
        return 1


def handle_test_drive(config: dict) -> int:
    """Tests all Google Drive image links configured in config.json."""
    urls = config.get("drive_images", [])
    print("=" * 60)
    print(f"TESTING {len(urls)} GOOGLE DRIVE IMAGE LINKS")
    print("=" * 60)
    if not urls:
        print("No Google Drive links configured in 'drive_images'.")
        print("=" * 60)
        return 0

    results = test_drive_links(urls)
    all_ok = True
    for r in results:
        if r["valid"]:
            print(f"[PASS] File ID: {r['file_id']:30} Size: {r['bytes']:,} bytes | URL: {r['url']}")
        else:
            all_ok = False
            print(f"[FAIL] File ID: {str(r['file_id']):30} Error: {r['error']} | URL: {r['url']}")
    print("=" * 60)
    return 0 if all_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Social Media Auto-Poster (Facebook Page) - Automated twice-daily content generator and publisher."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate topic, caption, and image, save to output/, but DO NOT post to Facebook.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the twice-daily slot check and force post even if already run for this slot.",
    )
    parser.add_argument(
        "--test-facebook",
        action="store_true",
        help="Verify Facebook Page ID and Access Token without posting.",
    )
    parser.add_argument(
        "--test-ai",
        action="store_true",
        help="Test all configured AI providers with a quick test prompt.",
    )
    parser.add_argument(
        "--test-drive",
        action="store_true",
        help="Verify accessibility and image validity of all configured Google Drive URLs.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_DIR / "config.json",
        help="Path to custom configuration file (defaults to config.json in root).",
    )

    args = parser.parse_args()

    # Load environment variables from .env
    load_dotenv(PROJECT_DIR / ".env")

    # Load configuration
    config = load_config(args.config)

    # Initialize SQLite database
    init_db()

    # Diagnostic / Test flags
    if args.test_facebook:
        return handle_test_facebook(config)

    if args.test_ai:
        return handle_test_ai(config)

    if args.test_drive:
        return handle_test_drive(config)

    # Environment validation for normal or dry-run execution
    require_fb = not args.dry_run
    if not validate_environment(config, require_facebook=require_fb):
        return 1

    # Time slot & Duplicate Slot Check
    sched_cfg = config.get("scheduler", {})
    tz_name = sched_cfg.get("timezone", "Asia/Dhaka")
    cutoff = sched_cfg.get("morning_slot_cutoff_hour", 14)
    slot, date_str, local_dt = get_current_slot(timezone_name=tz_name, morning_cutoff_hour=cutoff)

    logger.info(f"Execution started for Date: {date_str}, Slot: '{slot}' ({local_dt.strftime('%H:%M')} {tz_name})")

    if not args.force and not args.dry_run:
        if has_slot_posted_today(date_str, slot):
            logger.info(
                f"Notice: A post has already been successfully published for slot '{slot}' on {date_str}. "
                "Exiting quietly (exit code 0). Use --force to override."
            )
            return 0

    # 1. Select Topic avoiding last 30 posts
    topics_list = config.get("topics", [])
    history_limit = config.get("history_check_limit", 30)
    try:
        topic = select_topic(topics_list, limit=history_limit)
    except Exception as e:
        logger.error(f"Topic selection failed: {e}")
        print(f"Error selecting topic: {e}")
        return 1

    # 2. Resolve Image (AI, Drive, or Text-only with fallback)
    image_path = None
    image_source = "none"
    try:
        image_path, image_source = resolve_post_image(topic, config)
        logger.info(f"Image resolved from source: '{image_source}' (Path: {image_path})")
    except Exception as e:
        logger.error(f"Image resolution error: {e}")
        if not config.get("fallback_to_text_only", True):
            print(f"Fatal image error: {e}")
            return 1
        logger.info("Proceeding with text-only post.")

    # 3. Generate Caption avoiding recent captions
    recent_captions = get_recent_captions(limit=history_limit)
    try:
        caption, provider_used = generate_caption(
            topic=topic,
            config=config,
            recent_captions=recent_captions,
            image_path=image_path,
        )
    except Exception as e:
        logger.error(f"Caption generation failed: {e}")
        print(f"Caption generation failed: {e}")
        record_post(
            date_str=date_str,
            slot=slot,
            topic=topic,
            caption="",
            image_source=image_source,
            image_path=str(image_path) if image_path else None,
            status="failed",
            error=str(e),
        )
        return 1

    # 4. Handle Dry-Run Mode
    if args.dry_run:
        out_txt = OUTPUT_DIR / f"dry_run_{date_str}_{slot}.txt"
        summary = (
            f"=== DRY-RUN PREVIEW ({date_str} - {slot}) ===\n"
            f"Topic: {topic}\n"
            f"AI Provider Used: {provider_used}\n"
            f"Image Source: {image_source}\n"
            f"Image Path: {image_path}\n"
            f"----------------------------------------\n"
            f"Caption:\n{caption}\n"
            f"========================================\n"
        )
        out_txt.write_text(summary, encoding="utf-8")
        logger.info(f"[DRY-RUN] Success. Preview written to: {out_txt}")
        print(summary)
        record_post(
            date_str=date_str,
            slot=slot,
            topic=topic,
            caption=caption,
            image_source=image_source,
            image_path=str(image_path) if image_path else None,
            status="dry_run",
        )
        return 0

    # 5. Live Facebook Publication
    post_id = record_post(
        date_str=date_str,
        slot=slot,
        topic=topic,
        caption=caption,
        image_source=image_source,
        image_path=str(image_path) if image_path else None,
        status="pending",
    )

    try:
        fb_result = post_to_facebook(caption, image_path=image_path, config=config)
        update_post_status(
            post_id=post_id,
            status="success",
            facebook_post_id=fb_result["post_id"],
            facebook_link=fb_result["facebook_link"],
        )
        logger.info(f"Post successfully published! Link: {fb_result['facebook_link']}")
        print(f"[SUCCESS] Post published to Facebook Page!")
        print(f"Post ID: {fb_result['post_id']}")
        print(f"Link:    {fb_result['facebook_link']}")
        return 0

    except FacebookGraphError as e:
        logger.error(f"Facebook publication error: {e}")
        update_post_status(post_id=post_id, status="failed", error=str(e))
        print(f"\n[FACEBOOK POSTING FAILED]\n{e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error during posting: {e}")
        update_post_status(post_id=post_id, status="failed", error=str(e))
        print(f"Unexpected error during publication: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
