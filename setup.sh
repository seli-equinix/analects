#!/bin/bash
# CCA Full Stack — Setup & Management
# Usage: ./setup.sh [setup|pull|start|stop|status|logs]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

usage() {
    echo "CCA Full Stack Manager"
    echo ""
    echo "Usage: ./setup.sh <command>"
    echo ""
    echo "Commands:"
    echo "  setup     First-time setup: check prereqs, create configs, pull images"
    echo "  pull      Pull all Docker images from Docker Hub"
    echo "  start     Start the full stack (docker compose up -d)"
    echo "  stop      Stop the full stack (docker compose down)"
    echo "  status    Health check all services"
    echo "  logs      View CCA logs (docker compose logs -f cca)"
}

check_prereqs() {
    echo -e "${BLUE}Checking prerequisites...${NC}"

    # Docker
    if ! command -v docker &>/dev/null; then
        echo -e "  ${RED}✗${NC} Docker is not installed"
        echo "    Install: https://docs.docker.com/engine/install/"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"

    # Docker Compose v2
    if ! docker compose version &>/dev/null; then
        echo -e "  ${RED}✗${NC} Docker Compose v2 is not installed"
        echo "    Install: https://docs.docker.com/compose/install/"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} $(docker compose version --short 2>/dev/null || docker compose version | head -1)"

    # curl
    if ! command -v curl &>/dev/null; then
        echo -e "  ${RED}✗${NC} curl is not installed"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} curl"

    # NVIDIA GPU
    if docker info 2>/dev/null | grep -q -i nvidia; then
        echo -e "  ${GREEN}✓${NC} NVIDIA Docker runtime detected"
    elif command -v nvidia-smi &>/dev/null; then
        GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        echo -e "  ${GREEN}✓${NC} GPU: ${GPU}"
    else
        echo -e "  ${YELLOW}!${NC} NVIDIA GPU not detected (required for vLLM services)"
    fi

    # Models directory
    local models_dir="${MODELS_DIR:-/data/models}"
    if [ -d "$models_dir" ]; then
        echo -e "  ${GREEN}✓${NC} Models directory: ${models_dir}"
        for model in Qwen3.5-9B-FP8 Qwen3-Embedding-8B; do
            if [ -d "${models_dir}/${model}" ]; then
                echo -e "    ${GREEN}✓${NC} ${model}"
            else
                echo -e "    ${YELLOW}!${NC} ${model} not found"
            fi
        done
        if [ -d "${models_dir}/functionary" ]; then
            echo -e "    ${GREEN}✓${NC} functionary/"
        else
            echo -e "    ${YELLOW}!${NC} functionary/ not found"
        fi
    else
        echo -e "  ${YELLOW}!${NC} Models directory ${models_dir} not found"
        echo "    Set MODELS_DIR in .env after setup"
    fi
}

setup() {
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
    echo -e "${BLUE}  CCA Full Stack — First Time Setup${NC}"
    echo -e "${BLUE}═══════════════════════════════════════${NC}"
    echo ""

    check_prereqs
    echo ""

    # Create .env
    if [ ! -f "${SCRIPT_DIR}/.env" ]; then
        cp "${SCRIPT_DIR}/.env.example" "${SCRIPT_DIR}/.env"
        echo -e "${GREEN}✓${NC} Created .env — ${YELLOW}edit with your passwords and paths${NC}"
    else
        echo -e "${GREEN}✓${NC} .env already exists"
    fi

    # Create config.toml
    if [ ! -f "${SCRIPT_DIR}/config.toml" ]; then
        cp "${SCRIPT_DIR}/config.toml.example" "${SCRIPT_DIR}/config.toml"
        echo -e "${GREEN}✓${NC} Created config.toml — ${YELLOW}edit to set your main vLLM URL${NC}"
    else
        echo -e "${GREEN}✓${NC} config.toml already exists"
    fi

    # Create infrastructure.toml
    if [ ! -f "${SCRIPT_DIR}/infrastructure.toml" ]; then
        cp "${SCRIPT_DIR}/infrastructure.toml.example" "${SCRIPT_DIR}/infrastructure.toml"
        echo -e "${GREEN}✓${NC} Created infrastructure.toml (optional — for INFRA expert)"
    else
        echo -e "${GREEN}✓${NC} infrastructure.toml already exists"
    fi

    echo ""
    echo -e "${BLUE}Pulling Docker images...${NC}"
    pull_images

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
    echo -e "${GREEN}  Setup complete!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. nano .env              — Set REDIS_PASSWORD, MODELS_DIR, VLLM_URL"
    echo "  2. nano config.toml       — Set main vLLM URL in [providers.local.coder] base_url"
    echo "  3. Download model weights  — See README.md for model list"
    echo "  4. ./setup.sh start       — Start all 11 containers"
    echo "  5. curl localhost:8500/health"
}

pull_images() {
    cd "${SCRIPT_DIR}"
    docker compose pull 2>&1 | grep -v "^$" || true
    echo -e "  ${GREEN}✓${NC} All images pulled"
}

start_stack() {
    if [ ! -f "${SCRIPT_DIR}/.env" ]; then
        echo -e "${RED}ERROR: .env not found. Run './setup.sh setup' first.${NC}"
        exit 1
    fi
    echo -e "${BLUE}Starting CCA full stack...${NC}"
    cd "${SCRIPT_DIR}"
    docker compose up -d
    echo ""
    echo -e "${GREEN}Stack started.${NC} Checking health in 15 seconds..."
    sleep 15
    check_health
}

stop_stack() {
    echo -e "${BLUE}Stopping CCA full stack...${NC}"
    cd "${SCRIPT_DIR}"
    docker compose down
    echo -e "${GREEN}Stack stopped.${NC}"
}

check_health() {
    echo -e "${BLUE}Service health:${NC}"

    local services="CCA:8500:/health Embedding:8200:/health Note-taker:8400:/health Functionary:8001:/health Qdrant:6333:/ SearXNG:8888:/healthz"

    for svc in $services; do
        IFS=: read -r name port path <<< "$svc"
        if curl -sf "http://localhost:${port}${path}" >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} ${name} (port ${port})"
        else
            echo -e "  ${RED}✗${NC} ${name} (port ${port})"
        fi
    done

    # Redis (check via docker exec)
    if docker exec redis-memory redis-cli ping >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Redis (port 6379)"
    else
        echo -e "  ${RED}✗${NC} Redis (port 6379)"
    fi

    # Memgraph
    if curl -sf "http://localhost:7687" >/dev/null 2>&1 || docker ps --format '{{.Names}}' | grep -q memgraph; then
        echo -e "  ${GREEN}✓${NC} Memgraph (port 7687)"
    else
        echo -e "  ${RED}✗${NC} Memgraph (port 7687)"
    fi
}

show_logs() {
    cd "${SCRIPT_DIR}"
    docker compose logs -f "${1:-cca}"
}

case "${1:-help}" in
    setup)   setup ;;
    pull)    pull_images ;;
    start)   start_stack ;;
    stop)    stop_stack ;;
    status)  check_health ;;
    logs)    shift; show_logs "$@" ;;
    *)       usage ;;
esac
