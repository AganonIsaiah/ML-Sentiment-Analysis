"""
Streams the Sentiment140 dataset (1.6M tweets) into the posts-raw Kafka topic.
Used for model benchmarking and evaluation alongside live Reddit data.

Dataset: https://www.kaggle.com/datasets/kazanova/sentiment140
Place the CSV at data/sentiment140.csv before running.
"""

import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

import pandas as pd
from confluent_kafka import Producer

from config import (
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_TOPIC_RAW,
    SENTIMENT140_CSV,
    TWEETS_PER_SECOND,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [s140_producer] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Sentiment140 columns (no header in the file)
COLUMNS = ["polarity", "id", "date", "query", "user", "text"]

# Polarity mapping: 0=negative, 2=neutral, 4=positive
POLARITY_MAP = {0: "negative", 2: "neutral", 4: "positive"}


def delivery_report(err, msg):
    if err:
        log.error("Delivery failed for %s: %s", msg.key(), err)


def load_dataset(path: str) -> pd.DataFrame:
    log.info("Loading Sentiment140 from %s …", path)
    df = pd.read_csv(
        path,
        encoding="latin-1",
        header=None,
        names=COLUMNS,
        usecols=["id", "text", "polarity"],
    )
    df = df.dropna(subset=["text"])
    df["label"] = df["polarity"].map(POLARITY_MAP)
    log.info("Loaded %d rows", len(df))
    return df


def main():
    try:
        df = load_dataset(SENTIMENT140_CSV)
    except FileNotFoundError:
        log.error(
            "Sentiment140 CSV not found at %s. "
            "Download from https://www.kaggle.com/datasets/kazanova/sentiment140 "
            "and place it at data/sentiment140.csv",
            SENTIMENT140_CSV,
        )
        sys.exit(1)

    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    interval = 1.0 / TWEETS_PER_SECOND

    log.info("Streaming %d tweets at %d/sec → topic '%s'", len(df), TWEETS_PER_SECOND, KAFKA_TOPIC_RAW)

    for i, row in df.iterrows():
        msg = {
            "id": f"s140-{row['id']}",
            "text": str(row["text"])[:512],
            "source": "sentiment140",
            "subreddit": None,
            "ground_truth_label": row["label"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        producer.produce(
            KAFKA_TOPIC_RAW,
            key=msg["id"],
            value=json.dumps(msg),
            callback=delivery_report,
        )
        producer.poll(0)

        if (i + 1) % 1000 == 0:
            producer.flush()
            log.info("Streamed %d / %d tweets", i + 1, len(df))

        time.sleep(interval)

    producer.flush()
    log.info("Done — streamed all %d tweets", len(df))


if __name__ == "__main__":
    main()
