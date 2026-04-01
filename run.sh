#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[run]${NC} $*"; }
warn()  { echo -e "${YELLOW}[run]${NC} $*"; }
error() { echo -e "${RED}[run]${NC} $*"; exit 1; }

# ── cleanup on exit ───────────────────────────────────────────────────────────
PIDS=()
cleanup() {
    echo ""
    info "Shutting down…"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    docker compose down --timeout 5 2>/dev/null || true
    info "Done."
}
trap cleanup EXIT INT TERM

# ── checks ────────────────────────────────────────────────────────────────────
[ -f data/sentiment140.csv ] || error "data/sentiment140.csv not found. Download from https://www.kaggle.com/datasets/kazanova/sentiment140"
[ -f env/bin/activate ]      || error "Virtual env not found. Run: python3 -m venv env && pip install -r requirements.txt"

source env/bin/activate

# ── docker infrastructure ─────────────────────────────────────────────────────
info "Starting Docker services…"
docker compose up -d

info "Waiting for Kafka to be ready…"
until docker exec kafka kafka-broker-api-versions --bootstrap-server localhost:9092 &>/dev/null; do
    echo -n "."
    sleep 2
done
echo ""
info "Kafka is ready."

info "Waiting for Redis…"
until docker exec redis redis-cli ping 2>/dev/null | grep -q PONG; do
    echo -n "."
    sleep 1
done
echo ""
info "Redis is ready."

# ── consumer ──────────────────────────────────────────────────────────────────
info "Starting consumer…"
(cd consumer && python consumer.py 2>&1 | sed 's/^/[consumer] /') &
PIDS+=($!)
sleep 3   # give model time to load

# ── sentiment140 producer ─────────────────────────────────────────────────────
info "Starting Sentiment140 producer…"
(cd producer && python sentiment140_producer.py 2>&1 | sed 's/^/[producer] /') &
PIDS+=($!)
sleep 1

# ── dashboard ─────────────────────────────────────────────────────────────────
info "Starting Streamlit dashboard → http://localhost:8501"
(streamlit run dashboard/app.py --server.headless true 2>&1 | sed 's/^/[dashboard] /') &
PIDS+=($!)

info "Pipeline running. Press Ctrl+C to stop everything."
wait
