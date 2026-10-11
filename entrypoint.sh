#!/usr/bin/env bash
set -e

# ==============================================================================
# Container Entrypoint Script: Lead Cleaner Multi-Tenant Deployment
# Runs both FastAPI OAuth / API background server and Streamlit UI.
# ==============================================================================

FASTAPI_PORT=${PORT:-8000}
STREAMLIT_PORT=${STREAMLIT_SERVER_PORT:-8501}

echo "Starting FastAPI OAuth server on port ${FASTAPI_PORT}..."
uvicorn server:app --host 0.0.0.0 --port "${FASTAPI_PORT}" &
FASTAPI_PID=$!

echo "Starting Streamlit UI on port ${STREAMLIT_PORT}..."
streamlit run app.py \
    --server.port "${STREAMLIT_PORT}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &
STREAMLIT_PID=$!

# Trap signals for graceful shutdown
trap "kill -TERM ${FASTAPI_PID} ${STREAMLIT_PID}" SIGINT SIGTERM

# Wait for both processes
wait -n ${FASTAPI_PID} ${STREAMLIT_PID}
