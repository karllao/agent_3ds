"""
多 Agent 系统模块。

提供基于 LangGraph 的完整室内设计 Agent 流水线，包括：
- 需求理解（RequirementAgent）
- 追问澄清（ClarificationAgent）
- 设计规划（DesignAgent）
- 场景组装（SceneAssembler）
- 数据验证（ValidationAgent）
- 流水线编排（graph.py）

快速使用示例::

    from app.agents import run_agent_pipeline, continue_with_user_answer

    # 第一次运行
    result = await run_agent_pipeline(
        project_id="proj_001",
        cad_result_dict=cad_parse_result.to_dict(),
        user_description="现代简约风格，整体高级感，主卧要温馨，层高2.8米",
    )

    if result["status"] == "needs_user_input":
        # 向用户展示问题
        print(result["pending_question"])
        user_answer = input()

        # 继续执行
        result = await continue_with_user_answer(
            state_snapshot=result["state_snapshot"],
            user_answer=user_answer,
        )

    if result["status"] == "completed":
        scene_json = result["full_scene_data"]
"""

from .clarification_agent import ClarificationAgent
from .design_agent import DesignAgent
from .graph import (
    _build_pipeline_result,
    _create_llm,
    continue_with_user_answer,
    create_agent_graph,
    run_agent_pipeline,
)
from .requirement_agent import RequirementAgent
from .scene_assembler import SceneAssembler
from .state import AgentState, make_initial_state
from .validation_agent import ValidationAgent

__all__ = [
    # Agent 类
    "RequirementAgent",
    "ClarificationAgent",
    "DesignAgent",
    "SceneAssembler",
    "ValidationAgent",
    # 状态
    "AgentState",
    "make_initial_state",
    # 图和流水线
    "create_agent_graph",
    "run_agent_pipeline",
    "continue_with_user_answer",
    # 内部工具（供测试使用）
    "_create_llm",
    "_build_pipeline_result",
]
