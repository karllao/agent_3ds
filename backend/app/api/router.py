"""
API 路由聚合模块 —— 将所有子模块路由挂载到统一前缀下。
"""

from app.api.endpoints import cad_upload, chat, jobs, projects
from fastapi import APIRouter

api_router = APIRouter()

api_router.include_router(
    projects.router,
    prefix="/projects",
    tags=["项目管理"],
)

api_router.include_router(
    cad_upload.router,
    prefix="/projects",
    tags=["CAD 上传"],
)

api_router.include_router(
    jobs.router,
    prefix="/jobs",
    tags=["生成任务"],
)

api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["智能对话"],
)
