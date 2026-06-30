# 工具层
# 健身教练智能体可调用的工具集。
# 沿用 Hello_agent 的"函数 + available_tools 注册表"模式：
# 每个工具是一个普通函数，返回字符串作为 Observation 反馈给智能体。

import re

import monitor
from memory import remember, load_memory


# ==================== 训练计划模板（按目标）====================
# 内置三套目标模板，按运动水平（初级/中级/高级）微调时长与强度。
PLAN_TEMPLATES = {
    "减脂": {
        "主项": "中低强度有氧（慢跑/快走/椭圆机/划船机）",
        "区间": "心率维持在最大心率 60%-70% 的燃脂区",
        "时长": {"初级": "30 分钟", "中级": "45 分钟", "高级": "60 分钟"},
        "频次": "每周 4-5 次",
        "补充": "搭配 2 次全身循环力量训练，保住肌肉、提高基础代谢",
    },
    "增肌": {
        "主项": "抗阻力量训练（深蹲/卧推/硬拉/划船等复合动作）",
        "区间": "组间高强度，力量动作 6-12 RM，间歇 60-90 秒",
        "时长": {"初级": "40 分钟", "中级": "60 分钟", "高级": "75 分钟"},
        "频次": "每周 4 次，按 推/拉/腿 分化",
        "补充": "训练后补充蛋白质，少量低强度有氧维持心肺",
    },
    "提升耐力": {
        "主项": "持续有氧 + 间歇跑（LSD 长距离慢跑 + 间歇冲刺）",
        "区间": "心率维持在最大心率 70%-80% 的有氧耐力区",
        "时长": {"初级": "35 分钟", "中级": "50 分钟", "高级": "70 分钟"},
        "频次": "每周 4-5 次，1 次间歇 + 3 次匀速",
        "补充": "每周一次长距离，逐周递增总里程不超过 10%",
    },
}


# 口语化目标别名 → 标准目标键（弥补纯子串匹配的盲区，如"耐力提升"）
GOAL_ALIASES = {
    "减脂计划": "减脂",
    "增肌计划": "增肌",
    "耐力提升": "提升耐力",
    "提升耐力计划": "提升耐力",
}


def _match_goal(goal: str):
    """把用户口语化的目标映射到模板键。先查别名表，再做子串匹配。"""
    g = (goal or "").strip()
    if g in GOAL_ALIASES:
        return GOAL_ALIASES[g]
    for key in PLAN_TEMPLATES:
        if key in g:
            return key
    return None


def save_profile(key: str, value: str) -> str:
    """
    记住用户的一条健身档案（写入本地 JSON，跨运行持久化）。
    参数 key: 字段名，如 "健身目标"、"年龄"、"体重"、"运动水平"
    参数 value: 字段内容，如 "减脂"、"30"、"75"、"初级"
    返回: 确认信息，作为 Observation 反馈给智能体
    """
    return remember(key, value)


def generate_plan(goal: str, level: str = "初级",
                  heart_rate: str = "", intensity: str = "", recovery: str = "") -> str:
    """
    根据健身目标和运动水平生成结构化训练计划，并按当前生理状态动态调整。
    参数 goal: 健身目标，如 "减脂"、"增肌"、"提升耐力"
    参数 level: 运动水平，"初级"/"中级"/"高级"，缺省按初级
    参数 heart_rate: 当前心率（可选，用于动态调整），如 "152"
    参数 intensity: 当前运动强度（可选），"低"/"中"/"高"
    参数 recovery: 当前恢复状态（可选），"良好"/"疲劳"
    返回: 训练计划文本（含动态调整说明）
    """
    key = _match_goal(goal)
    if key is None:
        return (
            f"无法识别健身目标「{goal}」。目前支持：减脂、增肌、提升耐力。"
            "请先确认用户的目标。"
        )

    lvl = level if level in ("初级", "中级", "高级") else "初级"
    t = PLAN_TEMPLATES[key]
    duration = t["时长"].get(lvl, t["时长"]["初级"])

    # ---- 基于当前生理数据的动态调整 ----
    # 解析基础时长里的数字（如 "30 分钟" → 30），按状态增减并追加段落。
    base_min_match = re.search(r"\d+", duration)
    base_min = int(base_min_match.group()) if base_min_match else 30
    hr = None
    try:
        hr = int(heart_rate)
    except (TypeError, ValueError):
        pass

    extra_phases = []   # 追加的训练段落
    adj_notes = []      # 调整说明
    if intensity == "高" or (hr is not None and hr >= 150):
        base_min += 5
        extra_phases.append("主项后追加：降低强度 + 呼吸恢复 3 分钟")
        adj_notes.append(f"当前强度偏高（{('心率 ' + str(hr)) if hr is not None else '强度 高'}），已加入呼吸恢复段、延长缓冲。")
    elif recovery == "疲劳":
        base_min = max(15, base_min - 5)
        extra_phases.append("开头追加：轻度拉伸 5 分钟（疲劳恢复）")
        adj_notes.append("当前处于疲劳状态，已下调训练量、加入恢复性热身。")

    duration_text = f"{base_min} 分钟"

    plan = (
        f"【{key}训练计划 · {lvl}】\n"
        f"- 热身：5-10 分钟动态拉伸 + 关节活动\n"
        f"- 主项：{t['主项']}，{duration_text}\n"
        f"- 强度：{t['区间']}\n"
        f"- 频次：{t['频次']}\n"
        f"- 补充：{t['补充']}\n"
        f"- 放松：5 分钟静态拉伸，重点放松当日训练肌群"
    )
    for ph in extra_phases:
        plan += f"\n- 动态调整：{ph}"
    if adj_notes:
        plan += "\n（调整依据：" + " ".join(adj_notes) + "）"
    return plan


def get_biometrics() -> str:
    """
    读取一次可穿戴设备的当前生理快照（静息/运动前演示用）。
    返回: 描述当前心率、运动强度、配速、步频的字符串
    """
    profile = load_memory()
    low, high, mhr = monitor.target_hr_range(profile)
    center = (low + high) // 2
    snap = monitor.simulate_tick(center, tick=0, total=1)
    return (
        f"当前生理读数：心率 {snap['心率']} 次/分，运动强度 {snap['运动强度']}，"
        f"配速 {snap['配速']} 分/km，步频 {snap['步频']} 步/分。"
        f"（参考：最大心率 {mhr}，目标区间 {low}-{high}）"
    )


def evaluate_session(summary: str) -> str:
    """
    根据训练监测摘要评估训练效果，给出评级与改进建议。
    参数 summary: run_workout 返回的训练摘要字符串（含达标率/平均心率/纠正次数）
    返回: 训练效果评估文本
    """
    # 从摘要里抽取达标率与纠正次数
    pct_match = re.search(r"达标率\s*(\d+)\s*%", summary)
    corr_match = re.search(r"纠正\s*(\d+)\s*次", summary)
    pct = int(pct_match.group(1)) if pct_match else None
    corrections = int(corr_match.group(1)) if corr_match else None

    if pct is None:
        return "无法从摘要中读到达标率，请确认已先完成训练监测(StartWorkout)。"

    if pct >= 80:
        rating = "优秀"
        advice = "心率大部分时间稳定在目标区，训练质量很高，保持当前强度即可。"
    elif pct >= 60:
        rating = "良好"
        advice = "整体达标，但有波动。注意保持匀速、控制呼吸节奏，减少心率忽高忽低。"
    else:
        rating = "需改进"
        advice = "心率偏离目标区较多，建议下次降低起步强度、循序渐进，必要时调整计划难度。"

    extra = ""
    if corrections is not None and corrections >= 4:
        extra = f" 本次实时纠正达 {corrections} 次，动作/强度稳定性有待加强。"

    return f"训练效果评估：{rating}（心率达标率 {pct}%）。{advice}{extra}"


def diet_advice(goal: str, weight: str = "") -> str:
    """
    根据健身目标和体重给出饮食建议（热量方向、蛋白质摄入、三餐结构）。
    参数 goal: 健身目标，如 "减脂"、"增肌"、"提升耐力"
    参数 weight: 体重（公斤），可留空
    返回: 饮食建议文本
    """
    key = _match_goal(goal)

    # 蛋白质参考量（克/公斤体重）
    protein_per_kg = {"减脂": 1.6, "增肌": 1.8, "提升耐力": 1.4}.get(key, 1.5)
    protein_line = ""
    try:
        w = float(weight)
        protein_line = f"\n- 每日蛋白质：约 {round(w * protein_per_kg)} 克（{protein_per_kg} 克/公斤体重）"
    except (TypeError, ValueError):
        protein_line = f"\n- 每日蛋白质：约 {protein_per_kg} 克/公斤体重"

    plans = {
        "减脂": (
            "- 热量：制造小幅热量缺口（约低于 TDEE 300-500 千卡）\n"
            "- 主食：优先全谷物、粗粮，控制精制碳水\n"
            "- 三餐：高蛋白 + 大量蔬菜，少油少糖，晚餐适当减量"
        ),
        "增肌": (
            "- 热量：小幅热量盈余（约高于 TDEE 200-300 千卡）\n"
            "- 主食：保证充足碳水支撑训练（米饭、燕麦、红薯）\n"
            "- 三餐：每餐含优质蛋白，训练后 1 小时内补充蛋白+碳水"
        ),
        "提升耐力": (
            "- 热量：与消耗基本持平，避免亏空影响续航\n"
            "- 主食：以复合碳水为主，长训练前适当补碳\n"
            "- 三餐：均衡饮食，注意补充电解质与水分"
        ),
    }
    body = plans.get(key, "- 均衡膳食，蛋白质、碳水、脂肪合理搭配，多喝水。")
    title = f"{key}饮食建议" if key else "饮食建议"
    return f"【{title}】\n{body}{protein_line}"


# 工具注册表：把函数名和函数本身对应起来
available_tools = {
    "save_profile": save_profile,
    "generate_plan": generate_plan,
    "get_biometrics": get_biometrics,
    "evaluate_session": evaluate_session,
    "diet_advice": diet_advice,
}
