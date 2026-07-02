# 主程序
# 实现"思考 → 行动 → 观察"的 ReAct 循环（健身教练版）。

import os
import re
import sys

# Windows 终端默认 GBK 编码，无法输出 emoji/部分中文；统一切到 UTF-8 避免崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from tools import available_tools
from llm_client import OpenAICompatibleClient
from prompts import AGENT_SYSTEM_PROMPT
from memory import load_memory, format_memory_for_prompt
import monitor

DEMO_MODE = "--demo" in sys.argv
MAX_STEPS = 10


# ==================== 内置假 LLM（演示用）====================

class DemoLLM:
    """脚本化的假大语言模型，用于无 API Key 的离线演示。"""

    def __init__(self):
        self.step = -1

    def generate(self, prompt: str, system_prompt: str) -> str:
        print("  → [演示模式] 使用内置脚本化 LLM")
        self.step += 1

        if self.step == 6:
            m = re.search(r"(训练监测完成。.*?采样 \d+ 拍。)", prompt, re.DOTALL)
            summary = m.group(1) if m else "心率达标率 70%；纠正 5 次"
            return ("Thought: 拿到训练摘要，评估本次训练效果。\n"
                    f'Action: evaluate_session(summary="{summary}")')

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
            'Thought: 计划已按心率调整。最后给出减脂饮食建议。\nAction: diet_advice(goal="减脂", weight="75")',
            'Thought: 本次指导完成，收尾总结。\nAction: Finish[已为你记录档案、制定并按心率动态调整减脂计划、完成实时监测与效果评估，并给出饮食建议。]',
        ]
        idx = self.step if self.step < 6 else self.step - 2
        return steps[min(idx, len(steps) - 1)]


def create_llm(demo: bool = False):
    if demo:
        return DemoLLM()

    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL", "https://ztoken.zlux.top/v1")
    model_id = os.environ.get("LLM_MODEL", "gpt-5.5")

    if not api_key:
        raise RuntimeError("请设置环境变量 LLM_API_KEY，或使用 demo 模式。")

    return OpenAICompatibleClient(model=model_id, api_key=api_key, base_url=base_url)


def _emit(event_sink, event_type: str, data: dict):
    if event_sink:
        event_sink(event_type, data)


def _is_stopped(stop_checker) -> bool:
    return bool(stop_checker and stop_checker())


def run_react_loop(prompt_history, llm=None, event_sink=None, stop_checker=None,
                   workout_runner=None, max_steps: int = MAX_STEPS):
    """针对一次用户请求，执行 思考-行动-观察 循环。"""
    if llm is None:
        llm = create_llm(DEMO_MODE)

    for step in range(max_steps):
        if _is_stopped(stop_checker):
            _emit(event_sink, "stopped", {"step": step + 1, "reason": "会话已停止"})
            return {"status": "stopped", "history": prompt_history, "final_answer": None, "error": None}

        print(f"--- 第 {step + 1} 轮 ---")
        _emit(event_sink, "step_started", {"step": step + 1})

        profile = load_memory()
        memory_block = format_memory_for_prompt(profile)
        full_prompt = memory_block + "\n\n" + "\n".join(prompt_history)

        llm_output = llm.generate(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT)

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
                _emit(event_sink, "log", {"message": "已截断多余的 Thought-Action 对"})

        print(f"模型输出:\n{llm_output}\n")
        prompt_history.append(llm_output)
        _emit(event_sink, "llm_output", {"step": step + 1, "text": llm_output})

        if _is_stopped(stop_checker):
            _emit(event_sink, "stopped", {"step": step + 1, "reason": "会话已停止"})
            return {"status": "stopped", "history": prompt_history, "final_answer": None, "error": None}

        action_match = re.search(r"Action: (.*)", llm_output, re.DOTALL)
        if not action_match:
            observation = "错误: 未能解析到 Action 字段。请确保回复严格遵循 'Thought: ... Action: ...' 格式。"
            print(f"Observation: {observation}\n")
            prompt_history.append(f"Observation: {observation}")
            _emit(event_sink, "observation", {"step": step + 1, "text": observation})
            continue

        action_str = action_match.group(1).strip()
        print(f"  → 解析到 Action: {action_str}")
        _emit(event_sink, "action", {"step": step + 1, "action": action_str})

        if action_str.startswith("Finish"):
            final_match = re.match(r"Finish\[(.*)\]", action_str, re.DOTALL)
            if final_match:
                final_answer = final_match.group(1)
                print(f"\n{'=' * 60}")
                print(f"任务完成！最终答案: {final_answer}")
                print(f"{'=' * 60}")
                _emit(event_sink, "final", {"step": step + 1, "final_answer": final_answer})
                return {"status": "completed", "history": prompt_history, "final_answer": final_answer, "error": None}

            observation = "错误: Finish 格式不对，应该是 Finish[答案]"
            print(f"Observation: {observation}\n")
            prompt_history.append(f"Observation: {observation}")
            _emit(event_sink, "observation", {"step": step + 1, "text": observation})
            continue

        if action_str.startswith("StartWorkout"):
            wk_match = re.match(r"StartWorkout\[(.*)\]", action_str, re.DOTALL)
            if not wk_match:
                observation = "错误: StartWorkout 格式不对，应该是 StartWorkout[本次训练的计划要点]"
                print(f"Observation: {observation}\n")
                prompt_history.append(f"Observation: {observation}")
                _emit(event_sink, "observation", {"step": step + 1, "text": observation})
                continue

            plan_summary = wk_match.group(1).strip()
            if workout_runner:
                summary = workout_runner(load_memory(), plan_summary)
            else:
                summary = monitor.run_workout(
                    load_memory(),
                    plan_summary,
                    stop_checker=stop_checker,
                    event_sink=event_sink,
                )

            observation_str = f"Observation: {summary}"
            print(f"{observation_str}\n")
            prompt_history.append(observation_str)
            _emit(event_sink, "observation", {"step": step + 1, "text": summary})
            continue

        tool_name_match = re.search(r"(\w+)\(", action_str)
        args_match = re.search(r"\((.*)\)", action_str)

        if not tool_name_match or not args_match:
            observation = "错误: 无法解析工具调用格式"
            print(f"Observation: {observation}\n")
            prompt_history.append(f"Observation: {observation}")
            _emit(event_sink, "observation", {"step": step + 1, "text": observation})
            continue

        tool_name = tool_name_match.group(1)
        args_str = args_match.group(1)
        kwargs = dict(re.findall(r'(\w+)="([^"]*)"', args_str))

        print(f"  → 准备调用工具: {tool_name}，参数: {kwargs}")

        if tool_name in available_tools:
            observation = available_tools[tool_name](**kwargs)
        else:
            observation = f"错误: 未定义的工具 '{tool_name}'"

        observation_str = f"Observation: {observation}"
        print(f"{observation_str}\n")
        prompt_history.append(observation_str)
        _emit(event_sink, "observation", {"step": step + 1, "text": observation, "tool": tool_name})

    print(f"\n{'=' * 60}")
    print("达到最大循环次数，任务未能在规定步骤内完成。")
    print(f"{'=' * 60}")
    error = "达到最大循环次数，任务未能在规定步骤内完成。"
    _emit(event_sink, "error", {"message": error})
    return {"status": "failed", "history": prompt_history, "final_answer": None, "error": error}


# ==================== 交互式主程序 ====================

DEMO_USER_PROMPT = "我想减脂，今年30岁，体重75公斤，新手"


def run_demo():
    """演示模式：用内置假 LLM 自动跑一遍完整场景，无需 API Key、无需人工输入。"""
    print("=" * 60)
    print("【演示模式】私人健身教练智能体 · 内置脚本化 LLM（无需 API Key）")
    print(f"模拟用户需求：{DEMO_USER_PROMPT}")
    print("=" * 60 + "\n")

    prompt_history = [f"用户请求: {DEMO_USER_PROMPT}"]
    run_react_loop(prompt_history, llm=create_llm(demo=True))

    print("\n演示结束。要用真实大模型对话，请设置 LLM_API_KEY 后运行：python agent.py")


def main():
    if DEMO_MODE:
        run_demo()
        return

    try:
        llm = create_llm(demo=False)
    except RuntimeError as exc:
        print(f"错误: {exc}")
        print("在终端运行: export LLM_API_KEY=你的密钥")
        print("或用内置演示模式（无需密钥）: python agent.py --demo")
        return

    print("=" * 60)
    print("你好！我是你的私人健身教练智能体。")
    print("我会按你的健身目标制定训练计划，运动中实时监测并指导，")
    print("训练后评估效果并给出饮食建议。（输入 退出 结束对话）")
    print("=" * 60)

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

        prompt_history = [f"用户请求: {user_prompt}"]
        print()
        run_react_loop(prompt_history, llm=llm)


if __name__ == "__main__":
    main()
