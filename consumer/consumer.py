"""
Kafka consumer that reads from posts-raw, scores each post with RoBERTa,
updates the Redis keyword leaderboard, publishes to posts-scored, and logs
metrics to MLflow.
"""

import json
import logging
import re
import signal
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import List

import mlflow
import redis
from confluent_kafka import Consumer, KafkaError, Producer

from config import (
    BATCH_SIZE,
    KAFKA_BOOTSTRAP_SERVERS,
    KAFKA_GROUP_ID,
    KAFKA_TOPIC_RAW,
    KAFKA_TOPIC_SCORED,
    METRICS_LOG_INTERVAL,
    MLFLOW_EXPERIMENT_NAME,
    MLFLOW_TRACKING_URI,
    MODEL_NAME,
    REDIS_HOST,
    REDIS_PORT,
)
from model import SentimentModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [consumer] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# Regex to extract meaningful keywords (alpha, 4+ chars, no stopwords)
_STOPWORDS = {
    "that", "this", "with", "have", "from", "they", "been", "will",
    "would", "could", "should", "their", "there", "were", "when",
    "what", "which", "your", "more", "some", "just", "about", "into",
    "than", "then", "only", "also", "very", "much", "many", "such",
    "over", "like", "well", "even", "most", "after", "before",
}
_WORD_RE = re.compile(r"[a-z]{4,}")

LEADERBOARD_KEY = "leaderboard"
LEADERBOARD_MAX = 100


def extract_keywords(text: str) -> List[str]:
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if w not in _STOPWORDS][:10]


def update_leaderboard(r: redis.Redis, text: str, label: str):
    """
    Map label to a sentiment score (positive=1, neutral=0.5, negative=0),
    then update a sorted set where the score is a running average approximated
    via ZINCRBY. We keep it simple: increment by the sentiment value and a
    separate counter key so we can derive average on read.
    """
    score = {"positive": 1.0, "neutral": 0.5, "negative": 0.0}.get(label, 0.5)
    keywords = extract_keywords(text)
    pipe = r.pipeline()
    for word in keywords:
        pipe.zincrby(f"{LEADERBOARD_KEY}:sum", score, word)
        pipe.zincrby(f"{LEADERBOARD_KEY}:count", 1.0, word)
    pipe.execute()

    # Trim to top LEADERBOARD_MAX keywords by count
    r.zremrangebyrank(f"{LEADERBOARD_KEY}:count", 0, -(LEADERBOARD_MAX + 2))
    r.zremrangebyrank(f"{LEADERBOARD_KEY}:sum", 0, -(LEADERBOARD_MAX + 2))


def delivery_report(err, msg):
    if err:
        log.error("Delivery failed for %s: %s", msg.key(), err)


class MetricsTracker:
    def __init__(self):
        self.latencies: deque = deque(maxlen=1000)
        self.confidences: deque = deque(maxlen=1000)
        self.total = 0
        self.start_time = time.time()

    def record(self, latency_ms: float, confidence: float):
        self.latencies.append(latency_ms)
        self.confidences.append(confidence)
        self.total += 1

    def snapshot(self) -> dict:
        elapsed = max(time.time() - self.start_time, 1e-9)
        lats = sorted(self.latencies)
        p95_idx = int(len(lats) * 0.95) if lats else 0
        return {
            "avg_latency_ms": sum(lats) / len(lats) if lats else 0,
            "p95_latency_ms": lats[p95_idx] if lats else 0,
            "avg_confidence": sum(self.confidences) / len(self.confidences) if self.confidences else 0,
            "throughput_per_sec": self.total / elapsed,
        }


def main():
    model = SentimentModel(MODEL_NAME)

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": KAFKA_GROUP_ID,
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe([KAFKA_TOPIC_RAW])

    producer = Producer({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})

    # MLflow setup
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    active_run = mlflow.start_run(run_name=f"consumer-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}")
    log.info("MLflow run: %s", active_run.info.run_id)

    metrics = MetricsTracker()
    running = True

    def shutdown(sig, frame):
        nonlocal running
        log.info("Shutting down …")
        running = False

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("Consumer started. Reading from '%s' → '%s'", KAFKA_TOPIC_RAW, KAFKA_TOPIC_SCORED)

    batch_msgs = []
    batch_payloads = []

    def flush_batch():
        if not batch_msgs:
            return

        texts = [p["text"] for p in batch_payloads]
        predictions = model.predict_batch(texts)

        for payload, pred in zip(batch_payloads, predictions):
            update_leaderboard(r, payload["text"], pred["label"])

            scored = {**payload, **pred}
            producer.produce(
                KAFKA_TOPIC_SCORED,
                key=scored["id"],
                value=json.dumps(scored),
                callback=delivery_report,
            )
            producer.poll(0)

            metrics.record(pred["latency_ms"], pred["confidence"])

        producer.flush()
        batch_msgs.clear()
        batch_payloads.clear()

        if metrics.total % METRICS_LOG_INTERVAL < BATCH_SIZE:
            snap = metrics.snapshot()
            log.info(
                "Processed %d | avg_lat=%.1fms p95=%.1fms conf=%.2f tps=%.1f",
                metrics.total,
                snap["avg_latency_ms"],
                snap["p95_latency_ms"],
                snap["avg_confidence"],
                snap["throughput_per_sec"],
            )
            mlflow.log_metrics(snap, step=metrics.total)

    try:
        while running:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                flush_batch()
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    flush_batch()
                else:
                    log.error("Kafka error: %s", msg.error())
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                log.warning("Skipping malformed message: %s", e)
                continue

            if not payload.get("text"):
                continue

            batch_msgs.append(msg)
            batch_payloads.append(payload)

            if len(batch_msgs) >= BATCH_SIZE:
                flush_batch()

    finally:
        flush_batch()
        consumer.close()
        mlflow.end_run()
        log.info("Shutdown complete. Total processed: %d", metrics.total)


if __name__ == "__main__":
    main()
