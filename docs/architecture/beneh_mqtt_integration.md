# Beneh ↔ Mqtt_bbs 集成分析

> 分析日期: 2026-06-15
> 基于: CodeGraph索引(SQLite) + 源码阅读

---

## 项目定位

Beneh 是 GenericAgent 的 MQTT 衍生分支——AI 辅助文学创作项目，多 Agent 协作生成小说，通过 MQTT BBS 消息总线实现分布式跨机器实时通信。

## 系统拓扑（5核心服务）

```
                    Mosquitto (MQTT Broker :1883)
                            │
       ┌────────────────────┼────────────────────┐
       │                    │                    │
  BoardService          GA Handler          Feishu Bot
  (Rust :2999)          (ga.py)             (fsapp.py)
       │                    │                    │
       └──────── MariaDB (:3306) ───────────────┘

  + Worker Agents (按需) — 分布式任务执行
  + Dashboard (Streamlit :8501) — 实时监控
```

## 启动顺序约束

**BoardService 必须在 Feishu Bot 和 GA 之前启动**，否则客户端无法注册JWT，MQTT连接会超时。

## 数据流

### 用户→飞书→AI回复
```
Feishu App → fsapp.py → [MQTT bbs/request/ga]
  → ga.py Handler → LLM推理
  → [MQTT bbs/response/ga] → fsapp.py → 用户
```

### Board任务分发→Worker执行
```
AgentBoard.post_task() → PUBLISH board/task/{id}/input (Retain)
WorkerAgent.claim_task() → 执行 → PUBLISH board/task/{id}/output + signal=[ROUND_END]
AgentBoard.wait_task() → 实时收到结果
```

### 能力路由
```
WorkerAgent.start() → PUBLISH node/{id}/capability (Retain)
AgentBoard.post_task_routed(target_capability="scan") → 定向分发
```

## 跨项目依赖（CodeGraph精确数据）

Beneh 中引用 Mqtt_bbs 的文件（通过 import）：

| 文件 | 引用方式 | 用途 |
|------|---------|------|
| `GA/frontends/dashboard_mqtt.py` | `import Mqtt_bbs_server` (Python包) | MQTT仪表盘(Streamlit) |
| `GA/reflect/goal_bbs.py` | `_bbs.connect/register/query_posts/disconnect` | Goal BBS |
| `GA/reflect/goal_nexus.py` | `mqtt.Client` + `bbs.loop_stop/disconnect` | Phase3 Nexus |
| `GA/reflect/goal_mode.py` | `_bbs['pulse']` / `_bbs['chronicle']` / `_bbs['close']` | Goal Mode |
| `GA/scripts/fsapp.py` | `_bbs_d.register` + `_bbs_push_chats` | 飞书Bot推送 |
| `GA/scripts/chatapp_common.py` | `_bbs.register/post` | 聊天公共模块 |
| `GA/tools/curiosity/inspiration_board.py` | `bbs.post/register` + `mqtt.Client` | 灵感板 |
| `GA/tests/` | `mqtt.Client` | 集成测试 |

## 双层BBS架构

Beneh 包含两套 BBS 实现：

| 文件 | 技术栈 | 用途 |
|------|--------|------|
| `GA/assets/agent_bbs.py` | FastAPI + SQLite | 独立HTTP BBS (ApiKeyMiddleware) |
| `GA/frontends/dashboard_mqtt.py` | Streamlit + Mqtt_bbs 项目 | MQTT仪表盘 |
| `GA/reflect/goal_bbs.py` | MQTT Client | Goal BBS |
| `GA/services/bbs_data/` | Python包 | BBS数据服务层 |

## MQTT 集成启动方式

```bash
# MQTT模式启动
rmqtt start && python -m Mqtt_bbs_server.board_service
python agentmain.py --broker-host 127.0.0.1

# 内部触发 mqtt_agent_runner.start_mqtt_agent()
```

## 项目文件清单

- **记忆系统**: memory/ (L0-L3层SOP、MemPalace语义搜索)
- **架构文档**: docs/architecture/ (系统拓扑、数据流)
- **工具集**: tools/llm_providers.py
- **配置**: config/ (Docker Compose, Mosquitto配置)
- 原 **Mqtt_bbs_server/**: 空目录（已删除，客户端代码已自包含）

## 设计原则

1. **MQTT为中心**: 所有服务不直连，全部通过 Mosquitto 间接通信
2. **统一认证**: BoardService 签发JWT，所有客户端需注册才能发布/订阅
3. **持久化隔离**: 仅 BoardService 直连 MariaDB，其他服务通过MQTT间接读写
4. **可替换前端**: 飞书Bot是当前入口，可替换为其他IM
