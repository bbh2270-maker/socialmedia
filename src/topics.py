"""
Topic selector module.
Ensures fresh content selection without repeating any of the last 30 posts.
"""

import random
from typing import List, Optional
from pathlib import Path
from src.db import get_recent_topics
from src.utils import logger


def select_topic(
    configured_topics: List[str],
    limit: int = 30,
    db_path: Optional[Path] = None,
) -> str:
    """
    Selects a topic from the configured list that has not appeared in the last `limit` posts.
    If all configured topics have been used recently, it falls back to the topic used longest ago
    or appends a creative angle modifier so the post is never identical.
    """
    if not configured_topics:
        raise ValueError("No topics found in configuration. Please provide a list of topics in config.json.")

    recent_topics = get_recent_topics(limit=limit, db_path=db_path)
    logger.info(f"Retrieved {len(recent_topics)} recent topics from post history.")

    # Find topics not in recent history (case-insensitive comparison)
    recent_set = {t.strip().lower() for t in recent_topics}
    available = [t for t in configured_topics if t.strip().lower() not in recent_set]

    if available:
        chosen = random.choice(available)
        logger.info(f"Selected fresh topic from unused pool: '{chosen}'")
        return chosen

    # If all configured topics have been used in the last limit posts:
    logger.warning(
        f"All {len(configured_topics)} configured topics were used in the last {limit} posts. "
        "Selecting the least recently used topic and applying a fresh angle modifier."
    )
    
    # Track order of appearance in recent_topics (most recent first)
    # The topic that appears furthest down the list (or not in recent set) is the oldest used
    def recency_score(topic: str) -> int:
        norm = topic.strip().lower()
        for idx, recent in enumerate(recent_topics):
            if recent.strip().lower() == norm:
                return idx
        return 999999

    # Sort topics by recency_score descending (highest score = used longest ago)
    sorted_by_age = sorted(configured_topics, key=recency_score, reverse=True)
    base_topic = sorted_by_age[0]

    angles = [
        "Key Mistakes to Avoid in",
        "A Deep Dive into",
        "Pro Tips & Best Practices for",
        "Common Misconceptions About",
        "Beginner vs Advanced Strategies in",
        "A Practical Real-World Example of",
        "Quick Checklist for",
    ]
    angle = random.choice(angles)
    adapted_topic = f"{angle} {base_topic}"
    logger.info(f"Selected adapted topic: '{adapted_topic}'")
    return adapted_topic
