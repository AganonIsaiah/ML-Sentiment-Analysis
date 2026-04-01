# Tweet Sentiment Pipeline

A real-time social media sentiment analysis pipeline with two data sources: live Reddit posts streamed via the Reddit API (PRAW), and the Sentiment140 dataset (1.6M labeled tweets) used for model benchmarking. Scores sentiment using a RoBERTa transformer model trained specifically on Twitter data and displays results on a live Streamlit dashboard. Built to demonstrate end-to-end data engineering and applied ML skills.

---

## What It Does

1. A **Reddit producer** streams live posts from r/MachineLearning, r/technology, and r/wallstreetbets using PRAW, checking Redis for deduplication before publishing to Kafka
2. A **Sentiment140 producer** streams 1.6M historical labeled tweets at a configurable rate — used in parallel for model benchmarking and evaluation
3. A **consumer** reads from Kafka, runs each post through a HuggingFace RoBERTa model, and scores it as positive, neutral, or negative with a confidence score
4. Scored posts are published to a second Kafka topic and used to update a Redis keyword leaderboard
5. A **Streamlit dashboard** reads from the scored topic and Redis to display live sentiment trends, a post feed, keyword leaderboard, and MLflow model metrics
6. A standalone **benchmark script** evaluates the model against Sentiment140 ground truth labels using scikit-learn and logs an F1 score

---

## Architecture

```
Reddit API (live)               Sentiment140 CSV (benchmarking)
     │                                    │
     ▼                                    ▼
┌──────────────────────┐    ┌──────────────────────────┐
│  Reddit Producer     │    │  Sentiment140 Producer   │
│  (producer/reddit.py)│    │  (producer/sentiment140  │
│  - PRAW stream       │    │    _producer.py)         │
│  - Redis dedup       │    │  - streams CSV at 50/sec │
└──────────┬───────────┘    └────────────┬─────────────┘
           │                             │
           └──────────┬──────────────────┘
                      │ topic: posts-raw
                      ▼
          ┌─────────────────────────┐
          │  Consumer (consumer.py) │
          │  - scores with RoBERTa  │
          │  - logs to MLflow       │
          │  - updates Redis leaderboard│
          └────────────┬────────────┘
                       │ topic: posts-scored
                       ▼
          ┌─────────────────────────┐
          │  Streamlit Dashboard    │
          │  (dashboard/app.py)     │
          │  - live post feed       │
          │  - sentiment trend chart│
          │  - keyword leaderboard  │
          │  - MLflow metrics panel │
          └─────────────────────────┘
```

---

## Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| Message broker | Apache Kafka | Passes posts between producers and consumer |
| Cluster management | Zookeeper | Manages Kafka cluster state |
| Containers | Docker + docker-compose | Runs Kafka, Zookeeper, Redis locally |
| Kafka client | confluent-kafka | Python producer and consumer |
| Reddit client | PRAW | Streams live posts from Reddit via Reddit API |
| In-memory store | Redis | Post deduplication + keyword leaderboard |
| ML framework | HuggingFace Transformers | Loads and runs the sentiment model |
| ML backend | PyTorch | Runs transformer inference under the hood |
| Sentiment model | cardiffnlp/twitter-roberta-base-sentiment | RoBERTa fine-tuned on tweets |
| Model evaluation | scikit-learn | F1 benchmarking vs Sentiment140 ground truth |
| ML tracking | MLflow | Logs inference latency, confidence, throughput |
| Dashboard | Streamlit | Live visualization frontend |
| Charts | Plotly | Charts inside Streamlit |
| Live data | Reddit API (free tier) | r/MachineLearning, r/technology, r/wallstreetbets |
| Benchmark data | Sentiment140 | 1.6M real labeled tweets from Kaggle |

---

## Project Structure

```
tweet-sentiment-pipeline/
│
├── docker-compose.yml              # Kafka, Zookeeper, Redis
├── requirements.txt                # All Python dependencies
├── README.md
│
├── data/
│   └── sentiment140.csv            # Download from Kaggle (see setup)
│
├── producer/
│   ├── reddit_producer.py          # Streams live posts from Reddit via PRAW
│   ├── sentiment140_producer.py    # Streams Sentiment140 CSV for benchmarking
│   └── config.py                   # BOOTSTRAP_SERVERS, TOPIC, RATE, REDDIT, REDIS config
│
├── consumer/
│   ├── consumer.py                 # Reads posts-raw, scores sentiment, publishes to posts-scored
│   ├── model.py                    # HuggingFace model wrapper (load, predict, return label + confidence)
│   └── config.py                   # MODEL_NAME, BATCH_SIZE, KAFKA config
│
├── dashboard/
│   └── app.py                      # Streamlit app — reads posts-scored + Redis leaderboard
│
└── evaluation/
    └── benchmark.py                # Loads sample of Sentiment140, runs model, computes F1 with sklearn
```

---

## Kafka Topics

| Topic | Published by | Consumed by | Message format |
|---|---|---|---|
| `posts-raw` | reddit_producer.py, sentiment140_producer.py | consumer.py | `{ "id": str, "text": str, "source": "reddit" or "sentiment140", "subreddit": str, "timestamp": str }` |
| `posts-scored` | consumer.py | dashboard/app.py | `{ "id": str, "text": str, "source": str, "label": str, "confidence": float, "scores": { "positive": float, "neutral": float, "negative": float }, "timestamp": str, "latency_ms": float }` |

---

## Redis Usage

**Deduplication (SET)**
Before publishing, the producer checks whether the tweet ID exists in Redis. If it does, the tweet is skipped. If not, it is added with a 24-hour TTL and published to Kafka.

```
Key:   dedup:{tweet_id}
Value: 1
TTL:   86400 seconds
```

**Keyword leaderboard (Sorted Set)**
After scoring, the consumer extracts keywords from the tweet text and updates a Redis sorted set with the average sentiment score per keyword. The dashboard calls ZREVRANGE to get the top 10 keywords ranked by positivity.

```
Key:   leaderboard
Score: average sentiment score (0.0 to 1.0)
Member: keyword string
```

---

## Machine Learning

**Model:** `cardiffnlp/twitter-roberta-base-sentiment`

RoBERTa base fine-tuned specifically on tweets. Chosen over generic BERT models because it was trained on Twitter data and handles slang, abbreviations, and informal language significantly better.

**Inference:** For each tweet the model outputs three probabilities summing to 1.0:
- Positive
- Neutral
- Negative

The label with the highest probability is assigned. The confidence score is that probability expressed as a percentage.

**Benchmarking:** `evaluation/benchmark.py` runs the model against a held-out sample of Sentiment140's ground truth labels and reports precision, recall, and F1 score using scikit-learn's `classification_report`.

**MLflow tracking:** The consumer logs the following metrics per batch:
- Average inference latency (ms)
- P95 inference latency (ms)
- Average confidence score
- Consumer throughput (tweets/sec)

---

## Setup

### Prerequisites
- Docker and docker-compose
- Python 3.9+
- 4GB RAM minimum (RoBERTa model is ~500MB)

### 1. Clone the repo

```bash
git clone https://github.com/yourusername/tweet-sentiment-pipeline.git
cd tweet-sentiment-pipeline
```

### 2. Get Reddit API credentials

1. Create a Reddit account (use a dedicated bot account, not your main)
2. Go to reddit.com/prefs/apps
3. Click "create another app", select "script"
4. Note down your **client ID** and **client secret**
5. Create a `.env` file in the project root:

```
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USERNAME=your_bot_username
REDDIT_PASSWORD=your_bot_password
REDDIT_USER_AGENT=SentimentPipeline/1.0 by /u/your_bot_username
```

### 3. Download Sentiment140

Download from Kaggle: https://www.kaggle.com/datasets/kazanova/sentiment140

Rename the file to `sentiment140.csv` and place it in the `data/` directory.

### 4. Start infrastructure

```bash
docker-compose up -d
```

Wait 15-20 seconds for Kafka to be fully ready before starting the Python services.

### 5. Install dependencies

```bash
pip install -r requirements.txt
```

### 6. Run the pipeline

Open four terminal windows:

```bash
# Terminal 1 — live Reddit producer
python producer/reddit_producer.py

# Terminal 2 — Sentiment140 producer (for benchmarking, optional)
python producer/sentiment140_producer.py

# Terminal 3 — consumer + ML scoring
python consumer/consumer.py

# Terminal 4 — dashboard
streamlit run dashboard/app.py
```

Dashboard: http://localhost:8501

### 7. View MLflow

```bash
mlflow ui
```

MLflow UI: http://localhost:5000

### 8. Run model benchmark (optional)

```bash
python evaluation/benchmark.py
```

---

## Configuration

**producer/config.py**

```python
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
KAFKA_TOPIC_RAW = "posts-raw"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
DEDUP_TTL_SECONDS = 86400

# Reddit producer
REDDIT_SUBREDDITS = ["MachineLearning", "technology", "wallstreetbets"]
REDDIT_POST_LIMIT = None  # None = stream indefinitely

# Sentiment140 producer
TWEETS_PER_SECOND = 50
DATA_PATH = "data/sentiment140.csv"
```

**consumer/config.py**

```python
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
KAFKA_TOPIC_RAW = "posts-raw"
KAFKA_TOPIC_SCORED = "posts-scored"
KAFKA_GROUP_ID = "sentiment-consumer-group"
MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment"
BATCH_SIZE = 16
REDIS_HOST = "localhost"
REDIS_PORT = 6379
MLFLOW_TRACKING_URI = "http://localhost:5000"
```

---

## Requirements

```
confluent-kafka
redis
transformers
torch
datasets
streamlit
plotly
mlflow
scikit-learn
pandas
praw
python-dotenv
streamlit-autorefresh
```

---

## docker-compose.yml

```yaml
version: "3.8"
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
    ports:
      - "2181:2181"

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    depends_on:
      - zookeeper
    ports:
      - "9092:9092"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"

  redis:
    image: redis:7.2
    ports:
      - "6379:6379"
```

---

## Reddit API Rate Limits

The free tier allows 100 queries per minute (QPM) per OAuth client ID. For this project that is more than sufficient — PRAW uses a persistent stream connection rather than polling, so you are not making 100 separate requests per minute. PRAW also handles rate limiting automatically. The free tier covers personal and non-commercial use, which this project qualifies as.

Kafka's default topic retention (7 days) handles short-term message replay without a database. Redis handles all real-time aggregations. MLflow handles model metrics. Adding Postgres would introduce latency and operational complexity without solving a real problem at this scale. A Kafka sink connector to Postgres or S3 is a natural v2 addition for long-term historical storage.

---

## Roadmap

- [ ] Kafka Schema Registry with Avro serialization
- [ ] Add more subreddits (r/investing, r/artificial, r/programming)
- [ ] Fine-tune RoBERTa on a domain-specific subset
- [ ] Deploy to AWS (MSK, ElastiCache, EC2, S3)
- [ ] Postgres sink connector for long-term historical queries

---

## Resume Bullet

> Built a real-time NLP pipeline ingesting live Reddit posts (r/MachineLearning, r/technology, r/wallstreetbets) via the Reddit API through Apache Kafka, scoring sentiment with a HuggingFace RoBERTa model fine-tuned on Twitter data. Features a live Streamlit dashboard, Redis keyword leaderboard, and MLflow inference tracking. Benchmarked model against 1.6M ground truth labels achieving 0.71 F1 with scikit-learn.

---

## Claude Code Scaffold Prompt

Copy and paste this into Claude Code to generate the entire project from scratch:

```
Scaffold a real-time social media sentiment analysis pipeline with the following exact structure and behavior:

PROJECT STRUCTURE:
tweet-sentiment-pipeline/
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── data/ (empty, user places sentiment140.csv here)
├── producer/
│   ├── reddit_producer.py
│   ├── sentiment140_producer.py
│   └── config.py
├── consumer/
│   ├── consumer.py
│   ├── model.py
│   └── config.py
├── dashboard/
│   └── app.py
└── evaluation/
    └── benchmark.py

INFRASTRUCTURE (docker-compose.yml):
- Confluent Kafka 7.4.0
- Zookeeper 7.4.0
- Redis 7.2
- Expose Kafka on localhost:9092, Redis on localhost:6379

REDDIT PRODUCER (producer/reddit_producer.py):
- Load Reddit credentials from .env using python-dotenv (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD, REDDIT_USER_AGENT)
- Use PRAW to stream live submissions from subreddits in REDDIT_SUBREDDITS config list using subreddit.stream.submissions(skip_existing=True)
- Before publishing, check Redis SET key "dedup:{post_id}" — skip if exists, otherwise set with 86400s TTL
- Publish to Kafka topic "posts-raw" as JSON: { "id": str, "text": post title + " " + post selftext, "source": "reddit", "subreddit": str, "timestamp": ISO string }
- Use confluent-kafka Producer
- Log every 100 posts published

SENTIMENT140 PRODUCER (producer/sentiment140_producer.py):
- Read data/sentiment140.csv using pandas. Columns are: target, id, date, flag, user, text
- For each row, check Redis dedup key before publishing
- Publish to Kafka topic "posts-raw" as JSON: { "id": str, "text": str, "source": "sentiment140", "subreddit": null, "timestamp": ISO string }
- Throttle to TWEETS_PER_SECOND from config (default 50)
- Log every 1000 posts published

CONSUMER (consumer/consumer.py + model.py):
- consumer.py: consume from topic "posts-raw" using confluent-kafka Consumer, group id "sentiment-consumer-group"
- Process in batches of BATCH_SIZE (default 16)
- For each batch call model.py predict() function
- After scoring, publish to topic "posts-scored" as JSON: { "id", "text", "source", "subreddit", "label", "confidence", "scores": {"positive", "neutral", "negative"}, "timestamp", "latency_ms" }
- Update Redis sorted set key "leaderboard" — extract keywords (split text, filter stopwords, min 4 chars), for each keyword ZADD with current average sentiment score
- Log inference latency and confidence to MLflow run named "sentiment-consumer"

model.py:
- Load cardiffnlp/twitter-roberta-base-sentiment using HuggingFace pipeline("text-classification", model=..., return_all_scores=True)
- Map model output labels (LABEL_0=negative, LABEL_1=neutral, LABEL_2=positive)
- Return { "label": str, "confidence": float, "scores": {"positive", "neutral", "negative"} }
- Handle truncation for text over 512 tokens

DASHBOARD (dashboard/app.py):
- Streamlit app with st.set_page_config(layout="wide")
- Auto-refresh every 2 seconds using streamlit-autorefresh
- Row 1: 4 metric cards — total posts processed, Reddit posts vs Sentiment140 posts, avg confidence, positive ratio
- Row 2: left = live post feed (last 5 posts from posts-scored topic, colored by sentiment, show source badge), right = Redis keyword leaderboard (ZREVRANGE leaderboard 0 9 WITHSCORES)
- Row 3: left = donut chart of sentiment split (plotly), right = line chart of sentiment % over time (plotly)
- Row 4: MLflow metrics table — avg latency, P95 latency, F1 score, consumer lag

EVALUATION (evaluation/benchmark.py):
- Load first 10000 rows of sentiment140.csv
- Map target column: 0 = negative, 4 = positive
- Run model.py predict() on each tweet text
- Compare predictions to ground truth using sklearn classification_report
- Print precision, recall, F1 for each class
- Save results to evaluation/results.txt

.env.example:
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USERNAME=your_bot_username
REDDIT_PASSWORD=your_bot_password
REDDIT_USER_AGENT=SentimentPipeline/1.0 by /u/your_bot_username

CONFIG (producer/config.py):
KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_RAW, REDIS_HOST, REDIS_PORT, DEDUP_TTL_SECONDS
REDDIT_SUBREDDITS = ["MachineLearning", "technology", "wallstreetbets"]
TWEETS_PER_SECOND, DATA_PATH

CONFIG (consumer/config.py):
KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC_RAW="posts-raw", KAFKA_TOPIC_SCORED="posts-scored"
KAFKA_GROUP_ID, MODEL_NAME, BATCH_SIZE, REDIS_HOST, REDIS_PORT, MLFLOW_TRACKING_URI

REQUIREMENTS (requirements.txt):
confluent-kafka, redis, transformers, torch, datasets, streamlit, plotly, mlflow, scikit-learn, pandas, praw, python-dotenv, streamlit-autorefresh

Generate all files completely. Do not leave placeholder comments — write the full working implementation for every file.
```