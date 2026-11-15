"""
Tests for SQLite database persistence, slot checking, and 30-post duplicate prevention.
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from src.utils import get_current_slot
from src.db import (
    init_db,
    has_slot_posted_today,
    record_post,
    update_post_status,
    get_recent_topics,
    get_recent_captions,
    get_drive_usage_stats,
    record_drive_usage,
)
from src.topics import select_topic


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_autoposter.db"
    init_db(db_file)
    return db_file


def test_slot_determination():
    # Morning: 10:00 AM
    dt_morning = datetime(2026, 11, 8, 10, 0, 0, tzinfo=timezone.utc)
    slot, date_str, _ = get_current_slot(
        timezone_name="Asia/Dhaka", morning_cutoff_hour=14, override_now=dt_morning
    )
    assert slot == "morning"
    assert date_str == "2026-11-08"

    # Evening: 20:00 (8:00 PM)
    dt_evening = datetime(2026, 11, 8, 20, 0, 0, tzinfo=timezone.utc)
    slot_ev, date_str_ev, _ = get_current_slot(
        timezone_name="Asia/Dhaka", morning_cutoff_hour=14, override_now=dt_evening
    )
    assert slot_ev == "evening"
    assert date_str_ev == "2026-11-08"


def test_has_slot_posted_today(temp_db):
    date_str = "2026-11-08"
    slot = "morning"

    # Initially false
    assert not has_slot_posted_today(date_str, slot, db_path=temp_db)

    # Record a failed post
    record_post(
        date_str=date_str,
        slot=slot,
        topic="Failed Topic",
        caption="",
        image_source="none",
        image_path=None,
        status="failed",
        db_path=temp_db,
    )
    # Still false because status was 'failed'
    assert not has_slot_posted_today(date_str, slot, db_path=temp_db)

    # Record a successful post
    post_id = record_post(
        date_str=date_str,
        slot=slot,
        topic="Success Topic",
        caption="Success Caption",
        image_source="ai",
        image_path="output/test.jpg",
        status="success",
        facebook_post_id="fb_12345",
        db_path=temp_db,
    )
    assert post_id > 0
    assert has_slot_posted_today(date_str, slot, db_path=temp_db)

    # Different slot on same day should be false
    assert not has_slot_posted_today(date_str, "evening", db_path=temp_db)


def test_topic_selection_avoids_recent_30_posts(temp_db):
    configured = ["Topic A", "Topic B", "Topic C"]

    # Record Topic A as recently posted
    record_post(
        date_str="2026-11-01",
        slot="morning",
        topic="Topic A",
        caption="Cap A",
        image_source="ai",
        image_path=None,
        status="success",
        db_path=temp_db,
    )

    # Select topic with limit=30; it must pick either Topic B or Topic C, NEVER Topic A
    for _ in range(5):
        chosen = select_topic(configured, limit=30, db_path=temp_db)
        assert chosen in ["Topic B", "Topic C"]
        assert chosen != "Topic A"


def test_topic_selection_fallback_when_all_topics_used(temp_db):
    configured = ["Topic X", "Topic Y"]

    # Record both topics in history (Topic X first, Topic Y second)
    record_post(
        date_str="2026-11-01",
        slot="morning",
        topic="Topic X",
        caption="Cap X",
        image_source="ai",
        image_path=None,
        status="success",
        db_path=temp_db,
    )
    record_post(
        date_str="2026-11-02",
        slot="evening",
        topic="Topic Y",
        caption="Cap Y",
        image_source="ai",
        image_path=None,
        status="success",
        db_path=temp_db,
    )

    # When all configured topics have been used, select_topic should pick the oldest (Topic X)
    # and adapt it with a creative angle
    chosen = select_topic(configured, limit=30, db_path=temp_db)
    assert "Topic X" in chosen


def test_drive_image_usage_tracking(temp_db):
    fid1 = "drive_file_1"
    fid2 = "drive_file_2"

    record_drive_usage(fid1, "https://drive.google.com/open?id=drive_file_1", db_path=temp_db)
    record_drive_usage(fid1, "https://drive.google.com/open?id=drive_file_1", db_path=temp_db)
    record_drive_usage(fid2, "https://drive.google.com/open?id=drive_file_2", db_path=temp_db)

    stats = get_drive_usage_stats([fid1, fid2], db_path=temp_db)
    assert stats[fid1]["use_count"] == 2
    assert stats[fid2]["use_count"] == 1
