# 记忆层
# 负责把用户的健身档案读写到本地 JSON 文件，并格式化成可注入 Prompt 的文本块。
# 这样即使程序重启，智能体依然记得用户的健身目标、年龄、体重等信息。

import json
import os

from services.database import database

# 记忆文件路径：和本文件放在同一目录下
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "user_profile.json")


def load_memory() -> dict:
    """
    从 JSON 文件读取用户的健身档案。
    返回: 档案字典，比如 {"健身目标": "减脂", "年龄": "30", "体重": "75"}
          文件不存在或损坏时返回空字典。
    """
    try:
        database.ensure_schema()
        stored = database.load_profile()
        if stored:
            return stored
    except Exception:
        # CLI 仍可在数据库暂时不可用时读取旧 JSON 档案。
        pass
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            # 文件损坏或读不出来时，当作空记忆处理，避免程序崩溃
            return {}
    return {}


def save_memory(mem: dict) -> None:
    """保存数据库档案，并同步旧 JSON 文件以兼容现有 CLI。"""
    database.ensure_schema()
    database.save_profile(mem)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        # ensure_ascii=False 让中文正常显示；indent=2 让文件易读
        json.dump(mem, f, ensure_ascii=False, indent=2)


def migrate_json_profile() -> None:
    """数据库为空时一次性导入已有 JSON 档案。"""
    database.ensure_schema()
    if database.load_profile() or not os.path.exists(MEMORY_FILE):
        return
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            profile = json.load(f)
        if isinstance(profile, dict) and profile:
            database.save_profile(profile)
    except (json.JSONDecodeError, OSError):
        return


def remember(key: str, value: str) -> str:
    """
    save_profile 工具的底层实现：更新一条档案并立刻落盘。
    参数 key: 档案字段名，如 "健身目标"、"年龄"
    参数 value: 档案内容，如 "减脂"、"30"
    返回: 一句确认话，作为 Observation 反馈给智能体
    """
    mem = load_memory()
    mem[key] = value
    save_memory(mem)
    return f"已记入健身档案：{key} = {value}"


def format_memory_for_prompt(mem: dict) -> str:
    """
    把档案字典格式化成一段文本，用于注入到每轮 Prompt 的最前面。
    这是"记忆"功能的关键：让已知档案始终出现在智能体当前思考的视野里。
    """
    if not mem:
        return "# 已知的用户健身档案:\n（暂无，这是一位新用户，请在对话中主动了解并记住其健身目标、年龄、体重、运动水平）"
    lines = [f"- {k}: {v}" for k, v in mem.items()]
    return "# 已知的用户健身档案:\n" + "\n".join(lines)
