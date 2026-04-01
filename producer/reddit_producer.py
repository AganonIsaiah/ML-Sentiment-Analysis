"""
Streams live Reddit posts from configured subreddits into the posts-raw Kafka topic.
Uses Redis for deduplication so the same post is never processed twice.
"""

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

import praw
import redis
from confluent_kafka import Producer

from config import (
    DEDUP_TTL_SECONDS,
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC_RAW,
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_SUBREDDITS,
    REDDIT_USER_AGENT,
    REDIS_HOST,
    REDIS_PORT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [reddit_producer] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def build_message(submission) -> dict:
    text = submission.selftext.strip() or submission.title.strip()
    return {
        "id": str(submission.id),
        "text": text[:512],  # cap length for model
        "source": "reddit",
        "subreddit": submission.subreddit.display_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def delivery_report(err, msg):
    if err:
        log.error("Delivery failed for %s: %s", msg.key(), err)


def main():
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        log.error(
            "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET must be set in .env. "
            "Copy .env.example to .env and fill in your credentials."
        )
        sys.exit(1)

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})

    subreddit_str = "+".join(REDDIT_SUBREDDITS)
    log.info("Listening on r/%s → topic '%s'", subreddit_str, KAFKA_TOPIC_RAW)

    published = 0
    skipped = 0

    for submission in reddit.subreddit(subreddit_str).stream.submissions(skip_existing=True):
        dedup_key = f"dedup:{submission.id}"
        if r.exists(dedup_key):
            skipped += 1
            continue

        msg = build_message(submission)
        if not msg["text"]:
            continue

        r.setex(dedup_key, DEDUP_TTL_SECONDS, 1)
        producer.produce(
            KAFKA_TOPIC_RAW,
            key=msg["id"],
            value=json.dumps(msg),
            callback=delivery_report,
        )
        producer.poll(0)
        published += 1

        if published % 10 == 0:
            log.info("Published %d posts (skipped %d duplicates)", published, skipped)


if __name__ == "__main__":
    main()
