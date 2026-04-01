import os
from dotenv import load_dotenv

load_dotenv()

# Kafka
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_RAW = "posts-raw"

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
DEDUP_TTL_SECONDS = 86400  # 24 hours

# Reddit
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "SentimentPipeline/1.0")
REDDIT_SUBREDDITS = ["MachineLearning", "technology", "wallstreetbets"]

# Sentiment140
SENTIMENT140_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "sentiment140.csv")
TWEETS_PER_SECOND = 50
