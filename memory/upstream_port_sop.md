# 上游增量移植 SOP（GenericAgent fork 维护）

**触发**：用户要求"看上游有什么改进 / 吸收上游改动"。GA_OpenSquilla 是 lsdefine/GenericAgent 的 fork，分叉严重**不能 merge，只能手动 patch**。

## 1. 拉取与列清单（实测 ~34s）
```bash
git fetch upstream main --tags          # upstream=https://github.com/lsdefine/GenericAgent
git log <上次基线>..upstream/main --oneline --date=short --pretty=%h|%ad|%an|%s
git diff --name-only <基线>..upstream/main      # 再按"本地是否存在"过滤，desktop/React 产物本地多半没有
git diff --stat  <基线>..upstream/main
git diff <基线>..upstream/main -- <file> > plan_port_upstream/u2_<file>.diff   # 逐文件存 diff 再读
```
- **Windows 没有 `diff` 命令**（cmd 里 `diff` 不存在）→ 用 `git diff` 或 Python `difflib`
- `plan_port_upstream/` 已在 .gitignore，可放心堆放 diff/报告

## 2. 移植前必做核对（最耗时的坑都在这里）
- **同名 ≠ 同源**：本地 `hub.pyw` 是 tkinter 启动器，上游 `hub.pyw` 也是；但上游的 WS hub 是**另一个新文件** `frontends/hub.py`。**必须 file_read 两边确认功能**再决定"patch 本地"还是"引入新文件"
- **可能是超集**：本地某文件可能只是上游旧版的子集（如 `frontends/cost_tracker.py` 本地 7KB vs 上游 17KB）→ 直接取上游全文覆盖，但先确认本地独有行（`difflib` 看 `-` 行），若有则合并
- 取上游文件：`git show upstream/main:<path>`，写入时 `newline="\n"`（上游是 LF）
- 改动前**留备份**：`bak/port_<批次>_<日期>/`。注意根 `.gitignore` **未忽略 bak/**，提交时别误 add

## 3. 验证手段（本机可行组合）
- 语法：`python -m py_compile <f>` 逐个；再 `import llmcore, ga` 冒烟
- **pytest 未装且 pip 装不上**（代理 handshake 超时）→ 别指望跑上游 tests/，自己写功能测试
- **网络类改动用本地 mock 服务端到端验证**：
  - abort 唤醒 → mock HTTP handler 先 `sleep(8)` 再发响应头，对比 abort 后 worker 退出耗时（修复后 0.00s）
  - 退避可中断 → mock 恒返回 429 + `Retry-After`，对比中止耗时（修复后 1.6s vs 原本 30s）
  - TTFT/TPS → mock SSE 服务逐个 `data: {...}` + `[DONE]`
- 前端/WS：用假 agent 对象（注意本地 `agent.list_llms()` 返回 **3 元组**，别按 2 元组写测试）+ FastAPI TestClient / WS 直连
- HTML 改动：`node --check` 校验提取出的 JS

## 4. 提交纪律
- 工作区常有用户未提交的改动（如 `frontends/fsapp.py`、`memory/*_sop.md`）→ **只用 `git add -- <显式路径列表>`**，绝不用 `-A`
- 生效边界：改动的是运行中的进程（`agentmain.py`、`frontends/fsapp.py`）时需**重启进程**才生效，交付时明确告诉用户
- 记录下次对比基线（本次 = upstream `1b6442f`，2026-09-14）

## 验证于
- 2026-09-15 移植 `f06d550→1b6442f` 的 A/B 级共 17 项（commit cf073b3）：12 文件 py_compile + A1/A2/B1 mock 服务端到端 + hub/conductor 假 agent 集成 + node --check 全部通过
