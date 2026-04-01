import os
from dotenv import load_dotenv

load_dotenv()

# Kafka
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_RAW = "posts-raw"
KAFKA_TOPIC_SCORED = "posts-scored"
KAFKA_GROUP_ID = "sentiment-consumer-group"

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Model
MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment"
BATCH_SIZE = 16

# MLflow
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MLFLOW_EXPERIMENT_NAME = "sentiment-pipeline"

# Logging interval (log metrics every N messages)
METRICS_LOG_INTERVAL = 100
