# 主程序
# 实现"思考 → 行动 → 观察"的 ReAct 循环（健身教练版）。
# 在 Hello_agent 的 ReAct 骨架基础上：
#   1. 工具分派改为健身工具集（generate_plan / get_biometrics / evaluate_session / diet_advice / save_profile）
#   2. 新增 Action 类型 StartWorkout[...] —— 进入实时运动监测子循环（monitor.run_workout）
#   3. 每轮把"已知健身档案"注入 Prompt，实现跨轮记忆

import re
import os
import sys

# Windows 终端默认 GBK 编码，无法输出 emoji/部分中文；统一切到 UTF-8 避免崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# 从我们自己写的模块导入
from tools import available_tools
from llm_client import OpenAICompatibleClient
from prompts import AGENT_SYSTEM_PROMPT
from memory import load_memory, format_memory_for_prompt
import monitor

# 演示模式开关：加 --demo 启动参数时启用内置假 LLM，无需 API Key
DEMO_MODE = "--demo" in sys.argv


# ==================== 内置假 LLM（演示用）====================

class DemoLLM:
    """
    脚本化的"假"大语言模型，用于无 API Key 的离线演示。
    它不真正思考，只是按预设的减脂场景，逐轮返回一对 Thought/Action，
    完整走一遍"记档案 → 生成计划 → 实时监测 → 动态调整 → 评估 → 饮食建议"流程。
    其中评估与动态调整两步会从历史 Prompt 中读取真实的训练摘要/峰值心率，
    让演示结果反映本次随机监测的真实数据。
    """

    def __init__(self):
        self.step = -1

    def generate(self, prompt: str, system_prompt: str) -> str:
        print("  → [演示模式] 使用内置脚本化 LLM")
        self.step += 1

        # 第 7 步：评估——抓取上一轮 Observation 里的真实训练摘要
        if self.step == 6:
            m = re.search(r"(训练监测完成。.*?采样 \d+ 拍。)", prompt, re.DOTALL)
            summary = m.group(1) if m else "心率达标率 70%；纠正 5 次"
            return ("Thought: 拿到训练摘要，评估本次训练效果。\n"
                    f'Action: evaluate_session(summary="{summary}")')

        # 第 8 步：按训练中观察到的峰值心率，动态调整下一次计划
        if self.step == 7:
            peak = re.search(r"峰值心率\s*(\d+)", prompt)
            hr = peak.group(1) if peak else "150"
            return ("Thought: 训练中峰值心率偏高，按观察到的心率为下次训练动态调整计划。\n"
                    f'Action: generate_plan(goal="减脂", level="初级", heart_rate="{hr}")')

        steps = [
            'Thought: 用户透露了减脂目标和身体数据，先把目标记入档案。\nAction: save_profile(key="健身目标", value="减脂")',
            'Thought: 记下年龄，用于计算最大心率。\nAction: save_profile(key="年龄", value="30")',
            'Thought: 记下体重，用于后续饮食建议。\nAction: save_profile(key="体重", value="75")',
            'Thought: 记下运动水平。\nAction: save_profile(key="运动水平", value="初级")',
            'Thought: 档案齐了，生成减脂初级训练计划。\nAction: generate_plan(goal="减脂", level="初级")',
            'Thought: 计划已给出，开始训练并进入实时监测。\nAction: StartWorkout[燃脂区慢跑30分钟]',
            # 第 7、8 步在上面单独处理
            'Thought: 计划已按心率调整。最后给出减脂饮食建议。\nAction: diet_advice(goal="减脂", weight="75")',
            'Thought: 本次指导完成，收尾总结。\nAction: Finish[已为你记录档案、制定并按心率动态调整减脂计划、完成实时监测与效果评估，并给出饮食建议。]',
        ]
        # step 0-5 直接取前 6 条；step>=8 取后两条（索引偏移 2，因 6、7 步已单独处理）
        idx = self.step if self.step < 6 else self.step - 2
        return steps[min(idx, len(steps) - 1)]


# ==================== 配置与初始化 ====================

if DEMO_MODE:
    # 演示模式：使用内置假 LLM，跳过 API Key 检查
    llm = DemoLLM()
else:
    # 正常模式：从环境变量读取凭证（缺省值与 Hello_agent 保持一致）
    API_KEY = os.environ.get("LLM_API_KEY", "")
    BASE_URL = os.environ.get("LLM_BASE_URL", "https://ztoken.zlux.top/v1")
    MODEL_ID = os.environ.get("LLM_MODEL", "gpt-5.5")

    if not API_KEY:
        print("错误: 请设置环境变量 LLM_API_KEY")
        print("在终端运行: export LLM_API_KEY=你的密钥")
        print("或用内置演示模式（无需密钥）: python agent.py --demo")
        exit(1)

    llm = OpenAICompatibleClient(
        model=MODEL_ID,
        api_key=API_KEY,
        base_url=BASE_URL
    )

# 最多循环多少次，防止无限循环。
MAX_STEPS = 10


def run_react_loop(prompt_history):
    """
    针对一次用户请求，执行 思考-行动-观察 循环。
    参数 prompt_history: 本次任务的历史记录列表（首项为用户请求）。
    """
    for step in range(MAX_STEPS):
        print(f"--- 第 {step + 1} 轮 ---")

        # ---- 构建完整 Prompt ----
        # 记忆的关键：每轮都把"已知健身档案"重建并注入到 Prompt 最前面，
        # 让档案始终在智能体当前思考的视野里。
        profile = load_memory()
        memory_block = format_memory_for_prompt(profile)
        full_prompt = memory_block + "\n\n" + "\n".join(prompt_history)

        # ---- 调用 LLM 思考 ----
        llm_output = llm.generate(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

        # ---- 截断保护：只取第一对 Thought-Action ----
        match = re.search(
            r'(Thought:.*?Action:.*?)(?=\n\s*(?:Thought:|Action:|Observation:)|\Z)',
            llm_output,
            re.DOTALL
        )
        if match:
            truncated = match.group(1).strip()
            if truncated != llm_output.strip():
                llm_output = truncated
                print("  [已截断多余的 Thought-Action 对]")

        print(f"模型输出:\n{llm_output}\n")
        prompt_history.append(llm_output)

        # ---- 解析 Action ----
        action_match = re.search(r"Action: (.*)", llm_output, re.DOTALL)
        if not action_match:
            observation = "错误: 未能解析到 Action 字段。请确保回复严格遵循 'Thought: ... Action: ...' 格式。"
            print(f"Observation: {observation}\n")
            prompt_history.append(f"Observation: {observation}")
            continue

        action_str = action_match.group(1).strip()
        print(f"  → 解析到 Action: {action_str}")

        # ---- 判断 Action 类型 ----

        # 类型 A：结束任务
        if action_str.startswith("Finish"):
            final_match = re.match(r"Finish\[(.*)\]", action_str, re.DOTALL)
            if final_match:
                final_answer = final_match.group(1)
                print(f"\n{'=' * 60}")
                print(f"任务完成！最终答案: {final_answer}")
                print(f"{'=' * 60}")
                return
            else:
                observation = "错误: Finish 格式不对，应该是 Finish[答案]"
                print(f"Observation: {observation}\n")
                prompt_history.append(f"Observation: {observation}")

        # 类型 B：开始运动并进入实时监测子循环
        elif action_str.startswith("StartWorkout"):
            wk_match = re.match(r"StartWorkout\[(.*)\]", action_str, re.DOTALL)
            if not wk_match:
                observation = "错误: StartWorkout 格式不对，应该是 StartWorkout[本次训练的计划要点]"
                print(f"Observation: {observation}\n")
                prompt_history.append(f"Observation: {observation}")
                continue

            plan_summary = wk_match.group(1).strip()
            # 进入规则驱动的实时监测子循环（全程不调用 LLM，即时反馈）
            summary = monitor.run_workout(load_memory(), plan_summary)
            # 把训练摘要作为 Observation 交回循环，让 LLM 评估
            observation_str = f"Observation: {summary}"
            print(f"{observation_str}\n")
            prompt_history.append(observation_str)

        # 类型 C：调用工具
        else:
            tool_name_match = re.search(r"(\w+)\(", action_str)
            args_match = re.search(r"\((.*)\)", action_str)

            if not tool_name_match or not args_match:
                observation = "错误: 无法解析工具调用格式"
                print(f"Observation: {observation}\n")
                prompt_history.append(f"Observation: {observation}")
                continue

            tool_name = tool_name_match.group(1)
            args_str = args_match.group(1)

            # 解析参数为字典：{"goal": "减脂"}
            kwargs = dict(re.findall(r'(\w+)="([^"]*)"', args_str))

            print(f"  → 准备调用工具: {tool_name}，参数: {kwargs}")

            if tool_name in available_tools:
                observation = available_tools[tool_name](**kwargs)
            else:
                observation = f"错误: 未定义的工具 '{tool_name}'"

            observation_str = f"Observation: {observation}"
            print(f"{observation_str}\n")
            prompt_history.append(observation_str)

    # 循环正常结束（不是 return），说明达到了最大次数
    print(f"\n{'=' * 60}")
    print("达到最大循环次数，任务未能在规定步骤内完成。")
    print(f"{'=' * 60}")


# ==================== 交互式主程序 ====================

# 演示模式自动跑的预设需求
DEMO_USER_PROMPT = "我想减脂，今年30岁，体重75公斤，新手"


def run_demo():
    """演示模式：用内置假 LLM 自动跑一遍完整场景，无需 API Key、无需人工输入。"""
    print("=" * 60)
    print("【演示模式】私人健身教练智能体 · 内置脚本化 LLM（无需 API Key）")
    print(f"模拟用户需求：{DEMO_USER_PROMPT}")
    print("=" * 60 + "\n")

    prompt_history = [f"用户请求: {DEMO_USER_PROMPT}"]
    run_react_loop(prompt_history)

    print("\n演示结束。要用真实大模型对话，请设置 LLM_API_KEY 后运行：python agent.py")


def main():
    # 演示模式：跳过交互，自动走预设流程
    if DEMO_MODE:
        run_demo()
        return

    print("=" * 60)
    print("你好！我是你的私人健身教练智能体。")
    print("我会按你的健身目标制定训练计划，运动中实时监测并指导，")
    print("训练后评估效果并给出饮食建议。（输入 退出 结束对话）")
    print("=" * 60)

    # 开场展示已记住的健身档案，让"记忆"看得见
    profile = load_memory()
    if profile:
        print("\n我还记得你的健身档案：")
        for k, v in profile.items():
            print(f"  - {k}: {v}")

    while True:
        user_prompt = input("\n请告诉我你的健身需求 > ").strip()
        if not user_prompt:
            continue
        if user_prompt in ("退出", "quit", "exit"):
            print("再见，坚持训练，期待你的进步！")
            break

        # 每次新请求，开一份新的历史记录（档案通过记忆层跨请求保留）
        prompt_history = [f"用户请求: {user_prompt}"]
        print()
        run_react_loop(prompt_history)


if __name__ == "__main__":
    main()
