"""
Streamlit real-time dashboard for the sentiment analysis pipeline.

Reads from:
  - Kafka: posts-scored  (live feed + trend data)
  - Redis: leaderboard:sum / leaderboard:count  (keyword scores)
  - MLflow: latest run metrics

Run: streamlit run dashboard/app.py
"""

import json
import os
import sys
import time
from collections import deque
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import redis
import streamlit as st
from confluent_kafka import Consumer, KafkaError
from streamlit_autorefresh import st_autorefresh

# ─── path fix so we can import consumer config ───────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "consumer"))

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_SCORED = "posts-scored"
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

LEADERBOARD_KEY = "leaderboard"
FEED_MAX = 200          # max posts to keep in session state
POLL_INTERVAL_MS = 3000  # auto-refresh every 3 s

LABEL_COLOR = {
    "positive": "#2ecc71",
    "neutral": "#f39c12",
    "negative": "#e74c3c",
}

# ─── Kafka helper (cached per session) ───────────────────────────────────────

@st.cache_resource
def get_kafka_consumer():
    c = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": "dashboard-consumer",
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )
    c.subscribe([KAFKA_TOPIC_SCORED])
    return c


@st.cache_resource
def get_redis_client():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


# ─── Poll Kafka for new messages ─────────────────────────────────────────────

def poll_kafka(consumer: Consumer, max_msgs: int = 50) -> list[dict]:
    msgs = []
    deadline = time.time() + 0.5  # poll for up to 500 ms
    while time.time() < deadline and len(msgs) < max_msgs:
        m = consumer.poll(0.05)
        if m is None or m.error():
            continue
        try:
            msgs.append(json.loads(m.value().decode("utf-8")))
        except Exception:
            pass
    return msgs


# ─── Redis leaderboard ───────────────────────────────────────────────────────

def get_leaderboard(r: redis.Redis, top_n: int = 20) -> pd.DataFrame:
    """Return top-N keywords by average sentiment score."""
    top_words = r.zrevrange(f"{LEADERBOARD_KEY}:count", 0, top_n - 1, withscores=True)
    if not top_words:
        return pd.DataFrame(columns=["keyword", "avg_score", "count"])

    rows = []
    for word, count in top_words:
        total = r.zscore(f"{LEADERBOARD_KEY}:sum", word) or 0
        avg = total / count if count else 0
        rows.append({"keyword": word, "avg_score": avg, "count": int(count)})

    return pd.DataFrame(rows).sort_values("avg_score", ascending=False)


# ─── App layout ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Sentiment Pipeline",
    page_icon="📊",
    layout="wide",
)

# Auto-refresh
st_autorefresh(interval=POLL_INTERVAL_MS, key="auto_refresh")

st.title("📊 Real-Time Sentiment Analysis Pipeline")
st.caption(f"Refreshes every {POLL_INTERVAL_MS // 1000} seconds · {datetime.now().strftime('%H:%M:%S')}")

# ─── Session state ────────────────────────────────────────────────────────────

if "feed" not in st.session_state:
    st.session_state.feed = deque(maxlen=FEED_MAX)
if "trend" not in st.session_state:
    st.session_state.trend = []  # list of {timestamp, positive, neutral, negative}

# ─── Pull new data ────────────────────────────────────────────────────────────

try:
    consumer = get_kafka_consumer()
    new_msgs = poll_kafka(consumer)
except Exception as e:
    st.warning(f"Kafka unavailable: {e}")
    new_msgs = []

for m in new_msgs:
    st.session_state.feed.appendleft(m)

# Aggregate trend bucket
if new_msgs:
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for m in new_msgs:
        lbl = m.get("label", "neutral")
        counts[lbl] = counts.get(lbl, 0) + 1
    st.session_state.trend.append(
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            **counts,
        }
    )
    # Keep last 60 buckets (3 min at 3-s refresh)
    st.session_state.trend = st.session_state.trend[-60:]

try:
    r = get_redis_client()
    leaderboard_df = get_leaderboard(r)
    redis_ok = True
except Exception as e:
    st.warning(f"Redis unavailable: {e}")
    leaderboard_df = pd.DataFrame(columns=["keyword", "avg_score", "count"])
    redis_ok = False

# ─── KPI row ─────────────────────────────────────────────────────────────────

feed_list = list(st.session_state.feed)
total = len(feed_list)
pos = sum(1 for m in feed_list if m.get("label") == "positive")
neu = sum(1 for m in feed_list if m.get("label") == "neutral")
neg = sum(1 for m in feed_list if m.get("label") == "negative")
avg_conf = (
    sum(m.get("confidence", 0) for m in feed_list) / total if total else 0
)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Posts", total)
col2.metric("Positive", pos, delta=None)
col3.metric("Neutral", neu)
col4.metric("Negative", neg)
col5.metric("Avg Confidence", f"{avg_conf:.1%}")

st.divider()

# ─── Main content ─────────────────────────────────────────────────────────────

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Sentiment Trend")
    if st.session_state.trend:
        trend_df = pd.DataFrame(st.session_state.trend)
        fig = go.Figure()
        for label, color in LABEL_COLOR.items():
            fig.add_trace(
                go.Scatter(
                    x=trend_df["timestamp"],
                    y=trend_df[label],
                    mode="lines+markers",
                    name=label.capitalize(),
                    line=dict(color=color, width=2),
                )
            )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            height=260,
            legend=dict(orientation="h"),
            xaxis_title=None,
            yaxis_title="Posts",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Waiting for data …")

    st.subheader("Live Post Feed")
    if feed_list:
        for m in feed_list[:30]:
            label = m.get("label", "neutral")
            conf = m.get("confidence", 0)
            src = m.get("source", "?")
            sub = m.get("subreddit") or ""
            text = m.get("text", "")[:200]
            color = LABEL_COLOR.get(label, "#888")
            badge = f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:0.75rem">{label.upper()}</span>'
            source_tag = f"r/{sub}" if sub else src
            st.markdown(
                f"{badge} &nbsp; **{source_tag}** · {conf:.0%} confidence<br>"
                f"<small>{text}</small>",
                unsafe_allow_html=True,
            )
            st.markdown("---")
    else:
        st.info("No posts yet. Start the producer and consumer.")

with right:
    st.subheader("Sentiment Distribution")
    if total > 0:
        pie_fig = px.pie(
            names=["Positive", "Neutral", "Negative"],
            values=[pos, neu, neg],
            color=["Positive", "Neutral", "Negative"],
            color_discrete_map={
                "Positive": LABEL_COLOR["positive"],
                "Neutral": LABEL_COLOR["neutral"],
                "Negative": LABEL_COLOR["negative"],
            },
            hole=0.4,
        )
        pie_fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            height=260,
            showlegend=True,
            legend=dict(orientation="h"),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(pie_fig, use_container_width=True)
    else:
        st.info("Waiting for data …")

    st.subheader("Keyword Leaderboard")
    if not leaderboard_df.empty:
        bar_fig = px.bar(
            leaderboard_df.head(15),
            x="avg_score",
            y="keyword",
            orientation="h",
            color="avg_score",
            color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
            range_color=[0, 1],
            labels={"avg_score": "Avg Sentiment", "keyword": ""},
        )
        bar_fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            height=400,
            coloraxis_showscale=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(bar_fig, use_container_width=True)
    else:
        st.info("Leaderboard is empty. Redis may be unavailable or no data yet.")
