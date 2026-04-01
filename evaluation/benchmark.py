"""
Evaluates the RoBERTa sentiment model against Sentiment140 ground truth labels.

Usage:
    python evaluation/benchmark.py [--limit N] [--csv PATH]

The script reads N rows from the Sentiment140 CSV, runs them through the model
in batches, then prints a classification report and F1 scores.
"""

import argparse
import logging
import os
import sys
import time

import pandas as pd
from sklearn.metrics import classification_report, f1_score

# Allow imports from consumer/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "consumer"))
from model import SentimentModel  # noqa: E402
from config import MODEL_NAME, BATCH_SIZE  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

COLUMNS = ["polarity", "id", "date", "query", "user", "text"]
POLARITY_MAP = {0: "negative", 2: "neutral", 4: "positive"}

DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "sentiment140.csv")


def load_sample(csv_path: str, limit: int) -> pd.DataFrame:
    log.info("Loading %d rows from %s", limit, csv_path)
    df = pd.read_csv(
        csv_path,
        encoding="latin-1",
        header=None,
        names=COLUMNS,
        usecols=["id", "text", "polarity"],
        nrows=limit,
    )
    df = df.dropna(subset=["text"])
    df["label"] = df["polarity"].map(POLARITY_MAP)
    return df


def run_benchmark(model: SentimentModel, df: pd.DataFrame) -> None:
    texts = df["text"].astype(str).tolist()
    y_true = df["label"].tolist()
    y_pred = []

    log.info("Running inference on %d texts (batch_size=%d) …", len(texts), BATCH_SIZE)
    t0 = time.time()

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        preds = model.predict_batch(batch)
        y_pred.extend(p["label"] for p in preds)

        if (i // BATCH_SIZE + 1) % 20 == 0:
            elapsed = time.time() - t0
            rate = (i + len(batch)) / elapsed
            log.info("  %d / %d (%.0f texts/sec)", i + len(batch), len(texts), rate)

    elapsed = time.time() - t0
    log.info("Inference complete in %.1f s (%.0f texts/sec)", elapsed, len(texts) / elapsed)

    labels = ["negative", "neutral", "positive"]

    print("\n" + "=" * 60)
    print("CLASSIFICATION REPORT")
    print("=" * 60)
    print(classification_report(y_true, y_pred, labels=labels, digits=4))

    macro_f1 = f1_score(y_true, y_pred, labels=labels, average="macro")
    weighted_f1 = f1_score(y_true, y_pred, labels=labels, average="weighted")

    print(f"Macro F1:    {macro_f1:.4f}")
    print(f"Weighted F1: {weighted_f1:.4f}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Benchmark RoBERTa on Sentiment140")
    parser.add_argument("--limit", type=int, default=5000, help="Number of rows to evaluate (default: 5000)")
    parser.add_argument("--csv", default=DEFAULT_CSV, help="Path to sentiment140.csv")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        log.error(
            "CSV not found: %s\n"
            "Download from https://www.kaggle.com/datasets/kazanova/sentiment140 "
            "and place it at data/sentiment140.csv",
            args.csv,
        )
        sys.exit(1)

    df = load_sample(args.csv, args.limit)
    log.info("Label distribution:\n%s", df["label"].value_counts().to_string())

    model = SentimentModel(MODEL_NAME)
    run_benchmark(model, df)


if __name__ == "__main__":
    main()
