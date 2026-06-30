"""健身教练智能体的离线单元测试（不依赖 LLM）。

测试合并后的纯逻辑层：tools.py（计划生成/目标归一化/饮食建议/效果评估）
与 monitor.py（实时监测子循环）。原先针对 FitnessAgent 类与 argparse CLI
的测试已随旧实现合并，重写为对应当前架构。
"""

import os
import sys

# 让测试无论从哪个目录运行都能导入项目根目录下的模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import monitor
import tools


def test_plan_adjusts_for_goal_and_intensity():
    """高心率/高强度时，计划应动态加入呼吸恢复段。"""
    base = tools.generate_plan(goal="减脂", level="初级")
    assert "减脂" in base
    assert "呼吸恢复" not in base

    adjusted = tools.generate_plan(
        goal="减脂", level="初级", heart_rate="155", intensity="高"
    )
    assert "减脂" in adjusted
    assert "动态调整" in adjusted
    assert "呼吸恢复" in adjusted


def test_plan_adjusts_for_fatigue():
    """疲劳状态时，计划应下调训练量并加入恢复性热身。"""
    adjusted = tools.generate_plan(goal="增肌", level="中级", recovery="疲劳")
    assert "动态调整" in adjusted
    assert "疲劳" in adjusted


def test_generate_plan_normalizes_goal_input():
    """口语化/带空格的目标应被正确归一化（含子串匹配盲区"耐力提升"）。"""
    assert tools._match_goal(" 减脂 ") == "减脂"
    assert tools._match_goal("耐力提升") == "提升耐力"
    assert tools._match_goal("减脂计划") == "减脂"
    assert tools._match_goal("练腹肌") is None


def test_diet_recommendation_matches_goal():
    diet = tools.diet_advice(goal="增肌", weight="70")
    assert "蛋白质" in diet
    assert "增肌" in diet


def test_real_time_monitor_returns_summary():
    """实时监测子循环应返回含达标率的训练摘要，且不依赖 LLM。"""
    summary = monitor.run_workout(
        {"健身目标": "减脂", "年龄": "30", "体重": "75"},
        "慢跑30分钟",
        ticks=10,
        tick_delay=0,
    )
    assert "达标率" in summary
    assert "平均心率" in summary


def test_evaluate_session_reads_summary():
    summary = monitor.run_workout(
        {"健身目标": "减脂", "年龄": "30"}, "慢跑", ticks=8, tick_delay=0
    )
    result = tools.evaluate_session(summary=summary)
    assert "训练效果评估" in result
