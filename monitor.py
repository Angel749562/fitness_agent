# 运动监测层
# 负责两件事：
#   1. 模拟可穿戴设备的生理数据流（心率、运动强度、配速、步频）
#   2. 运动过程中实时监测：把心率与目标区间比对，越界时输出文字语音指导/动作纠正
#
# 设计要点：实时监测子循环全程不调用 LLM（规则驱动），
# 这样每一拍都能即时给出反馈，保证"实时"无网络延迟。
# 子循环结束后返回一段训练摘要字符串，交回主循环让 LLM 评估。

import random
import sys
import time

# Windows 终端默认 GBK 编码，无法输出 emoji/部分中文；统一切到 UTF-8 避免崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# ==================== 目标心率区间 ====================
# 以"占最大心率的百分比"表示。最大心率 = 220 - 年龄。
# 不同健身目标对应不同的训练强度区间：
GOAL_ZONES = {
    "减脂":   (0.60, 0.70),   # 燃脂有氧区：中低强度、长时间
    "提升耐力": (0.70, 0.80),   # 有氧耐力区：中高强度持续
    "增肌":   (0.80, 0.90),   # 高强度间歇区：力量/爆发
}
# 默认区间（目标无法识别时）
DEFAULT_ZONE = (0.60, 0.75)

# 步频健康下限（步/分钟），低于此值提示加快摆臂/步频
MIN_CADENCE = 160


def max_hr(age) -> int:
    """计算最大心率 = 220 - 年龄。年龄缺失或非法时按 30 岁估算。"""
    try:
        a = int(age)
    except (TypeError, ValueError):
        a = 30
    return 220 - a


def resolve_zone(goal: str):
    """根据健身目标返回 (区间下限, 区间上限) 的最大心率百分比。"""
    if not goal:
        return DEFAULT_ZONE
    for key, zone in GOAL_ZONES.items():
        if key in goal:
            return zone
    return DEFAULT_ZONE


def target_hr_range(profile: dict):
    """
    根据用户档案算出目标心率的绝对区间（次/分钟）。
    返回: (low_bpm, high_bpm, mhr)
    """
    mhr = max_hr(profile.get("年龄"))
    low_pct, high_pct = resolve_zone(profile.get("健身目标", ""))
    return round(mhr * low_pct), round(mhr * high_pct), mhr


def simulate_tick(hr_center: int, tick: int, total: int) -> dict:
    """
    生成一拍生理快照，模拟可穿戴设备读数。
    用随机游走让数值在 hr_center 附近自然波动，并在训练中段刻意制造异常
    （心率飙高、配速过快、步频偏低），用于演示实时动作纠正。

    参数:
        hr_center: 本次训练心率的中心值（目标区间中点）
        tick: 当前是第几拍（从 0 开始）
        total: 总拍数
    返回: {"心率", "运动强度", "配速", "步频"} 字典
    """
    # 基础心率：围绕中心值小幅波动
    hr = hr_center + random.randint(-6, 6)

    # 训练中段（第 40%~60% 进度）刻意制造一次"心率飙高"异常
    in_spike = total > 0 and 0.40 <= tick / total <= 0.60
    if in_spike:
        hr += random.randint(20, 35)

    # 配速（分钟/公里）：心率越高通常配速越快（数值越小）
    pace_min = max(4.0, 8.5 - (hr - 110) * 0.03 + random.uniform(-0.2, 0.2))

    # 步频（步/分钟）：中段疲劳时偶尔偏低，制造动作纠正机会
    cadence = random.randint(168, 182)
    if in_spike or random.random() < 0.15:
        cadence = random.randint(148, 159)

    # 运动强度档位（供展示）
    if hr >= hr_center + 18:
        intensity = "高"
    elif hr <= hr_center - 14:
        intensity = "低"
    else:
        intensity = "中"

    return {
        "心率": hr,
        "运动强度": intensity,
        "配速": round(pace_min, 1),     # 分钟/公里
        "步频": cadence,                # 步/分钟
    }


def run_workout(profile: dict, plan_summary: str, ticks: int = 12, tick_delay: float = 0.4) -> str:
    """
    实时监测子循环：模拟一整段训练，逐拍打印生理数据并实时给出文字语音指导。

    参数:
        profile: 用户健身档案（含 健身目标、年龄 等）
        plan_summary: 本次训练的计划要点（来自智能体的 StartWorkout）
        ticks: 模拟多少拍（默认 12，约代表整段训练的采样点）
        tick_delay: 每拍之间的停顿秒数，让数据流"动"起来（离线测试可设 0）
    返回: 一段训练摘要字符串，作为 Observation 交回主循环供 LLM 评估
    """
    low, high, mhr = target_hr_range(profile)
    center = (low + high) // 2
    goal = profile.get("健身目标", "未设定")

    print("\n" + "=" * 60)
    print(f"🏃 开始训练监测 | 目标：{goal} | 计划：{plan_summary}")
    print(f"   最大心率 {mhr}，目标心率区间 {low}–{high} 次/分钟")
    print("=" * 60)

    in_zone = 0          # 心率落在目标区间内的拍数
    hr_sum = 0           # 心率累加，用于求平均
    corrections = 0      # 实时纠正次数
    hr_max_seen = 0      # 出现过的最高心率

    for t in range(ticks):
        snap = simulate_tick(center, t, ticks)
        hr = snap["心率"]
        hr_sum += hr
        hr_max_seen = max(hr_max_seen, hr)

        # 逐拍打印生理数据流
        print(
            f"[{t + 1:02d}/{ticks}] ❤️ {hr} 次/分 | 强度 {snap['运动强度']} "
            f"| 配速 {snap['配速']} 分/km | 步频 {snap['步频']} 步/分"
        )

        # ---- 实时监测与文字语音指导 ----
        if hr > high:
            corrections += 1
            print(f"   💬 心率 {hr} 超出 {goal} 目标区({low}-{high})，请放慢配速、调整呼吸节奏")
        elif hr < low:
            corrections += 1
            print(f"   💬 心率 {hr} 低于目标区({low}-{high})，强度不够，请适当加快")
        else:
            in_zone += 1

        # 动作纠正：步频偏低
        if snap["步频"] < MIN_CADENCE:
            corrections += 1
            print(f"   💬 步频 {snap['步频']} 偏低，注意加快摆臂、缩小步幅、保持上身稳定")

        if tick_delay:
            time.sleep(tick_delay)

    avg_hr = round(hr_sum / ticks) if ticks else 0
    in_zone_pct = round(in_zone / ticks * 100) if ticks else 0

    print("=" * 60)
    print(f"🏁 训练结束 | 平均心率 {avg_hr} | 达标率 {in_zone_pct}% | 实时纠正 {corrections} 次")
    print("=" * 60 + "\n")

    # 返回结构化摘要字符串，交回主循环让 LLM 评估
    return (
        f"训练监测完成。健身目标：{goal}；计划：{plan_summary}。"
        f"目标心率区间 {low}-{high} 次/分钟；"
        f"平均心率 {avg_hr}；峰值心率 {hr_max_seen}；"
        f"心率达标率 {in_zone_pct}%；全程实时纠正 {corrections} 次；采样 {ticks} 拍。"
    )


# 离线自测：python monitor.py
if __name__ == "__main__":
    demo_profile = {"健身目标": "减脂", "年龄": "30", "体重": "75"}
    print(run_workout(demo_profile, "慢跑 30 分钟", ticks=10, tick_delay=0))
