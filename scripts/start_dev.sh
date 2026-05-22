#!/bin/bash
# ============================================================
# CAD-to-MAX Agent — 开发环境启动脚本（Linux / macOS）
# 用法: bash scripts/start_dev.sh
# ============================================================
set -euo pipefail

# ── 颜色输出 ────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── 项目根目录（脚本所在目录的上一级）──────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  CAD-to-MAX Agent — Development Environment Startup${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

# ── 步骤 1：检查 .env 文件 ──────────────────────────────────
info "Step 1/5: Checking environment configuration..."

ENV_FILE="${PROJECT_ROOT}/backend/.env"
ENV_EXAMPLE="${PROJECT_ROOT}/backend/.env.example"

if [ ! -f "${ENV_FILE}" ]; then
    if [ -f "${ENV_EXAMPLE}" ]; then
        warn ".env not found. Copying from .env.example..."
        cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        warn "Please edit ${ENV_FILE} and fill in your API keys before continuing."
        warn "  Required: OPENAI_API_KEY (or ANTHROPIC_API_KEY)"
        warn "  Required: SECRET_KEY"
        echo ""
        read -rp "Press Enter after editing .env to continue, or Ctrl+C to abort: "
    else
        error ".env.example not found at ${ENV_EXAMPLE}"
        exit 1
    fi
else
    success ".env file found: ${ENV_FILE}"
fi

# 检查关键变量是否已填写
OPENAI_KEY=$(grep -E '^OPENAI_API_KEY=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
ANTHROPIC_KEY=$(grep -E '^ANTHROPIC_API_KEY=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' | tr -d "'")

if [[ "${OPENAI_KEY}" == "sk-your-openai-api-key-here" || -z "${OPENAI_KEY}" ]] && \
   [[ "${ANTHROPIC_KEY}" == "sk-ant-your-anthropic-api-key-here" || -z "${ANTHROPIC_KEY}" ]]; then
    warn "Neither OPENAI_API_KEY nor ANTHROPIC_API_KEY is configured."
    warn "AI features will not work until at least one key is set."
fi

# ── 步骤 2：检查 Docker ─────────────────────────────────────
info "Step 2/5: Checking Docker..."

if ! command -v docker &>/dev/null; then
    error "Docker is not installed or not in PATH."
    error "Please install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    exit 1
fi

if ! docker info &>/dev/null; then
    error "Docker daemon is not running. Please start Docker Desktop."
    exit 1
fi

success "Docker is running: $(docker --version)"

# ── 步骤 3：启动 Docker 服务（仅 postgres + redis）─────────
info "Step 3/5: Starting PostgreSQL and Redis via Docker Compose..."

cd "${PROJECT_ROOT}"

# 只启动基础设施服务，不启动 backend/celery（本地开发时手动启动）
docker compose up -d postgres redis

success "Docker services started."

# ── 等待 PostgreSQL 就绪 ────────────────────────────────────
info "Waiting for PostgreSQL to be ready..."
MAX_RETRIES=30
RETRY=0
until docker compose exec -T postgres pg_isready -U postgres -d cad_agent &>/dev/null; do
    RETRY=$((RETRY + 1))
    if [ "${RETRY}" -ge "${MAX_RETRIES}" ]; then
        error "PostgreSQL did not become ready after ${MAX_RETRIES} attempts."
        error "Check logs: docker compose logs postgres"
        exit 1
    fi
    echo -n "."
    sleep 2
done
echo ""
success "PostgreSQL is ready."

# ── 等待 Redis 就绪 ─────────────────────────────────────────
info "Waiting for Redis to be ready..."
RETRY=0
until docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q "PONG"; do
    RETRY=$((RETRY + 1))
    if [ "${RETRY}" -ge "${MAX_RETRIES}" ]; then
        error "Redis did not become ready after ${MAX_RETRIES} attempts."
        error "Check logs: docker compose logs redis"
        exit 1
    fi
    echo -n "."
    sleep 2
done
echo ""
success "Redis is ready."

# ── 步骤 4：运行数据库迁移 ──────────────────────────────────
info "Step 4/5: Running database migrations..."

BACKEND_DIR="${PROJECT_ROOT}/backend"

# 优先使用 uv，其次使用系统 Python
if command -v uv &>/dev/null; then
    info "Using uv to run alembic..."
    cd "${BACKEND_DIR}"
    uv run alembic upgrade head
elif command -v python3 &>/dev/null; then
    info "Using python3 to run alembic..."
    cd "${BACKEND_DIR}"
    # 尝试在虚拟环境中运行
    if [ -f "${PROJECT_ROOT}/.venv/bin/activate" ]; then
        source "${PROJECT_ROOT}/.venv/bin/activate"
    fi
    python3 -m alembic upgrade head
else
    warn "Neither uv nor python3 found. Skipping local migration."
    warn "Run migration manually: docker compose exec backend alembic upgrade head"
fi

success "Database migrations applied."

# ── 步骤 5：提示用户后续操作 ────────────────────────────────
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Infrastructure is ready! Next steps:${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo -e "  ${CYAN}Terminal 1${NC} — Start FastAPI backend:"
echo -e "    cd backend"
echo -e "    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo ""
echo -e "  ${CYAN}Terminal 2${NC} — Start Celery worker:"
echo -e "    cd backend"
echo -e "    celery -A app.celery_app.celery_app worker \\"
echo -e "      --loglevel=info --queues=default,cad,ai,max_export"
echo ""
echo -e "  ${CYAN}Terminal 3${NC} — Start frontend:"
echo -e "    cd frontend"
echo -e "    npm install && npm run dev"
echo ""
echo -e "  ${CYAN}Services:${NC}"
echo -e "    API:      http://localhost:8000"
echo -e "    API Docs: http://localhost:8000/docs"
echo -e "    Frontend: http://localhost:5173"
echo -e "    Flower:   (start with: docker compose up -d flower)"
echo ""
echo -e "  ${CYAN}Stop infrastructure:${NC}"
echo -e "    docker compose down"
echo ""
