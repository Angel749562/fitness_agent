# 运动监测层
# 负责两件事：
#   1. 模拟可穿戴设备的生理数据流（心率、运动强度、配速、步频）
#   2. 运动过程中实时监测：把心率与目标区间比对，越界时产生结构化事件
#
# 设计要点：实时监测子循环全程不调用 LLM（规则驱动），
# 这样每一拍都能即时给出反馈，保证"实时"无网络延迟。
# 子循环输出 heart_rate_sample、advice_event、session_summary，供 CLI/API/UI 消费。

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
GOAL_ZONE_LABELS = {
    "减脂": "燃脂区",
    "提升耐力": "有氧耐力区",
    "增肌": "高强度间歇区",
}
# 默认区间（目标无法识别时）
DEFAULT_ZONE = (0.60, 0.75)
DEFAULT_ZONE_LABEL = "综合有氧区"

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


def training_zone_label(goal: str) -> str:
    if not goal:
        return DEFAULT_ZONE_LABEL
    for key, label in GOAL_ZONE_LABELS.items():
        if key in goal:
            return label
    return DEFAULT_ZONE_LABEL


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


def iter_workout_events(profile: dict, plan_summary: str, ticks: int = 12,
                        tick_delay: float = 0.4, stop_checker=None):
    low, high, mhr = target_hr_range(profile)
    center = (low + high) // 2
    goal = profile.get("健身目标", "未设定")
    training_zone = training_zone_label(goal)

    in_zone = 0
    hr_sum = 0
    corrections = 0
    hr_max_seen = 0

    def build_summary(sample_count: int, stopped: bool = False) -> dict:
        avg_hr = round(hr_sum / sample_count) if sample_count else 0
        in_zone_pct = round(in_zone / sample_count * 100) if sample_count else 0
        if sample_count:
            prefix = "训练已结束。" if stopped else "训练监测完成。"
            summary = (
                f"{prefix}健身目标：{goal}；计划：{plan_summary}。"
                f"目标心率区间 {low}-{high} 次/分钟；"
                f"平均心率 {avg_hr}；峰值心率 {hr_max_seen}；"
                f"心率达标率 {in_zone_pct}%；全程实时纠正 {corrections} 次；采样 {sample_count} 拍。"
            )
        else:
            summary = "训练已停止，尚未产生采样数据。"

        return {
            "summary": summary,
            "goal": goal,
            "training_zone": training_zone,
            "plan_summary": plan_summary,
            "target_low": low,
            "target_high": high,
            "max_hr": mhr,
            "average_heart_rate": avg_hr,
            "peak_heart_rate": hr_max_seen,
            "in_zone_pct": in_zone_pct,
            "corrections": corrections,
            "samples": sample_count,
            "planned_samples": ticks,
            "stopped": stopped,
        }

    for t in range(ticks):
        if stop_checker and stop_checker():
            yield {"type": "session_summary", "data": build_summary(t, stopped=True)}
            yield {
                "type": "stopped",
                "data": {"reason": "训练已停止", "completed_ticks": t, "total_samples": ticks},
            }
            return

        snap = simulate_tick(center, t, ticks)
        hr = snap["心率"]
        in_target_zone = low <= hr <= high
        hr_sum += hr
        hr_max_seen = max(hr_max_seen, hr)

        yield {
            "type": "heart_rate_sample",
            "data": {
                "sample_index": t + 1,
                "total_samples": ticks,
                "heart_rate": hr,
                "intensity": snap["运动强度"],
                "pace": snap["配速"],
                "cadence": snap["步频"],
                "target_low": low,
                "target_high": high,
                "max_hr": mhr,
                "in_target_zone": in_target_zone,
                "goal": goal,
                "training_zone": training_zone,
                "plan_summary": plan_summary,
            },
        }

        if hr > high:
            corrections += 1
            yield {
                "type": "advice_event",
                "data": {
                    "sample_index": t + 1,
                    "message": f"心率 {hr} 超出 {goal} 目标区({low}-{high})，请放慢配速、调整呼吸节奏",
                    "reason": "heart_rate_high",
                    "heart_rate": hr,
                    "target_low": low,
                    "target_high": high,
                },
            }
        elif hr < low:
            corrections += 1
            yield {
                "type": "advice_event",
                "data": {
                    "sample_index": t + 1,
                    "message": f"心率 {hr} 低于目标区({low}-{high})，强度不够，请适当加快",
                    "reason": "heart_rate_low",
                    "heart_rate": hr,
                    "target_low": low,
                    "target_high": high,
                },
            }
        else:
            in_zone += 1

        if snap["步频"] < MIN_CADENCE:
            corrections += 1
            yield {
                "type": "advice_event",
                "data": {
                    "sample_index": t + 1,
                    "message": f"步频 {snap['步频']} 偏低，注意加快摆臂、缩小步幅、保持上身稳定",
                    "reason": "cadence_low",
                    "cadence": snap["步频"],
                    "min_cadence": MIN_CADENCE,
                },
            }

        if tick_delay:
            time.sleep(tick_delay)

    yield {"type": "session_summary", "data": build_summary(ticks)}


def run_workout(profile: dict, plan_summary: str, ticks: int = 12, tick_delay: float = 0.4,
                stop_checker=None, event_sink=None) -> str:
    """
    实时监测子循环：模拟训练并通过 event_sink 推送结构化事件。

    返回: 一段训练摘要字符串，作为 Observation 交回主循环供 LLM 评估
    """
    final_summary = "训练监测已停止。"

    for event in iter_workout_events(profile, plan_summary, ticks, tick_delay, stop_checker):
        if event_sink:
            event_sink(event["type"], event["data"])

        if event["type"] == "session_summary":
            final_summary = event["data"]["summary"]
        elif event["type"] == "stopped" and final_summary == "训练监测已停止。":
            final_summary = (
                f"训练监测已停止。已完成 {event['data']['completed_ticks']}/"
                f"{event['data']['total_samples']} 拍。"
            )

    return final_summary


# 离线自测：python monitor.py
if __name__ == "__main__":
    demo_profile = {"健身目标": "减脂", "年龄": "30", "体重": "75"}
    print(run_workout(demo_profile, "慢跑 30 分钟", ticks=10, tick_delay=0))
