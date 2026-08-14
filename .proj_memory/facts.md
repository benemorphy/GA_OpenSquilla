# Project Facts (GA_OpenSquilla) — GenericAgent

## 概览
**GenericAgent** — 极简自进化自主智能体框架。
- 包名: `genericagent` v0.1.0
- 入口: `ga.py` / `agentmain.py` / `agent_loop.py` / `hub.pyw` / `launch.pyw`
- CLI: `ga` (via `ga_cli.cli:main`)
- 核心规模: ~3K 行种子代码, 9 个原子工具, ~100 行 Agent Loop
- 论文: arXiv 2604.17091 (https://arxiv.org/abs/2604.17091)
- 官网: https://gaagent.ai
- Git: main branch, latest `6b1713d` (2026-07-17)
- Python: >=3.10, <3.14

## 核心组件

| 文件/模块 | 说明 |
|-----------|------|
| `ga.py` | 主入口 (35 KB) |
| `agentmain.py` | Agent 主循环 (17.9 KB) |
| `agent_loop.py` | 智能体循环核心 (9.6 KB) |
| `llmcore.py` | LLM 核心调用 (62.6 KB) |
| `simphtml.py` | 简易 HTML 工具 (42.3 KB) |
| `TMWebDriver.py` | 浏览器驱动 (14.6 KB) |
| `hub.pyw` | 中心 Hub (10 KB) |
| `launch.pyw` | 启动器 (8.7 KB) |
| `mykey.py` | API 密钥 (2.7 KB) |
| `ga_cli/` | CLI 命令行工具 |
| `squilla_router/` | MCP 风格路由 (cascade_router, controller, models) |
| `reflect/` | 反射模式 (autonomous, goal_mode, scheduler, checklist_master) |
| `frontends/` | 前端 (conductor, chatapp, at_complete) |
| `plugins/` | 插件系统 (hooks, langfuse_tracing) |
| `memory/` | SOP 系统 (全局记忆、SOP文档、工具脚本) |
| `temp/` | 临时文件和工作目录 |

## 关键目录
- `memory/` — SOP 系统根目录，包含:
  - `global_mem.txt` (全局事实), `global_mem_insight.txt` (索引入口)
  - L3 SOPs: deep_research_sop, memory_cleanup_sop, plan_sop, itndf_train_sop, tmwebdriver_sop, ljqCtrl_sop, vision_sop, adb_ui, ocr_utils 等
  - `L4_raw_sessions/` — 历史会话记录
  - 子目录: `autonomous_operation_sop/`, `review_sop/`, `skill_search/`
- `docs/` — 文档 (architecture, installation guides)
- `squilla_router/` — cascade_router, models, runtime_src
- `reflect/` — autonomous.py, goal_mode.py, scheduler.py
- `frontends/` — conductor.html, conductor.py

## 工具链
- 自主运行: `python reflect/autonomous.py`
- 目标模式: `python reflect/goal_mode.py`
- 调度器: `python reflect/scheduler.py`
- 检查表: `python reflect/checklist_master.py`
- 路由: `squilla_router/controller.py`

## 配置变更记录
- 2026-08-03: `mykey.py` 的 `native_oai_config.api_mode` 从 `'chat_completions'` 改为 `'responses'`。
  - deepseek-v4-flash 实测支持 OpenAI Responses API（`https://api.deepseek.com/v1/responses`）：流式文本 + function calling + prompt cache 均可用。
  - `llmcore.py` 原生支持 `api_mode='responses'`（`_openai_stream`/`_parse_openai_sse`/`_prepare_oai_tools`/`_to_responses_input` 均已实现），无需改框架。
  - 注意：`raw_ask` 是生成器，文本经 yield 传出，工具调用 blocks 经生成器 return 值（`StopIteration.value`）传出。
  - 切回旧端点：改回 `'chat_completions'`（`/v1/chat/completions`）。

- 2026-08-11: 继续CAD识别（住宅平面剖面0902.dwg，AutoCAD COM 已打开）。产出增量空间分析 `temp/住宅平面剖面0902_增量分析.md`。
  - 空间结构: 左下图层说明表 + 3排标准层户型(y≈90k/140k/180k，每排3个完整户型单元，规模递增) + 顶部机房带(y≈230k: 电梯机房19/排风机房7)。
  - 文字660条: 飘窗87/电84/水69/阳台48/客厅48/餐厅48/玄关30/电梯机房19/担架电梯15/合用前室15。
  - 图块2287: 座便004×194/水槽001×106/冰箱×106/浴缸A1800×58，家具464个集中在主力户型层。
  - 数据文件: temp/cad_texts_pos.json(660条文字坐标), temp/cad_blocks_pos.json(2287图块坐标), temp/cad_texts_extract.json。
  - **坑**: 逐实体读Layer属性超时(>60s)，只读Text/MText/BlockReference坐标46s完成；doubao大图(≥117KB base64)识别超时，需裁剪≤900px(65KB)才成功——视觉辅助只能用小图。

- 2026-08-11: 剖面信息提取完成 `temp/住宅平面剖面0902_剖面信息.md`。剖面图位于底部条带第2段 x≈530-730k, y≈0-75k。
  - 识别方法: doubao视觉确认(楼板/梁/墙/门窗/3单元/26层) + COM几何验证(22条楼层线，层高2800mm)。
  - 剖面特征: 22层(几何)/~26层(视觉含屋顶)，3个电梯入户单元，无楼梯斜线(楼梯在匿名块内)，顶部y=73175/73475/73575为女儿墙构造。
  - 底部条带3段: seg1=立面图(11/26/26层3种楼栋), seg2=剖面图, seg3=平面图(6层2单元)。
  - 全量实体缓存: temp/cad_all_ents.json(8647非Zombie实体, 61s)。

- 2026-08-11: 配置火山方舟(ARK) doubao-seed 多模态 `doubao_vision_config` 到 `mykey.py`（vision_api.py 的 OPENAI_CONFIG_KEY 已指向它，主用 ARK）。
  - 端点: `https://ark.cn-beijing.volces.com/api/v3`（OpenAI 兼容），apikey 取环境变量 `ARK_API_KEY`，model=`doubao-seed-2-0-pro-260215`（实测可用；lite/mini/2-1-pro 返回 ModelNotOpen 需在 Ark Console 开通）。
  - vision_api.py `_call_openai_compat` 已支持多种 apibase 拼接：`/v1`、`/v3` → 直接加 `/chat/completions`；裸地址 → 加 `/v1/chat/completions`；完整 URL 原样。
  - 本地 8090 llama.cpp qwen3-vl 仍保留为 `ocr_config` 备选（需先启动服务）。
  - 注意: `doubao_vision_config`/`ocr_config` 变量名含 'config' 会被 agentmain 扫描，但 resolve_session 对非 native/claude/oai 名返回 None，不会加入 LLM 会话，安全。

- 2026-08-11: 配置本地 OCR/视觉模型 `ocr_config` 到 `mykey.py`（vision_api.py 的 OPENAI_CONFIG_KEY 已指向它）。
  - 端点: `http://localhost:8090`（llama.cpp llama-server，OpenAI 兼容），model=`qwen3-vl-4b-yoyo-instruct-q8_0.gguf`，无需 apikey。
  - 已验证: `/health`→200, `/v1/models`→200, 纯文本 chat 200；大图请求(406KB)会导致服务断连(RemoteDisconnected/连接拒绝)，需先缩放图片(≤512px)。
  - 注意: `ocr_config` 变量名含 'config' 会被 agentmain 扫描，但 resolve_session 对非 native/claude/oai 名返回 None，不会加入 LLM 会话，安全。
  - 注意: vision_api.py 之前用 `native_oai_config`(DeepSeek) 做 vision，现已切到本地 8090。

- 2026-08-05: 移植上游 lsdefine/GenericAgent (upstream/main=284b332) 高价值升级，commit `81d17b4`。
  - 分叉严重(上游+1183/本地+718)，不能 merge，仅手动 patch 4 文件：llmcore.py / ga.py / TMWebDriver.py / agentmain.py。
  - llmcore: Responses API 终态(incomplete/failed)+reasoning_text 流、max_retry_after 封顶、ChunkedEncodingError 重试、should_stop 跳过重试、active_response abort 掐流、STATS、trim_keep_prefix、mykey 热重载(sys.modules.pop)。
  - ga: _file_newline 换行符保护、_arg 类型强转、code_run stdin=DEVNULL、timeout>600 拒绝、_get_tool_maxlen。
  - TMWebDriver: safe_print 全面替换 + Origin header 防护(防 CSRF)。
  - agentmain: max_turns 180、长 prompt 唯一化(pid+time_ns)、oldname sticky llm_no、_current_queue/all_outputs。
  - 保留本地独有: switch_tier/switch_model/MixinSession(_raw_ask 回退)/_cn schema/CDP(cdp_cfg+tmwd_cdp_bridge)/GeneraticAgent 别名/agent_loop SquillaRouter 集成。
  - 独立验证 subagent VERDICT: PASS；detail: plan_port_upstream/。
  - 注意: squilla_router/ 3 文件 + sync.ffs_db 有用户未提交改动，未混入本次提交。
