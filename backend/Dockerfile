# ── 构建阶段 ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# 设置构建时环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# 安装系统依赖（编译 psycopg2、shapely 等需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgeos-dev \
    libgdal-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 先复制 requirements.txt，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# ── 运行阶段 ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# 安装运行时系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgeos-c1v5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的 Python 包
COPY --from=builder /install /usr/local

# 复制应用代码
COPY . .

# 创建非 root 用户（安全最佳实践）
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --shell /bin/bash --create-home appuser \
    && chown -R appuser:appgroup /app

# 创建存储目录并授权
RUN mkdir -p /data/storage && chown -R appuser:appgroup /data

USER appuser

# 暴露 FastAPI 端口
EXPOSE 8000

# 默认启动命令（docker-compose 中会覆盖）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
