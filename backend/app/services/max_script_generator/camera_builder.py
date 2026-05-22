"""
CameraScriptBuilder
-------------------
将相机数据转换为 MAXScript 代码片段。

输入示例
--------
cameras = [
    {
        "id": "cam_001",
        "name": "LivingRoom",
        "position": [3000, -2000, 1600],   # 相机位置，mm
        "target": [3000, 3000, 1200],       # 目标点，mm
        "fov": 60,                          # 视野角，度
        "lens_mm": None,                    # 等效焦距（与 fov 二选一）
        "clipping": False,                  # 是否开启剪切面
        "near_clip": 100,
        "far_clip": 50000
    },
    ...
]
"""

from __future__ import annotations

import math
from typing import Any


class CameraScriptBuilder:
    """生成 Target Camera 的 MAXScript 代码段。"""

    # 35mm 等效焦距与 FOV 换算基准（对角线 FOV）
    FILM_WIDTH_MM = 36.0  # 全画幅横向尺寸（mm）

    def build(self, cameras: list[dict[str, Any]]) -> str:
        """
        返回 MAXScript 字符串：
          - 每个相机生成 TargetCamera
          - 设置 FOV / 焦距
          - 可选剪切面
          - 所有相机放入 "Cameras" Group
          - 为第一个相机设置激活透视视口
        """
        lines: list[str] = []
        lines.append("-- ============================================================")
        lines.append("-- [Section] Camera Builder - Auto Generated")
        lines.append("-- ============================================================")
        lines.append("")

        cam_vars: list[str] = []

        for idx, cam in enumerate(cameras, start=1):
            cam_num = f"{idx:03d}"
            cam_id = cam.get("id", f"cam_{idx}")
            cam_name = cam.get("name", f"Camera_{cam_num}")
            safe_name = cam_name.replace(" ", "_").replace("/", "_")

            pos = cam.get("position", [0, -3000, 1600])
            tgt = cam.get("target", [0, 0, 1000])
            px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
            tx, ty, tz = float(tgt[0]), float(tgt[1]), float(tgt[2])

            # FOV 与焦距换算
            fov_deg = cam.get("fov", None)
            lens_mm = cam.get("lens_mm", None)
            if fov_deg is not None:
                fov_val = float(fov_deg)
            elif lens_mm is not None:
                # fov = 2 * atan(film_width / (2 * focal_length))
                fov_val = math.degrees(
                    2 * math.atan(self.FILM_WIDTH_MM / (2.0 * float(lens_mm)))
                )
            else:
                fov_val = 60.0

            # 剪切面
            clipping = cam.get("clipping", False)
            near_clip = float(cam.get("near_clip", 100))
            far_clip = float(cam.get("far_clip", 50000))

            var = f"cam_{cam_num}"
            lines.append(f"-- ---- Camera {cam_num}: {cam_name} ----")
            lines.append(f"local {var} = TargetCamera()")
            lines.append(f"{var}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]")
            lines.append(f"{var}.target.pos = [{tx:.2f}, {ty:.2f}, {tz:.2f}]")
            lines.append(f"{var}.fov = {fov_val:.4f}")

            if clipping:
                lines.append(f"{var}.clipManually = true")
                lines.append(f"{var}.nearClip = {near_clip:.2f}")
                lines.append(f"{var}.farClip = {far_clip:.2f}")

            lines.append(f'{var}.name = "Camera_{safe_name}"')
            lines.append(f'{var}.target.name = "Camera_{safe_name}.Target"')

            # 多视口支持：切换对应相机视口
            viewport_idx = min(idx, 4)  # 最多 4 个视口
            lines.append(f"-- Set viewport {viewport_idx} to this camera")
            lines.append(f"viewport.setCamera {var} vp:{viewport_idx}")

            lines.append("")
            cam_vars.append(var)

        # ---- 激活第一个相机的视口 ----
        if cam_vars:
            lines.append("-- ---- Activate first camera viewport ----")
            lines.append("viewport.setLayout #layout_4")
            lines.append("viewport.setActiveViewport 1")
            lines.append(f"viewport.setCamera {cam_vars[0]} vp:1")
            lines.append("")

        # ---- Group: Cameras ----
        lines.append("-- ---- Group all cameras ----")
        if cam_vars:
            # TargetCamera 包含 camera + target，都要进组
            # 通过 helpers 获取 target 节点
            all_cam_nodes: list[str] = []
            for v in cam_vars:
                all_cam_nodes.append(v)
                all_cam_nodes.append(f"{v}.target")

            arr = "#(" + ", ".join(cam_vars) + ")"
            lines.append(f"local cam_group_nodes = {arr}")
            lines.append('group cam_group_nodes name:"Cameras"')
        else:
            lines.append("-- No cameras to group")
        lines.append("")

        return "\n".join(lines)
