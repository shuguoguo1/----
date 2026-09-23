"""项目级配置与统一物理常数。"""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_PROBLEM_ROOT = Path(
    os.environ.get(
        "D_PROBLEM_ROOT",
        r"D:\比赛\第二十三届中国研究生数学建模竞赛 - 中文题目\中文题目\D题",
    )
)

DEFAULT_OUTPUT_DIR = Path("outputs")

# 题面统一规则
CRUISE_CLEARANCE_M = 50.0
SERVICE_WORK_HEIGHT_AGL_M = 30.0
DEFAULT_DEM_SAMPLE_INTERVAL_M = 15.0
DECLARED_DEM_NODATA = -32767.0

# 单位换算常数
STANDARD_GRAVITY_M_S2 = 9.80665
JOULES_PER_KWH = 3_600_000.0

# 题面只明确了 E_total = E_horizontal + E_climb，并未在公式对象中给出两个分项的显式表达式。
# 当前实现采用 README 中列出的可复核解释，必须在正式提交前由参赛队人工确认。
ENERGY_FORMULA_STATUS = "公式待人工核对：题面未显式给出水平能耗与爬升能耗分项公式"
