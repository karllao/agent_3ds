# CAD-to-MAX Agent

> 将建筑 CAD 图纸（DXF/DWG）自动转换为 3ds Max 场景文件的 AI 智能体系统。

---

## 项目介绍

CAD-to-MAX Agent 是一套端到端的自动化流水线：用户上传建筑平面图（DXF/DWG），系统通过 AI 解析墙体、门窗、房间布局，自动生成 3ds Max 场景脚本（MAXScript），并在远程 Windows 机器上执行，最终输出可渲染的 `.max` 文件和预览图。

整个过程支持多轮对话交互——用户可以在任意阶段通过自然语言调整材质、灯光、家具摆放等细节，AI 智能体会将意图转换为精确的 MAXScript 修改并重新执行。

---

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器 (React)                        │
│   上传 CAD  │  对话调整  │  查看进度  │  下载 .max / 预览图      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   FastAPI Backend (Docker)                       │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │  REST API    │  │  WebSocket   │  │   AI Agent (LangChain)│ │
│  │  /projects   │  │  /ws/{id}    │  │   Tool Calling Loop   │ │
│  │  /jobs       │  │              │  │   OpenAI / Anthropic  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬────────────┘ │
│         │                 │                      │              │
│         └─────────────────┴──────────────────────┘             │
│                           │                                     │
│              ┌────────────▼────────────┐                        │
│              │    Celery Task Queue    │                        │
│              │  cad / ai / max_export  │                        │
│              └────────────┬────────────┘                        │
└───────────────────────────┼─────────────────────────────────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
   ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐
   │  PostgreSQL │  │    Redis     │  │  max_worker (Windows)   │
   │  (项目/任务 │  │  (Broker /   │  │                         │
   │   对话历史) │  │  Result)     │  │  FastAPI + 3dsmaxbatch  │
   └─────────────┘  └──────────────┘  │  执行 MAXScript         │
                                      │  输出 .max + 预览图      │
                                      └─────────────────────────┘
```

---

## 功能特性

- **CAD 解析**：支持 DXF/DWG 格式，自动识别墙体、门洞、窗洞、房间轮廓
- **AI 场景生成**：基于解析结果和用户描述，通过 LLM Tool Calling 生成结构化场景数据
- **MAXScript 生成**：自动生成包含墙体、地板、门窗、材质、灯光、相机、家具的完整脚本
- **远程执行**：通过 HTTP API 将脚本推送到 Windows 机器上的 `3dsmaxbatch.exe` 执行
- **多轮对话**：支持自然语言调整场景细节，AI 智能体自动将意图转换为脚本修改
- **实时进度**：WebSocket 推送任务进度，前端实时显示处理状态
- **预览图生成**：场景导出后自动渲染低分辨率预览图
- **任务队列**：Celery 异步任务队列，支持多项目并发处理
- **Flower 监控**：内置 Celery 任务监控面板

---

## 技术栈

| 层次 | 技术 |
|------|------|
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) |
| AI | LangChain + OpenAI GPT-4o / Anthropic Claude |
| 任务队列 | Celery 5 + Redis |
| 数据库 | PostgreSQL 16 |
| CAD 解析 | ezdxf |
| 3ds Max | 3dsmaxbatch.exe + MAXScript |
| 容器化 | Docker + Docker Compose |
| 数据库迁移 | Alembic |

---

## 快速开始

### 前置要求

- Docker Desktop（Linux 容器模式）
- Node.js 18+（前端开发）
- Python 3.12+（本地开发）
- 一台安装了 3ds Max 2022/2023/2024 的 Windows 机器（用于运行 max_worker）
- OpenAI 或 Anthropic API Key

---

### 步骤 1：克隆仓库

```bash
git clone https://github.com/your-org/agent_3ds.git
cd agent_3ds
```

---

### 步骤 2：配置环境变量

**后端：**

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，至少填写以下必填项：

```
OPENAI_API_KEY=sk-your-real-key-here
SECRET_KEY=your-random-secret-at-least-32-chars
MAX_WORKER_URL=http://<windows-machine-ip>:8765
```

**max_worker（在 Windows 机器上）：**

```bat
copy max_worker\.env.example max_worker\.env
```

编辑 `max_worker\.env`，确认 `MAX_EXE_PATH` 指向正确的 `3dsmaxbatch.exe`。

---

### 步骤 3：启动 Docker 服务

```bash
# 启动所有后端服务（PostgreSQL、Redis、FastAPI、Celery Worker、Flower）
docker compose up -d

# 查看服务状态
docker compose ps

# 查看后端日志
docker compose logs -f backend
```

服务启动后可访问：
- 后端 API：http://localhost:8000
- API 文档：http://localhost:8000/docs（DEBUG=true 时）
- Flower 监控：http://localhost:5555/flower（admin / admin123）

---

### 步骤 4：运行数据库迁移

```bash
# 方式一：在 Docker 容器内执行
docker compose exec backend alembic upgrade head

# 方式二：本地执行（需先安装依赖）
cd backend
pip install -r requirements.txt
alembic upgrade head
```

验证迁移结果：

```bash
docker compose exec postgres psql -U postgres -d cad_agent -c "\dt"
```

---

### 步骤 5：启动前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器启动在 http://localhost:5173

---

### 步骤 6：配置并启动 max_worker（Windows）

在安装了 3ds Max 的 Windows 机器上：

```bat
cd max_worker

:: 安装依赖
pip install -r requirements.txt

:: 配置环境变量
copy .env.example .env
:: 编辑 .env，填写 MAX_EXE_PATH 和 WORK_DIR

:: 启动服务
python worker_service.py
```

服务默认监听 `0.0.0.0:8765`。确保防火墙允许后端服务器访问该端口。

验证 max_worker 是否正常：

```bash
curl http://<windows-ip>:8765/health
```

---

## 目录结构

```
agent_3ds/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── agents/             # LangChain AI 智能体
│   │   ├── api/                # REST API 路由
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   ├── schemas/            # Pydantic 请求/响应模型
│   │   ├── services/
│   │   │   ├── cad_parser/     # DXF/DWG 解析器
│   │   │   └── max_script_generator/  # MAXScript 生成器
│   │   │       ├── wall_builder.py        # 墙体脚本
│   │   │       ├── floor_builder.py       # 地板脚本
│   │   │       ├── door_window_builder.py # 门窗脚本
│   │   │       ├── material_builder.py    # 材质脚本
│   │   │       ├── light_builder.py       # 灯光脚本
│   │   │       ├── camera_builder.py      # 相机脚本
│   │   │       ├── furniture_builder.py   # 家具脚本
│   │   │       └── scene_script_generator.py  # 总装配器
│   │   ├── tasks/              # Celery 异步任务
│   │   ├── utils/              # 工具函数
│   │   ├── config.py           # 全局配置（pydantic-settings）
│   │   ├── database.py         # 数据库连接
│   │   ├── celery_app.py       # Celery 应用实例
│   │   └── main.py             # FastAPI 应用入口
│   ├── alembic/                # 数据库迁移
│   │   └── versions/
│   │       └── 001_initial_schema.py
│   ├── .env.example            # 环境变量模板
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── components/         # UI 组件
│   │   ├── pages/              # 页面
│   │   ├── hooks/              # 自定义 Hook
│   │   ├── api/                # API 客户端
│   │   └── types/              # TypeScript 类型定义
│   └── package.json
│
├── max_worker/                 # 3ds Max 执行服务（Windows）
│   ├── worker_service.py       # FastAPI 服务主程序
│   ├── config.py               # 配置
│   ├── scripts/                # MAXScript 工具脚本
│   ├── .env.example            # 环境变量模板
│   └── requirements.txt
│
├── scripts/                    # 开发/运维脚本
│   ├── start_dev.sh            # Linux/Mac 开发启动脚本
│   └── start_dev.bat           # Windows 开发启动脚本
│
├── docker-compose.yml          # Docker 服务编排
├── pyproject.toml
└── README.md
```

---

## API 文档

启动后端后（`DEBUG=true`），访问以下地址查看交互式 API 文档：

- **Swagger UI**：http://localhost:8000/docs
- **ReDoc**：http://localhost:8000/redoc

### 主要端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/projects` | 创建新项目 |
| `GET` | `/api/v1/projects` | 获取项目列表 |
| `GET` | `/api/v1/projects/{id}` | 获取项目详情 |
| `POST` | `/api/v1/projects/{id}/upload-cad` | 上传 CAD 文件 |
| `POST` | `/api/v1/projects/{id}/generate` | 触发场景生成 |
| `GET` | `/api/v1/jobs/{id}` | 查询任务状态 |
| `GET` | `/api/v1/projects/{id}/conversation` | 获取对话历史 |
| `POST` | `/api/v1/projects/{id}/chat` | 发送对话消息 |
| `WS` | `/ws/{project_id}` | 实时进度推送 |
| `GET` | `/health` | 健康检查 |

---

## 开发指南

### 本地开发（不使用 Docker）

```bash
# 1. 安装 Python 依赖（推荐使用 uv）
cd backend
uv sync   # 或 pip install -r requirements.txt

# 2. 启动 PostgreSQL 和 Redis（仅这两个服务用 Docker）
docker compose up -d postgres redis

# 3. 运行数据库迁移
alembic upgrade head

# 4. 启动 FastAPI（热重载）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 5. 启动 Celery Worker（新终端）
celery -A app.celery_app.celery_app worker --loglevel=info --queues=default,cad,ai,max_export
```

### 添加新的 MAXScript Builder

1. 在 `backend/app/services/max_script_generator/` 下创建新文件，例如 `stair_builder.py`
2. 实现 `build(self, data: list) -> str` 方法，返回 MAXScript 字符串
3. 在 `__init__.py` 中导出新类
4. 在 `SceneScriptGenerator.generate()` 中调用新 builder

### 数据库迁移

```bash
# 创建新迁移文件
alembic revision --autogenerate -m "add new column"

# 应用迁移
alembic upgrade head

# 回滚一步
alembic downgrade -1
```

### 运行测试

```bash
cd backend
pytest tests/ -v --asyncio-mode=auto
```

---

## 注意事项

### 3ds Max 授权

- `3dsmaxbatch.exe` 需要有效的 Autodesk 授权（单机版或网络版）
- 批处理模式下 3ds Max 会消耗一个授权席位
- 建议使用 Autodesk 网络许可证服务器，以支持多并发任务

### Windows 环境要求

- 操作系统：Windows 10/11 或 Windows Server 2019/2022
- 3ds Max：2022、2023 或 2024（推荐 2024）
- Python：3.10+（用于运行 max_worker）
- 内存：建议 16GB+（每个 3ds Max 实例约占 2-4GB）
- `MAX_CONCURRENT_TASKS` 建议不超过 2，避免内存不足

### 安全注意事项

- 生产环境必须设置强随机 `SECRET_KEY`（至少 32 字符）
- `max_worker` 的 `SECRET_TOKEN` 在生产环境必须设置
- 不要将 `.env` 文件提交到版本库（已在 `.gitignore` 中排除）
- 建议通过 VPN 或内网访问 max_worker，不要直接暴露到公网

### CAD 文件要求

- 支持格式：DXF（推荐）、DWG
- 建议使用 AutoCAD 2010 或更高版本的 DXF 格式
- 平面图应包含完整的墙体轮廓，门窗位置标注清晰
- 单位建议使用毫米（mm）

---

## License

MIT License. See [LICENSE](LICENSE) for details.
