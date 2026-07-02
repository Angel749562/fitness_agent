# 健身 Agent 上线与手表实时心率接入路线

## 计划文件位置

我刚才在计划模式里写的计划文件位置是：

```text
C:\Users\邓可鹏\.claude\plans\agent-agent-splendid-prism.md
```

这个文件属于 Claude Code 的计划文件，不在项目根目录里。下面这份文档是整理后放到项目里的版本，方便你以后直接在仓库里查看和迭代。

## 当前项目基础

当前项目已经具备一个 CLI 版健身教练 Agent：

- `agent.py`：负责 ReAct 循环，解析模型输出，调用工具或启动训练监测。
- `tools.py`：提供训练计划、饮食建议、训练评估、模拟生理数据等工具。
- `memory.py`：用本地 `user_profile.json` 保存用户健身档案。
- `monitor.py`：模拟实时心率、配速、步频，并根据目标心率区间给出即时反馈。
- `llm_client.py`：封装 OpenAI-compatible 的大模型调用。

现在的项目更像一个本地原型。如果想上线，并且接入手表实时查看心率、实时给出健身建议，需要逐步把它改造成一个在线实时健身教练系统。

## 总体发展方向

建议把项目拆成四层：

1. **设备数据层**  
   接入手表、BLE 心率带、手机桥接 App 或厂商健康 API，获取心率等生理数据。

2. **实时会话层**  
   后端接收心率样本，维护训练状态，计算目标心率区间，判断是否需要提醒。

3. **建议引擎层**  
   规则引擎负责秒级即时反馈，LLM 负责更自然的总结、解释和个性化建议。

4. **客户端层**  
   Web 或 App 展示实时心率、目标区间、训练时长、当前建议和训练总结。

## 推荐技术架构

```text
智能手表 / 心率带 / 手机桥接 App
        |
        v
设备接入层 Wearable Integration
        |
        v
FastAPI 后端
        |
        +--> 实时会话管理 Session Monitor
        |
        +--> 建议引擎 Advice Engine
        |
        +--> 数据库存储 PostgreSQL / SQLite
        |
        v
WebSocket 实时推送
        |
        v
Web Dashboard / Mobile App
```

推荐优先使用：

- 后端：FastAPI
- 实时通信：WebSocket
- 开发期数据库：SQLite
- 上线数据库：PostgreSQL
- 前端：先做简单 Web Dashboard
- 设备 MVP：先用模拟器，再接 BLE 心率带或手机桥接手表数据

## 分阶段路线

### Phase 1：把现有逻辑服务化

目标：先不急着上线，把当前 CLI 逻辑改造成可以被 API 调用的服务逻辑。

建议做法：

- 保留 `tools.py` 里的 `generate_plan`、`diet_advice`、`evaluate_session`。
- 继续复用 `monitor.py` 里的 `target_hr_range`、`simulate_tick`。
- 把 `monitor.py` 中直接 `print` 的逻辑逐步改造成返回结构化事件。
- 新增数据结构：
  - 用户档案 `UserProfile`
  - 心率样本 `HeartRateSample`
  - 训练会话 `WorkoutSession`
  - 建议事件 `AdviceEvent`
- 保留 `agent.py` 作为 CLI demo，不需要一开始就删掉。

结构化事件示例：

```json
{
  "type": "heart_rate_sample",
  "heart_rate": 145,
  "zone": "燃脂区",
  "target_low": 114,
  "target_high": 133,
  "timestamp": "2026-07-01T10:00:00"
}
```

建议事件示例：

```json
{
  "type": "advice_event",
  "severity": "warning",
  "message": "心率持续高于目标区间，请降低配速并调整呼吸。",
  "recommended_action": "降低强度",
  "cooldown_seconds": 60
}
```

### Phase 2：新增 FastAPI 后端

目标：让这个 Agent 可以作为在线服务使用。

建议新增目录：

```text
api/
  main.py
  routes/
    profile.py
    sessions.py
  ws/
    realtime.py

services/
  advice_engine.py
  session_monitor.py
```

最小 API：

- `GET /health`：健康检查。
- `GET /profile`：读取用户档案。
- `PUT /profile`：更新用户档案。
- `POST /sessions`：创建训练会话。
- `POST /sessions/{id}/stop`：停止训练会话。
- `GET /sessions/{id}`：查询训练结果。
- `WS /sessions/{id}/stream`：实时推送心率和建议。

第一版可以先不接真实手表，而是用 `monitor.py` 的模拟心率流通过 WebSocket 推送给前端。

### Phase 3：做实时训练 Dashboard

目标：先让用户能直观看到实时训练效果。

页面建议展示：

- 当前心率。
- 目标心率区间。
- 当前训练区间，例如燃脂区、有氧区、高强度区。
- 训练时长。
- 当前配速或步频。
- 最近一条实时建议。
- 训练结束总结。

第一版建议先做 Web 页面，不急着做 App。Web Dashboard 更快验证产品闭环。

### Phase 4：替换本地 JSON 为数据库

当前 `memory.py` 使用 `user_profile.json`，只适合本地单用户 demo。上线后需要数据库。

推荐路线：

1. 开发期：SQLite + SQLAlchemy。
2. 上线期：PostgreSQL。
3. 心率数据量变大后：考虑 TimescaleDB 或其他时序数据库。

核心表设计：

- `users`：用户账号。
- `profiles`：用户健身档案。
- `workout_sessions`：训练会话。
- `heart_rate_samples`：心率样本。
- `advice_events`：实时建议记录。
- `device_connections`：设备连接信息。

### Phase 5：接入真实手表或心率设备

不要一开始就直接做 Apple Watch / Garmin / Fitbit 全家桶。建议按难度逐步推进。

#### 方案 A：继续用模拟器

优点：最快验证后端、WebSocket、前端、建议逻辑。

适合第一里程碑。

#### 方案 B：BLE 心率带

优点：很多心率带支持标准 BLE Heart Rate Service，实时性好，适合 MVP 演示。

缺点：智能手表不一定稳定暴露标准 BLE 心率服务。

#### 方案 C：手机桥接 App

适合 Apple Watch / Wear OS 的真实实时心率。

架构：

```text
手表传感器
  -> 手机 App
  -> 后端 WebSocket / HTTPS
  -> Web Dashboard
```

优点：更接近真实产品。

缺点：需要移动端开发，复杂度更高。

#### 方案 D：厂商云 API

例如 Fitbit、Garmin、Google Fit、Health Connect。

优点：适合历史数据同步。

缺点：很多厂商 API 并不适合秒级实时心率，可能有延迟、权限和频率限制。

## 设备接入抽象

建议新增：

```text
integrations/
  wearables/
    base.py
    simulator.py
    ble_hr.py
    fitbit.py
    garmin.py
    health_connect.py
```

统一接口可以类似：

```python
class WearableClient:
    def connect(self):
        ...

    def read_sample(self):
        ...

    def disconnect(self):
        ...
```

这样后续可以把模拟器、BLE、手表云 API 都接到同一套实时会话逻辑里。

## 实时建议策略

不建议每一拍心率都调用大模型。原因是：

- 成本高。
- 延迟不稳定。
- 关键安全提醒不能完全交给 LLM。

推荐方式：

1. **秒级反馈用规则引擎**
   - 心率过高：提示降低强度。
   - 心率过低：提示适当加快。
   - 步频偏低：提示加快摆臂、缩小步幅。
   - 持续超区间：升级提醒。

2. **阶段总结用 LLM**
   - 每 5-10 分钟总结一次训练状态。
   - 根据用户目标给出更自然的建议。

3. **训练后复盘用 LLM**
   - 总结平均心率、峰值心率、达标率、纠正次数。
   - 给出下一次训练建议和饮食建议。

## 安全边界

因为涉及心率和健康数据，需要特别注意：

- 明确提示“这不是医疗建议”。
- 心率异常过高时，规则引擎应直接建议停止训练、休息、必要时寻求专业帮助。
- 高风险判断尽量用确定性规则，不让 LLM 自由发挥。
- 不要保存不必要的敏感健康信息。
- 上线后必须考虑用户数据导出、删除和隐私保护。

## 上线准备

上线前需要补齐：

- 用户登录和鉴权。
- HTTPS。
- 环境变量和密钥管理。
- Docker 部署。
- 数据库迁移。
- 日志和监控。
- WebSocket 连接监控。
- LLM 调用延迟和费用监控。
- 健康数据隐私策略。

## 第一里程碑建议

建议先做：**Realtime Simulated Workout Dashboard**。

范围：

- FastAPI 后端。
- WebSocket 实时流。
- 继续使用 `monitor.py` 模拟心率。
- 前端实时展示心率、目标区间和建议。
- 训练结束生成总结。

这个版本不接真实手表，但可以完整验证产品体验和技术架构。等这个闭环跑通后，再把数据源从模拟器替换成 BLE 或手表桥接数据。

## 验证方式

### 单元测试

重点验证：

- `generate_plan`
- `diet_advice`
- `evaluate_session`
- `target_hr_range`
- `simulate_tick`

### API 测试

重点验证：

- 创建用户档案。
- 更新用户档案。
- 创建训练会话。
- 停止训练会话。
- 查询训练历史。

### WebSocket 测试

重点验证：

- 客户端能连接训练流。
- 能持续收到心率样本。
- 心率超出目标区间时能收到建议事件。
- 训练结束后连接能正常关闭。

### 端到端测试

完整流程：

1. 启动后端。
2. 打开前端 Dashboard。
3. 创建训练会话。
4. 使用模拟心率流推送数据。
5. 页面实时刷新心率和建议。
6. 停止训练。
7. 查看训练总结。

## 一句话总结

最合理的路线是：先把当前 CLI Agent 产品化成一个可实时推送的 Web 健身教练，再逐步接入真实设备；模拟器验证架构，BLE 或手机桥接验证真实实时心率，LLM 负责个性化总结，规则引擎负责即时和安全建议。
