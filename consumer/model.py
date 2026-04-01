"""
HuggingFace RoBERTa sentiment model wrapper.

Model: cardiffnlp/twitter-roberta-base-sentiment
Labels: 0=Negative, 1=Neutral, 2=Positive
"""

import logging
import time
from typing import List

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

log = logging.getLogger(__name__)

LABEL_MAP = {0: "negative", 1: "neutral", 2: "positive"}


class SentimentModel:
    def __init__(self, model_name: str):
        log.info("Loading tokenizer and model: %s", model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
        log.info("Model loaded on %s", self.device)

    def predict_batch(self, texts: List[str]) -> List[dict]:
        """
        Score a batch of texts.

        Returns a list of dicts with keys:
            label       – "positive" | "neutral" | "negative"
            confidence  – float 0-1 (probability of the winning label)
            scores      – {"positive": float, "neutral": float, "negative": float}
            latency_ms  – inference time for the full batch (ms), same for all items
        """
        t0 = time.perf_counter()
        encoded = self.tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=128,
        ).to(self.device)

        with torch.no_grad():
            logits = self.model(**encoded).logits
            probs = torch.softmax(logits, dim=-1).cpu().numpy()

        latency_ms = (time.perf_counter() - t0) * 1000

        results = []
        for prob in probs:
            idx = int(prob.argmax())
            results.append(
                {
                    "label": LABEL_MAP[idx],
                    "confidence": float(prob[idx]),
                    "scores": {
                        "negative": float(prob[0]),
                        "neutral": float(prob[1]),
                        "positive": float(prob[2]),
                    },
                    "latency_ms": latency_ms,
                }
            )
        return results
