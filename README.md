
# 健身教练智能体 (fitness_agent)

一个基于大语言模型 + **ReAct（思考-行动-观察）** 范式的私人健身教练智能体。
它通过 FastAPI + WebSocket 驱动网页实时训练看板，模拟可穿戴设备数据流，完成“制定计划 → 开始训练 → 实时监测 → 即时建议 → 结束训练 → 汇总评估”的闭环，并持久化训练历史用于复盘和趋势分析。

实时训练闭环由规则驱动的监测层完成，不依赖 LLM；LLM 只参与训练前计划、训练后总结和自然语言解释。

## ✨ 核心能力

1. **网页实时训练看板** —— 启动 FastAPI 后打开 `/dashboard/`，可直接点击「开始训练」进入实时训练，点击「结束训练」查看本次训练汇总。
2. **生理数据监测** —— 模拟可穿戴设备，默认每秒推送心率、运动强度、配速、步频，并按「最大心率 = 220 − 年龄」与健身目标自动计算目标心率区间。
3. **运动中即时建议与动作纠正** —— 心率越出目标区间或步频偏低时立即产生结构化 `advice_event`，页面同步显示中文建议原因与建议内容；该实时环节规则驱动、不调用 LLM。
4. **训练结果汇总** —— 完成或结束训练后展示平均心率、峰值心率、心率达标率、纠正次数、采样数和训练摘要。
5. **按目标动态调整训练计划** —— 支持「减脂 / 增肌 / 提升耐力」×「初级 / 中级 / 高级」，并能根据训练摘要在训练后动态调整计划。
6. **训练效果评估 + 饮食建议** —— 按心率达标率给出效果评级与改进点，并按目标和体重给出热量方向、三餐结构与每日蛋白质参考量。
7. **跨会话记忆** —— 自动记住健身目标、年龄、体重、运动水平；SQLite 为主存储，`user_profile.json` 保留为 CLI 兼容镜像。
8. **训练历史与趋势复盘** —— SQLite 持久化训练会话、心率样本与建议事件，可查看历史详情、心率曲线和多次训练趋势。

## 🏗️ 项目结构

```
fitness_agent/
├── api/
│   ├── main.py        # FastAPI 应用、REST 路由与 WebSocket 入口
│   └── schemas.py     # API 请求/响应模型
├── services/
│   ├── database.py         # SQLAlchemy 模型、SQLite 持久化与趋势聚合
│   └── session_manager.py  # 实时会话注册表、持久化、后台任务与事件队列
├── web/
│   ├── index.html     # Web Dashboard 页面
│   ├── styles.css     # Dashboard 样式
│   └── app.js         # Dashboard REST/WebSocket 客户端逻辑
├── agent.py           # ReAct 主循环；支持 CLI 与服务层注入式调用
├── llm_client.py      # OpenAI 兼容的 LLM 客户端
├── memory.py          # 健身档案读写与 JSON 兼容迁移
├── prompts.py         # 健身教练系统提示词与工作流程引导
├── tools.py           # 工具集：计划生成 / 生理读数 / 效果评估 / 饮食建议 / 档案记忆
├── monitor.py         # 模拟可穿戴数据流 + 事件化实时监测/纠正子循环
├── tests/             # 单元测试与 API/WebSocket 测试
├── requirements.txt   # 依赖
├── README.md          # 本文件
└── 需求文档.md         # 完整需求文档
```

## 🔧 环境要求

- Python 3.10+
- 安装 `requirements.txt` 中的依赖
- 非演示模式需要一个 OpenAI 兼容的 LLM 服务及有效的 API Key；Web Dashboard 演示模式不需要密钥

## 🚀 安装与运行

```bash
# 1. 安装依赖
pip install -r requirements.txt
```

### 方式一：启动网页实时训练看板（推荐）

```bash
uvicorn api.main:app --reload
```

启动后打开：

```text
http://127.0.0.1:8000/dashboard/
```

Dashboard 默认勾选「演示模式」，不需要 `LLM_API_KEY` 就可以点击「开始训练」跑完整实时闭环。默认采样间隔为 1 秒，页面会实时刷新心率、配速、步频，并在点击「结束训练」或训练自然完成后保留汇总指标。

### 方式二：运行 CLI 智能体

```bash
# 配置环境变量（BASE_URL 与 MODEL 有默认值，可按需覆盖）
export LLM_API_KEY=你的密钥
# 可选：
# export LLM_BASE_URL=https://api.openai.com/v1
# export LLM_MODEL=gpt-4o

python agent.py
```

不想配置密钥也可以运行 CLI 演示模式：

```bash
python agent.py --demo
```

> Windows 提示：程序入口已统一将终端输出切到 UTF-8，可正常显示中文。

## 🌐 FastAPI 后端服务

除 CLI 外，项目也提供 FastAPI 服务接口，适合被前端、移动端或其他后端系统调用。

### 启动服务

```bash
uvicorn api.main:app --reload
```

服务默认运行在 `http://127.0.0.1:8000`。`/health` 与 `/profile` 不依赖 LLM；创建非 demo 会话时需要配置 `LLM_API_KEY`。如果只想离线演示完整流程，可以在创建会话时传 `"demo": true`。

### Web Dashboard

启动服务后打开：

```text
http://127.0.0.1:8000/dashboard/
```

Dashboard 默认启用演示模式，可在没有 `LLM_API_KEY` 的情况下直接点击「开始训练」。页面会通过 `POST /sessions` 创建会话，再连接 `/sessions/{id}/stream` WebSocket，实时展示：

- 当前心率、目标心率区间、训练区间；
- 配速、步频、训练时长；
- 最新实时建议与建议原因；
- 训练进度与事件日志；
- 训练完成后的总结、平均心率、峰值心率、心率达标率、纠正次数和采样数。

Dashboard 顶部提供三个视图：

- **实时训练**：开始/结束训练，查看实时心率、目标区间、配速、步频、建议和事件日志；
- **训练历史**：分页浏览训练记录，查看某次训练的心率曲线、目标区间和建议采样点；
- **趋势**：比较多次训练的平均心率和心率达标率，并查看累计训练次数和时长。

页面的训练时长从第一条 `heart_rate_sample` 事件开始计时，并在训练总结、停止或错误事件到达后冻结。

### 验收标准对照

| 验收项 | 当前实现 |
|--------|----------|
| 能在网页点击「开始训练」 | `web/index.html` 提供 `#startButton`，`web/app.js` 调用 `POST /sessions` 创建会话并连接 WebSocket |
| 页面每秒收到心率/步频/配速更新 | `CreateSessionRequest.workout_tick_delay` 与 Dashboard 默认间隔均为 `1` 秒；`heart_rate_sample` 包含 `heart_rate`、`cadence`、`pace` |
| 心率超出目标区间时出现即时建议 | `monitor.iter_workout_events()` 在心率高于/低于目标区间时立即发出 `advice_event`，Dashboard 显示中文原因和建议 |
| 点击「结束训练」后看到平均心率、峰值心率、达标率、纠正次数 | `POST /sessions/{id}/stop` 触发停止信号，监测层先产出 `session_summary`，再结束会话；页面保留汇总指标 |
| 实时闭环不依赖 LLM | `monitor.py` 的训练监测子循环只做规则判断，不调用 LLM；LLM 仅用于训练前计划、训练后评估/解释 |

### REST 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查，返回服务状态 |
| `GET` | `/` | 重定向到 Web Dashboard |
| `GET` | `/dashboard/` | 打开 Web Dashboard 页面 |
| `GET` | `/profile` | 读取本地健身档案 |
| `PUT` | `/profile` | 覆盖写入健身档案 |
| `POST` | `/sessions` | 创建并启动一次 Agent 会话 |
| `GET` | `/sessions` | 分页查询训练历史（`page`、`page_size`） |
| `GET` | `/sessions/{id}` | 查询会话状态、Dashboard 快照、最终答案与错误信息 |
| `GET` | `/sessions/{id}/details` | 查询会话、心率样本和建议事件 |
| `POST` | `/sessions/{id}/stop` | 幂等请求结束运行中的会话 |
| `GET` | `/trends` | 查询训练次数、累计时长及逐次训练趋势 |

训练会话状态包括 `running`、`completed`、`stopping`、`stopped`、`failed` 和 `interrupted`。服务重启时，之前仍处于 `running` 或 `stopping` 的会话会被标记为 `interrupted`，不会自动续跑。

### 数据持久化

默认使用项目根目录的 `fitness_agent.db`（SQLite）。应用启动时自动建表，并将已有 `user_profile.json` 导入数据库；之后数据库作为主存储，JSON 文件继续同步更新以兼容 CLI。

如需切换到其他 SQLAlchemy 支持的数据库，可设置：

```bash
# SQLite 示例
export FITNESS_DATABASE_URL=sqlite:///./fitness_agent.db

# PostgreSQL 示例（需额外安装对应驱动）
export FITNESS_DATABASE_URL=postgresql+psycopg://user:password@localhost/fitness_agent
```

创建 demo 会话示例：

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"prompt":"我想减脂，今年30岁，体重75公斤，新手","demo":true,"workout_ticks":12,"workout_tick_delay":1}'
```

`POST /sessions` 常用字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | string | 必填 | 用户训练目标或自然语言需求 |
| `demo` | boolean | `false` | 是否使用内置脚本化演示 LLM；看板默认启用 |
| `workout_ticks` | integer | `12` | 本次训练采样次数，范围 `0-300` |
| `workout_tick_delay` | number | `1.0` | 每次采样间隔秒数；测试时可传 `0` 加速 |

返回示例：

```json
{
  "id": "session-uuid",
  "status": "running",
  "prompt": "我想减脂，今年30岁，体重75公斤，新手",
  "created_at": "2026-07-02T...",
  "updated_at": "2026-07-02T...",
  "dashboard": {},
  "final_answer": null,
  "error": null
}
```

### WebSocket 事件流

连接：

```text
ws://127.0.0.1:8000/sessions/{id}/stream
```

连接后会先收到 `session_snapshot`，随后持续收到结构化业务事件，例如：

- `session_started`
- `llm_output`
- `action`
- `observation`
- `heart_rate_sample`
- `advice_event`
- `session_summary`
- `final`
- `error`
- `stop_requested`
- `stopped`

事件格式：

```json
{
  "type": "heart_rate_sample",
  "session_id": "session-uuid",
  "timestamp": "2026-07-02T...",
  "data": {
    "sample_index": 1,
    "total_samples": 3,
    "heart_rate": 128,
    "intensity": "中",
    "pace": 7.8,
    "cadence": 171,
    "target_low": 114,
    "target_high": 133,
    "max_hr": 190,
    "in_target_zone": true,
    "goal": "减脂",
    "training_zone": "燃脂区",
    "plan_summary": "慢跑30分钟"
  }
}
```

说明：当前 LLM 客户端仍是非 token 流式调用；WebSocket 推送的是 Agent 执行过程、工具调用和运动监测的业务事件流。`session_summary` 会在训练自然完成或用户点击「结束训练」后产生，包含平均心率、峰值心率、心率达标率、纠正次数和采样数。

`session_snapshot.data.dashboard` 会保存当前会话的轻量级展示状态，供 Dashboard 首次连接或刷新后恢复：

- `last_sample` / `last_sample_at`：最新心率、目标区间、训练区间、配速、步频等采样数据；
- `last_advice` / `last_advice_at`：最新实时建议；
- `summary` / `summary_at`：训练总结数据；
- `workout_started_at` / `workout_finished_at`：训练计时边界；
- `final_answer` 或 `terminal_event`：会话收尾或异常停止信息。

## 🎬 演示模式（无需 API Key）

不想配置密钥也能完整看一遍流程——加 `--demo` 启动参数即可：

```bash
python agent.py --demo
```

演示模式使用内置的脚本化"假 LLM"，自动以"我想减脂，30岁，75kg，新手"为例，
依次走完：记录档案 → 生成计划 → 实时监测（含超区/步频纠正）→ **按实测峰值心率
动态调整计划** → 效果评估 → 饮食建议 → 收尾，无需任何网络调用。

## 💬 示例对话

```
请告诉我你的健身需求 > 我想减脂，今年30岁，体重75公斤，新手
```

智能体会依次：
1. 调用 `save_profile` 记录档案（目标=减脂、年龄=30、体重=75、水平=初级）；
2. 调用 `generate_plan` 生成减脂训练计划；
3. 用 `StartWorkout[...]` 进入实时监测——终端逐拍打印心率/强度/配速/步频，
   心率超出燃脂区或步频偏低时即时给出文字纠正；
4. 用 `evaluate_session` 按达标率评估本次训练效果；
5. 用 `diet_advice` 给出减脂饮食建议，最后 `Finish` 收尾。

下次启动时，开场会展示已记住的健身档案。

## ⚙️ 工作原理

每一轮，LLM 在系统提示与"已知健身档案"的引导下输出一对 `Thought / Action`，
主循环解析 `Action` 并分派为三类：

| Action 形式 | 含义 |
|-------------|------|
| `func(arg="值")` | 调用工具（如 `generate_plan(goal="减脂", level="初级")`） |
| `StartWorkout[计划要点]` | 进入运动监测子循环，结束后把训练摘要作为 Observation 回流 |
| `Finish[最终答案]` | 结束本次任务 |

工具/监测返回的结果作为 `Observation` 追加进历史，驱动下一轮思考，直到 `Finish`
或达到最大轮数。运动监测子循环全程不调用 LLM，确保实时反馈无网络延迟。

### ReAct 主循环与监测子循环的衔接

```mermaid
flowchart TD
    A([用户请求]) --> B[注入已知健身档案 + 历史]
    B --> C[LLM 输出 Thought / Action]
    C --> D{解析 Action 类型}
    D -->|func arg=值| E[调用工具<br/>generate_plan / get_biometrics<br/>evaluate_session / diet_advice / save_profile]
    D -->|StartWorkout 计划要点| F[进入运动监测子循环]
    D -->|Finish 答案| G([输出最终答案 · 结束])

    subgraph SUB [运动监测子循环 · 规则驱动 · 不调用 LLM]
        F --> F1[逐拍模拟生理数据<br/>心率/强度/配速/步频]
        F1 --> F2{心率超区 / 步频偏低?}
        F2 -->|是| F3[即时文字语音指导 + 动作纠正]
        F2 -->|否| F4[计入达标]
        F3 --> F5{还有下一拍?}
        F4 --> F5
        F5 -->|是| F1
        F5 -->|否| F6[汇总训练摘要<br/>平均心率/达标率/纠正次数]
    end

    E --> H[结果作为 Observation 回流]
    F6 --> H
    H --> B
```

### 完整对话执行流程（示例）

```mermaid
sequenceDiagram
    participant U as 用户
    participant A as 智能体(ReAct)
    participant M as 监测层(monitor)
    participant S as 档案(user_profile.json)

    U->>A: 我想减脂，30岁，75kg，新手
    A->>S: save_profile(目标/年龄/体重/水平)
    A->>A: generate_plan(goal=减脂, level=初级)
    A-->>U: 呈现减脂训练计划
    U->>A: 开始训练
    A->>M: StartWorkout[燃脂区慢跑]
    loop 逐拍监测(不调用 LLM)
        M-->>U: 心率/强度/配速/步频
        M-->>U: 💬 超区/步频纠正(实时)
    end
    M-->>A: 训练摘要(达标率/平均心率/纠正次数)
    A->>A: evaluate_session(summary)
    A-->>U: 训练效果评估
    A->>A: diet_advice(goal=减脂, weight=75)
    A-->>U: 饮食建议
    A-->>U: Finish[本次指导小结]
```

## 🧪 测试

```bash
# 运行全部测试
python -m pytest tests

# 只运行原有健身逻辑测试
python -m pytest tests/test_fitness_agent.py

# 只运行 FastAPI / WebSocket 测试
python -m pytest tests/test_api.py

# 单独验证运动监测子循环（无需 LLM、无需 pytest）
python monitor.py
```

测试覆盖：计划生成与动态调整、目标别名归一化、饮食建议、实时监测摘要、训练区间字段、停止后的部分训练汇总、效果评估、健康检查、档案接口、Dashboard 页面入口、开始/结束训练按钮、demo 会话创建、WebSocket 快照与事件流、心率/步频/配速采样字段、即时建议事件、结束训练后汇总指标、停止接口、历史列表与详情、趋势聚合、服务重启后的中断恢复和缺少 API Key 的错误路径。

## 📌 约束与说明

- 可穿戴设备数据为 **Python 模拟生成**，未接入真实硬件 SDK。
- 默认数据库为项目目录下的 `fitness_agent.db`；可用 `FITNESS_DATABASE_URL` 指向其他 SQLAlchemy 数据库地址。
- 首次启动会把现有 `user_profile.json` 档案导入数据库；JSON 文件继续作为 CLI 兼容镜像。
- 实时指导以 **文字建议** 形式呈现，未做真实 TTS 语音合成。
- 当前支持的健身目标限定为 **减脂 / 增肌 / 提升耐力** 三类。
- 本工具仅供健身指导参考，**不构成医疗建议**；特殊健康状况请遵医嘱。

## 🗺️ 后续可扩展方向

- 接入真实可穿戴设备 SDK（华为 / 苹果 / Garmin）替换模拟层；
- 接入真实 TTS 实现语音播报；
- 扩充健身目标与动作库级别的姿态纠正；
- 引入周期化训练计划和跨周期目标管理；
- 接入真实可穿戴设备后，增加设备连接状态和数据质量监测。

> 更完整的功能/非功能需求、验收标准见 [需求文档.md](需求文档.md)。
