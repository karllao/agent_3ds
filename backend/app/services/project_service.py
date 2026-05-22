"""
Project CRUD 服务。

提供项目的创建、查询、更新路径/状态、删除等操作，
基于 SQLAlchemy async session，不自行提交事务。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectStatus


class ProjectService:
    """项目 CRUD 服务，所有方法均为异步。"""

    # ── 创建 ──────────────────────────────────────────────────────────────────

    async def create_project(
        self,
        session: AsyncSession,
        name: str,
        user_description: str = "",
        cad_file_path: str = "",
    ) -> Project:
        """
        创建新项目记录。

        Args:
            session:          数据库会话。
            name:             项目名称。
            user_description: 用户描述（可为空）。
            cad_file_path:    CAD 文件路径（上传后再填也可）。

        Returns:
            创建后的 Project 对象。
        """
        project = Project(
            name=name,
            user_description=user_description or None,
            cad_file_path=cad_file_path or None,
            status=ProjectStatus.CREATED
            if not cad_file_path
            else ProjectStatus.CAD_UPLOADED,
        )
        session.add(project)
        await session.flush()
        await session.refresh(project)
        logger.info(
            "[ProjectService] Project created: id={} name={!r}",
            project.id,
            project.name,
        )
        return project

    # ── 查询 ──────────────────────────────────────────────────────────────────

    async def get_project(
        self,
        session: AsyncSession,
        project_id: int,
    ) -> Optional[Project]:
        """
        根据 ID 查询项目，不存在时返回 None。

        Args:
            session:    数据库会话。
            project_id: 项目 ID。

        Returns:
            Project 对象或 None。
        """
        result = await session.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    async def list_projects(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Project]:
        """
        分页获取项目列表，按创建时间倒序。

        Args:
            session: 数据库会话。
            skip:    跳过条数（offset）。
            limit:   最大返回条数。

        Returns:
            Project 列表。
        """
        result = await session.execute(
            select(Project)
            .order_by(Project.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── 更新路径 ──────────────────────────────────────────────────────────────

    async def update_project_paths(
        self,
        session: AsyncSession,
        project_id: int,
        scene_json_path: Optional[str] = None,
        max_file_path: Optional[str] = None,
        preview_image_path: Optional[str] = None,
    ) -> None:
        """
        更新项目的输出文件路径（只更新非 None 的字段）。

        Args:
            session:            数据库会话。
            project_id:         项目 ID。
            scene_json_path:    场景 JSON 文件路径。
            max_file_path:      .max 文件路径。
            preview_image_path: 预览图路径。
        """
        project = await self.get_project(session, project_id)
        if project is None:
            logger.warning(
                "[ProjectService] update_project_paths: Project {} not found",
                project_id,
            )
            return

        updated_fields: list[str] = []
        if scene_json_path is not None:
            project.scene_json_path = scene_json_path
            updated_fields.append("scene_json_path")
        if max_file_path is not None:
            project.max_file_path = max_file_path
            updated_fields.append("max_file_path")
        if preview_image_path is not None:
            project.preview_image_path = preview_image_path
            updated_fields.append("preview_image_path")

        if updated_fields:
            logger.info(
                "[ProjectService] Project {} paths updated: {}",
                project_id,
                updated_fields,
            )
            await session.flush()

    # ── 更新状态 ──────────────────────────────────────────────────────────────

    async def update_project_status(
        self,
        session: AsyncSession,
        project_id: int,
        status: str,
    ) -> None:
        """
        更新项目状态。

        Args:
            session:    数据库会话。
            project_id: 项目 ID。
            status:     目标状态字符串（与 ProjectStatus 枚举值一致）。
        """
        project = await self.get_project(session, project_id)
        if project is None:
            logger.warning(
                "[ProjectService] update_project_status: Project {} not found",
                project_id,
            )
            return

        try:
            project.status = ProjectStatus(status)
        except ValueError:
            logger.error(
                "[ProjectService] Unknown status '{}' for project {}",
                status,
                project_id,
            )
            return

        logger.info("[ProjectService] Project {} status → {}", project_id, status)
        await session.flush()

    # ── 删除 ──────────────────────────────────────────────────────────────────

    async def delete_project(
        self,
        session: AsyncSession,
        project_id: int,
    ) -> bool:
        """
        删除项目（级联删除关联 Job 和 Conversation）。

        Args:
            session:    数据库会话。
            project_id: 项目 ID。

        Returns:
            True 表示删除成功，False 表示项目不存在。
        """
        project = await self.get_project(session, project_id)
        if project is None:
            logger.warning(
                "[ProjectService] delete_project: Project {} not found", project_id
            )
            return False

        await session.delete(project)
        await session.flush()
        logger.info("[ProjectService] Project {} deleted", project_id)
        return True

    # ── 更新 CAD 文件路径 ─────────────────────────────────────────────────────

    async def update_cad_file_path(
        self,
        session: AsyncSession,
        project_id: int,
        cad_file_path: str,
    ) -> None:
        """更新 CAD 文件路径并将状态置为 CAD_UPLOADED。"""
        project = await self.get_project(session, project_id)
        if project is None:
            logger.warning(
                "[ProjectService] update_cad_file_path: Project {} not found",
                project_id,
            )
            return

        project.cad_file_path = cad_file_path
        project.status = ProjectStatus.CAD_UPLOADED
        await session.flush()
        logger.info(
            "[ProjectService] Project {} cad_file_path updated: {}",
            project_id,
            cad_file_path,
        )


# 全局单例
project_service = ProjectService()
