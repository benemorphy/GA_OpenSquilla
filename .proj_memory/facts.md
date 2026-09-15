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

- 2026-09-15: 上游增量评估（基线 f06d550 → upstream/main=1b6442f，2026-09-14，37 个新提交）。
  - 报告: `plan_port_upstream/upstream_2026-09-14_report.md`；diff 全文 `plan_port_upstream/u2_*.diff`。
  - A 级可直收（本地全未含，均低风险）: ①abort() 唤醒等响应头中阻塞的 recv（llmcore 头部 _INFLIGHT+socket hook，agentmain.py abort() 加 `_real_close()`；上游 f07bfc5/3d62523）②重试退避可中断 `_sleep()`（llmcore `_stream_with_retry`）③`trim_messages_history` 线性化（0c235a8）④ga.py 完成判定 `content[50:][-100:]`（3327a6c）⑤`str(session_id/switch_tab_id)` 强转（71cf559）。
  - B 级按需: TTFT/TPS 统计、UA 2.1.152→2.1.251、context_win 38000/cut 8、禁用 claude `context_management`、NativeClaude `api_key_header`、hub 远程切 LLM、conductor 模型选择加固、cost_tracker jsonl 账本、data_backup.py、stapp 流式修复（需 streamlit>=1.62，本机 1.57）。
  - C 级不吸收: Desktop 2.0 全套（React/Tauri/CI/发布资格，需 npm+rust）、vision_sop 默认后端变更（本机 deepseek vision 为本地独有）、wechatapp conductor 修复（本地无该逻辑）。
  - 长期约束: 分叉严重不能 merge，只能手动 patch；本地独有（SquillaRouter/_cn schema/CDP/fsapp sleep/vision deepseek）不可破坏。

- 2026-08-14: 飞书通道新增远程S3睡眠命令。`frontends/fsapp.py` FeishuApp override `handle_command` 支持 `/sleep` `/s3` `/s3sleep [秒]`（默认3s，上限60s）→ 调 `temp/s3_sleep2.ps1`(SetSuspendState+日志) 进入S3睡眠；不依赖LLM直达。fsapp.py 长连接 main() 自带重连，唤醒后自动恢复。mykey.py `fs_allowed_users` 为 "*" (public模式，任意飞书用户可发命令)。重启方式：杀旧 fsapp 进程后 `.venv\Scripts\python.exe frontends/fsapp.py`（日志 temp/fsapp_restart.log）。

- 2026-08-22: 配置 DeepSeek V4 flash vision exp 到 `mykey.py`（`deepseek_vision_config`），`memory/vision_api.py` 的 `OPENAI_CONFIG_KEY` 已指向它（主用；ARK doubao 与本地 8090 为备选）。
  - 模型名: `deepseek-v4-flash-vision-exp`，端点 `https://api.deepseek.com/v1`（OpenAI 兼容 /v1/chat/completions），复用 `DEEPSEEK_API_KEY`（与 native_oai_config 同一 key）。
  - 文档: https://api-docs.deepseek.com/guides/vision — 图片格式 JPEG/PNG/GIF/WebP，内联 base64 ≤48MiB，URL ≤8192 字符/32MiB，Files API ≤64MiB。
  - 实测: ask_vision 中文描述测试图成功（蓝色方框+红色圆圈识别正确）。vision_api.py 的 `_call_openai_compat` 已兼容（apibase 以 /v1 结尾自动拼 /chat/completions）。
  - **2026-08-22 补充**: vision 已切换 Responses API 模式。`deepseek_vision_config` 加 `'api_mode': 'responses'`；`memory/vision_api.py` 的 `_call_openai_compat` 新增 responses 分支（POST /v1/responses, input 用 input_text/input_image, 解析 output[] 中 message.content[].output_text）。实测成功。主会话 native_oai_config 本就 api_mode='responses'（llmcore.py L484 auto_make_url "responses"）。

- **2026-08-22 scheduler 恢复**: weekly_memory_tidy 因 launch.pyw 未带 --sched 参数导致 scheduler 未运行而漏执行。已手动补做(报告 done/2026-08-22)。scheduler 正确启动方式: `python agentmain.py --reflect reflect/scheduler.py --llm_no 0`(不能直接跑 scheduler.py, 无入口)。已启动: 主进程+reflect子进程+端口45762锁。**教训: launch.pyw --feishu 不带 --sched 则定时任务不跑**。

## 2026-09-15 上游 A/B 级移植完成 (commit cf073b3)
- 上游基线更新: upstream/main = 1b6442f (2026-09-14, 37 个新提交)；评估报告 `plan_port_upstream/upstream_2026-09-14_report.md`
- 已移植（全部 py_compile + 实测）：
  - A1 abort 唤醒"等响应头"中阻塞的 recv（llmcore `_INFLIGHT` + urllib3 request hook；agentmain.abort 加 `_real_close()`）→ 实测 8s→0.00s
  - A2 重试退避可中断 `_sleep()` → 实测 30s→1.63s
  - A3 `trim_messages_history` 线性化 → 120→8 msgs 用时 9ms
  - A4 完成判定 `content[50:][-100:]`；A5 session_id `str()` 强转（ga.py 两处 + TMWebDriver.py）
  - B1 TTFT/decode-TPS 统计（本地 SSE mock 端到端实测通过）；B2 UA→2.1.251；B3 ctx 38000/cut 8
  - B4 去掉 claude `context_management` payload；B5 `api_key_header`(auto|x-api-key|bearer)
  - B6 新增 WS hub（frontends/hub.py + hub.html + hub_p2p.py + p2p_ws_client.py）→ 假 agent 实测 llms 列表/切换/越界均正确
  - B7 conductor 模型选择（/llms /llm 端点 + WS `llm`/`model_selected` 广播 + 任务边界应用）→ 集成实测通过
  - B8 cost_tracker jsonl 账本（跨进程/10MB 压缩/坏行容错）→ 往返测试通过
  - B10 frontends/data_backup.py（857 行，零第三方依赖）；B11 提示词（摘要措辞/宪法去重/remember 成功判定）
- **未移植 B9**（stapp 流式修复）：本地 stapp 是同步渲染架构，与上游 fragment tick 架构不同源，主体不适用；且本机 streamlit 1.57 < 上游要求 1.62
- **生效需重启**：运行中的 `agentmain.py --reflect ...` 与 `frontends/fsapp.py` 仍加载旧代码
- 备份：`bak/port_ab_20260915/`（本次改动前的原件；注意 `.gitignore` 未忽略 bak/，勿误提交）
- 下次对比基线：upstream **1b6442f**
