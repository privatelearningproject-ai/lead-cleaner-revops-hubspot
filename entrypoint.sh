#!/usr/bin/env bash
set -e

# ==============================================================================
# Container Entrypoint Script: Lead Cleaner Multi-Tenant Deployment
# Runs both FastAPI OAuth / API background server and Streamlit UI.
# ==============================================================================

PUBLIC_PORT=${PORT:-8000}
STREAMLIT_INTERNAL_PORT=${STREAMLIT_INTERNAL_PORT:-8501}

echo "Starting Streamlit UI internally on port ${STREAMLIT_INTERNAL_PORT}..."
streamlit run app.py \
    --server.port "${STREAMLIT_INTERNAL_PORT}" \
    --server.address 127.0.0.1 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection true \
    --browser.gatherUsageStats false &
STREAMLIT_PID=$!

echo "Starting FastAPI OAuth & Gateway server on public port ${PUBLIC_PORT}..."
uvicorn server:app --host 0.0.0.0 --port "${PUBLIC_PORT}" &
FASTAPI_PID=$!

# Trap signals for graceful shutdown
trap "kill -TERM ${FASTAPI_PID} ${STREAMLIT_PID}" SIGINT SIGTERM

# Wait for both processes
wait -n ${FASTAPI_PID} ${STREAMLIT_PID}
