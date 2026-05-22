@echo off
:: ============================================================
:: CAD-to-MAX Agent -- 开发环境启动脚本（Windows）
:: 用法: 双击运行，或在项目根目录执行 scripts\start_dev.bat
:: ============================================================
setlocal EnableDelayedExpansion

:: ── 定位项目根目录 ──────────────────────────────────────────
:: 脚本位于 scripts\ 子目录，向上一级即为项目根
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
pushd "%PROJECT_ROOT%"
set "PROJECT_ROOT=%CD%"
popd

echo.
echo ============================================================
echo   CAD-to-MAX Agent -- Development Environment Startup
echo ============================================================
echo.

:: ── 步骤 1：检查 .env 文件 ──────────────────────────────────
echo [Step 1/5] Checking environment configuration...

set "ENV_FILE=%PROJECT_ROOT%\backend\.env"
set "ENV_EXAMPLE=%PROJECT_ROOT%\backend\.env.example"

if not exist "%ENV_FILE%" (
    if exist "%ENV_EXAMPLE%" (
        echo [WARN]  .env not found. Copying from .env.example...
        copy "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
        echo [WARN]  Please edit backend\.env and fill in your API keys.
        echo [WARN]    Required: OPENAI_API_KEY ^(or ANTHROPIC_API_KEY^)
        echo [WARN]    Required: SECRET_KEY
        echo.
        echo Press any key after editing .env to continue, or Ctrl+C to abort...
        pause >nul
    ) else (
        echo [ERROR] .env.example not found at %ENV_EXAMPLE%
        goto :error_exit
    )
) else (
    echo [OK]    .env file found: %ENV_FILE%
)

:: ── 步骤 2：检查 Docker ─────────────────────────────────────
echo.
echo [Step 2/5] Checking Docker...

docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not installed or not in PATH.
    echo [ERROR] Please install Docker Desktop: https://www.docker.com/products/docker-desktop/
    goto :error_exit
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker daemon is not running. Please start Docker Desktop.
    goto :error_exit
)

for /f "tokens=*" %%v in ('docker --version') do echo [OK]    %%v

:: ── 步骤 3：启动 Docker 服务（仅 postgres + redis）─────────
echo.
echo [Step 3/5] Starting PostgreSQL and Redis via Docker Compose...

cd /d "%PROJECT_ROOT%"

:: 只启动基础设施服务，不启动 backend/celery（本地开发时手动启动）
docker compose up -d postgres redis
if errorlevel 1 (
    echo [ERROR] Failed to start Docker services.
    echo [ERROR] Check logs: docker compose logs
    goto :error_exit
)

echo [OK]    Docker services started.

:: ── 等待 PostgreSQL 就绪 ────────────────────────────────────
echo.
echo [INFO]  Waiting for PostgreSQL to be ready...
set /a RETRY=0
set /a MAX_RETRIES=30

:wait_postgres
docker compose exec -T postgres pg_isready -U postgres -d cad_agent >nul 2>&1
if not errorlevel 1 goto :postgres_ready

set /a RETRY+=1
if !RETRY! geq %MAX_RETRIES% (
    echo [ERROR] PostgreSQL did not become ready after %MAX_RETRIES% attempts.
    echo [ERROR] Check logs: docker compose logs postgres
    goto :error_exit
)
<nul set /p "=."
timeout /t 2 /nobreak >nul
goto :wait_postgres

:postgres_ready
echo.
echo [OK]    PostgreSQL is ready.

:: ── 等待 Redis 就绪 ─────────────────────────────────────────
echo [INFO]  Waiting for Redis to be ready...
set /a RETRY=0

:wait_redis
docker compose exec -T redis redis-cli ping 2>nul | findstr /i "PONG" >nul
if not errorlevel 1 goto :redis_ready

set /a RETRY+=1
if !RETRY! geq %MAX_RETRIES% (
    echo [ERROR] Redis did not become ready after %MAX_RETRIES% attempts.
    echo [ERROR] Check logs: docker compose logs redis
    goto :error_exit
)
<nul set /p "=."
timeout /t 2 /nobreak >nul
goto :wait_redis

:redis_ready
echo.
echo [OK]    Redis is ready.

:: ── 步骤 4：运行数据库迁移 ──────────────────────────────────
echo.
echo [Step 4/5] Running database migrations...

cd /d "%PROJECT_ROOT%\backend"

:: 优先使用 uv，其次使用系统 Python
where uv >nul 2>&1
if not errorlevel 1 (
    echo [INFO]  Using uv to run alembic...
    uv run alembic upgrade head
    if errorlevel 1 (
        echo [ERROR] alembic upgrade failed.
        goto :error_exit
    )
    goto :migration_done
)

where python >nul 2>&1
if not errorlevel 1 (
    echo [INFO]  Using python to run alembic...
    :: 尝试激活虚拟环境
    if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
        call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
    )
    python -m alembic upgrade head
    if errorlevel 1 (
        echo [ERROR] alembic upgrade failed.
        goto :error_exit
    )
    goto :migration_done
)

echo [WARN]  Neither uv nor python found in PATH. Skipping local migration.
echo [WARN]  Run migration manually:
echo [WARN]    docker compose exec backend alembic upgrade head

:migration_done
echo [OK]    Database migrations applied.

:: ── 步骤 5：提示用户后续操作 ────────────────────────────────
echo.
echo ============================================================
echo   Infrastructure is ready! Next steps:
echo ============================================================
echo.
echo   [Window 1] Start FastAPI backend:
echo     cd backend
echo     uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
echo.
echo   [Window 2] Start Celery worker:
echo     cd backend
echo     celery -A app.celery_app.celery_app worker ^
echo       --loglevel=info --queues=default,cad,ai,max_export
echo.
echo   [Window 3] Start frontend:
echo     cd frontend
echo     npm install ^&^& npm run dev
echo.
echo   Services:
echo     API:      http://localhost:8000
echo     API Docs: http://localhost:8000/docs  (DEBUG=true)
echo     Frontend: http://localhost:5173
echo     Flower:   docker compose up -d flower
echo.
echo   Stop infrastructure:
echo     docker compose down
echo.

:: 打开三个新的命令窗口（可选，注释掉如果不需要自动打开）
:: start "FastAPI Backend" cmd /k "cd /d %PROJECT_ROOT%\backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
:: start "Celery Worker"   cmd /k "cd /d %PROJECT_ROOT%\backend && celery -A app.celery_app.celery_app worker --loglevel=info --queues=default,cad,ai,max_export"
:: start "Frontend Dev"    cmd /k "cd /d %PROJECT_ROOT%\frontend && npm install && npm run dev"

echo Press any key to exit...
pause >nul
endlocal
exit /b 0

:error_exit
echo.
echo [ERROR] Startup failed. Please check the error messages above.
echo Press any key to exit...
pause >nul
endlocal
exit /b 1
