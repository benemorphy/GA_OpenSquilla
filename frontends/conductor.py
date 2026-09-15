import os, sys, re, time, json, uuid, queue, asyncio, threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path: sys.path.insert(0, ROOT)

from agentmain import GenericAgent

HOST = "127.0.0.1"
PORT = 8900
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conductor.html")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 服务启动（事件循环已就绪）：捕获 loop 供工作线程跨线程推 WS 广播，并起主agent
    global main_loop
    main_loop = asyncio.get_running_loop()
    conductor.start()
    threading.Thread(target=im_poll_loop, name="im-poller", daemon=True).start()
    yield


app = FastAPI(title="Conductor", lifespan=lifespan)

class ChatIn(BaseModel):
    msg: str
    role: str = "conductor"  # conductor | system | user

class StartSubagentIn(BaseModel):
    prompt: str

class ApprovalIn(BaseModel):
    prompt: str
    source: str = ""

class SubagentActionIn(BaseModel):
    action: str = "intervene"  # intervene | abort | kill
    msg: str = ""

@dataclass
class SubAgentState:
    id: str
    agent: GenericAgent
    prompt: str
    thread: Optional[threading.Thread] = None
    reply: str = ""
    status: str = "running"  # running | stopped
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

ws_clients: set[WebSocket] = set()
main_loop: Optional[asyncio.AbstractEventLoop] = None
# conductor event queue: only user messages and subagent-done events enter here.
chat_messages: List[dict] = []

def now_ms() -> int:
    return int(time.time() * 1000)

def short_id() -> str:
    return uuid.uuid4().hex[:8]

_TURN_SPLIT_RE = re.compile(r'\**LLM Running \(Turn \d+\) \.\.\.\**')
_SUMMARY_RE = re.compile(r'<summary>(.*?)</summary>\s*', re.DOTALL)

def extract_last_summary(full: str) -> str:
    """Extract the latest <summary> content for in-progress display."""
    matches = _SUMMARY_RE.findall(full or "")
    if not matches: return ""
    s = matches[-1].strip()
    return s[-1000:] if len(s) > 1000 else s

def extract_last_text_reply(full: str) -> str:
    """Extract only the last turn's text reply (like stapp.py fold_turns logic)."""
    # Split by turn markers, take last segment
    parts = _TURN_SPLIT_RE.split(full)
    last = parts[-1] if parts else full
    # Strip <summary> tags
    last = _SUMMARY_RE.sub('', last)
    # Strip [Status] and [Info] lines
    last = re.sub(r'\[(Status|Info)\][^\n]*\n?', '', last)
    # Strip trailing whitespace
    last = last.strip()
    # Cap length
    return last[-3000:] if len(last) > 3000 else last

def clean_log_text(s: str) -> str:
    if not s: return s
    s = re.sub(r'`{5}\n.*?`{5}\n?', '', s, flags=re.DOTALL)
    s = re.sub(r'🛠️ Tool: `([^`]+)`\s*📥 args:\n`{4}.*?`{4}\n?', r'🛠️ `\1`\n', s, flags=re.DOTALL)
    s = re.sub(r'^🛠️ .*\n?', '', s, flags=re.MULTILINE)  # remove tool call summary lines
    s = re.sub(r'<thinking>.*?</thinking>\s*', '', s, flags=re.DOTALL)
    s = re.sub(r'^\s*\[(?:Info|Status)\][^\n]*\n?', '', s, flags=re.MULTILINE)
    s = re.sub(r'^\s*`{4,5}\s*$\n?', '', s, flags=re.MULTILINE)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def schedule_broadcast(payload: dict):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(payload), main_loop)

async def broadcast(payload: dict):
    dead = []
    for ws in list(ws_clients):
        try: await ws.send_json(payload)
        except Exception: dead.append(ws)
    for ws in dead: ws_clients.discard(ws)

def push_cards(): schedule_broadcast({"type": "subagents", "items": pool.snapshot()})

# ---- 模型绑定：把桌面设置里 conductor 绑定的 LLM 编号应用到总管会话 ----
# 上游设计要点：绑定值只持久化，不在任务进行中改 live client；下一个任务边界才生效。
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".ga_desktop_settings.json")


def _settings_doc() -> dict:
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _persist_conductor_llm_no(llm_no: int) -> None:
    """只改 conductor.llmNo 一段，写回时保留文件其它内容。"""
    doc = _settings_doc()
    section = doc.get("conductor")
    if not isinstance(section, dict):
        section = {}
        doc["conductor"] = section
    section["llmNo"] = llm_no
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SETTINGS_PATH)


def _conductor_llm_no() -> Optional[int]:
    """读总管绑定的模型编号；兼容旧版桌面默认值 ui.llmNo。"""
    doc = _settings_doc()
    for section in (doc.get("conductor"), doc.get("ui")):
        if isinstance(section, dict) and section.get("llmNo") is not None:
            try:
                return int(section.get("llmNo"))
            except (TypeError, ValueError):
                pass
    return None


def _client_usable(agent: "GenericAgent") -> bool:
    return hasattr(getattr(agent, "llmclient", None), "backend")


def _parse_model_no(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usable_model(agent: "GenericAgent", no: Optional[int]) -> bool:
    clients = getattr(agent, "llmclients", []) or []
    return no is not None and 0 <= no < len(clients) and hasattr(clients[no], "backend")


def _activate_model(agent: "GenericAgent", no: int) -> None:
    if not _usable_model(agent, no):
        raise ValueError(f"llm index out of range or unavailable: {no}")
    agent.next_llm(no)


def _runtime_model_state(agent: "GenericAgent", configured: Optional[int], reason: Optional[str]) -> dict:
    effective = getattr(agent, "llm_no", None) if _client_usable(agent) else None
    current = None
    if _client_usable(agent):
        try:
            current = str(agent.llmclient.backend.name)
        except Exception:
            pass
    return {"configured": configured, "effective": effective,
            "fallbackReason": reason, "current": current}


def _apply_desktop_model(agent: "GenericAgent") -> dict:
    """任务开始前让总管会话对齐当前绑定：
    有绑定就切过去；没有也要刷新 mykey（否则导入密钥后不重启永远不生效）。
    失败逐级降级：绑定值 → ui 默认值 → 第一个可用模型。"""
    doc = _settings_doc()
    conductor_cfg = doc.get("conductor") if isinstance(doc.get("conductor"), dict) else {}
    ui_cfg = doc.get("ui") if isinstance(doc.get("ui"), dict) else {}
    raw_configured = conductor_cfg.get("llmNo")
    configured = _parse_model_no(raw_configured)
    ui_default = _parse_model_no(ui_cfg.get("llmNo"))

    try:
        agent.load_llm_sessions()   # mtime 保护：mykey 变了才重建
    except Exception as e:
        print(f"[conductor] failed to refresh model sessions: {e}", file=sys.stderr)

    clients = getattr(agent, "llmclients", []) or []

    configured_failed = False
    if _usable_model(agent, configured):
        try:
            _activate_model(agent, configured)
            return _runtime_model_state(agent, configured, None)
        except Exception as e:
            configured_failed = True
            print(f"[conductor] configured model #{configured} is unavailable: {e}", file=sys.stderr)

    if _usable_model(agent, ui_default):
        if raw_configured is None:
            reason = "ui_default"
        elif configured_failed:
            reason = "configured_unavailable"
        elif configured is not None:
            reason = "configured_unavailable" if 0 <= configured < len(clients) else "invalid_configured"
        else:
            reason = "invalid_configured"
        try:
            _activate_model(agent, ui_default)
            return _runtime_model_state(agent, configured, reason)
        except Exception as e:
            print(f"[conductor] UI default model #{ui_default} is unavailable: {e}", file=sys.stderr)

    for i, client in enumerate(clients):
        if hasattr(client, "backend"):
            try:
                _activate_model(agent, i)
                return _runtime_model_state(agent, configured, "first_available")
            except Exception:
                continue

    print("[conductor] no usable model is available", file=sys.stderr)
    return {"configured": configured, "effective": None,
            "fallbackReason": "no_models", "current": None}


def _selected_conductor_llm_no(agent: "GenericAgent") -> int:
    configured = _conductor_llm_no()
    return configured if _usable_model(agent, configured) else getattr(agent, "llm_no", -1)


def _set_conductor_llm_no(agent: "GenericAgent", value: Any) -> int:
    """持久化绑定但不改 in-flight 客户端；总管循环在下个任务边界应用。"""
    no = _parse_model_no(value)
    if no is None or not _usable_model(agent, no):
        raise ValueError(f"llm index out of range or unavailable: {value}")
    _persist_conductor_llm_no(no)
    return no

def add_chat(msg: str, role: str = "conductor"):
    item = {"id": short_id(), "role": role, "msg": msg, "ts": now_ms(), "read": role != "user"}
    chat_messages.append(item)
    if len(chat_messages) > 200: del chat_messages[:-200]
    schedule_broadcast({"type": "chat", "item": item})
    return item

def start_agent_runner(agent: GenericAgent, name: str):
    t = threading.Thread(target=agent.run, name=name, daemon=True)
    t.start(); return t

def monitor_display_queue(agent_id: str, dq: "queue.Queue", trigger_when_done: bool):
    acc = ""
    while True:
        item = dq.get()
        if "next" in item:
            chunk = item.get("next") or ""
            acc += chunk
            pool.on_display(agent_id, acc, done=False)
            push_cards()
        if "done" in item:
            done = item.get("done") or acc
            pool.on_display(agent_id, done, done=True)
            push_cards()
            if trigger_when_done: conductor.notify({"type": "subagent_done", "id": agent_id, "reply": done})
            break


class SubagentPool:
    def __init__(self):
        self.subagents: Dict[str, SubAgentState] = {}
        self.lock = threading.RLock()
        threading.Thread(target=self._auto_cleanup_loop, name="subagent-cleanup", daemon=True).start()
    def snapshot(self) -> list[dict]:
        with self.lock:
            return [
                {
                    "id": s.id,
                    "prompt": s.prompt,
                    "reply": (extract_last_summary(s.reply) if s.status == "running" else extract_last_text_reply(s.reply)) if s.reply else "",
                    "status": s.status,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                }
                for s in self.subagents.values()
            ]
    def get(self, sid: str) -> Optional[SubAgentState]:
        with self.lock: return self.subagents.get(sid)
    def counts(self) -> tuple:
        with self.lock:
            running = sum(1 for s in self.subagents.values() if s.status == "running")
            stopped = sum(1 for s in self.subagents.values() if s.status != "running")
        return running, stopped
    def on_display(self, agent_id: str, acc: str, done: bool):
        with self.lock:
            s = self.subagents.get(agent_id)
            if s:
                s.reply = acc
                s.updated_at = time.time()
                s.status = "stopped" if done else "running"
    def _auto_cleanup_loop(self):
        IDLE_TIMEOUT = 3600
        while True:
            time.sleep(300) 
            now = time.time()
            to_abort = []
            with self.lock:
                for sid, s in self.subagents.items():
                    if s.status == "stopped" and (now - s.updated_at) > IDLE_TIMEOUT: to_abort.append((sid, s))
            for sid, s in to_abort:
                s.agent.abort()
                s.agent.task_queue.put("EXIT")  
                with self.lock: self.subagents.pop(sid, None)  
            if to_abort: push_cards()
    def start_subagent(self, prompt: str) -> dict:
        sid = short_id()
        agent = GenericAgent()
        agent.inc_out = True
        agent.verbose = False
        agent.no_print = True
        th = start_agent_runner(agent, f"subagent-{sid}")
        state = SubAgentState(id=sid, agent=agent, prompt=prompt, status="running", thread=th)
        with self.lock: self.subagents[sid] = state
        return self._send_msg(sid, prompt)
    def _send_msg(self, sid, msg):
        with self.lock: s = self.subagents.get(sid)
        if not s: return {"error": "subagent not found", "id": sid}
        dq = s.agent.put_task(msg, source=f"subagent:{sid}")
        threading.Thread(target=monitor_display_queue, args=(sid, dq, True), name=f"monitor-{sid}", daemon=True).start()
        push_cards()
        return {"id": sid, "status": "running"}
    def input_subagent(self, sid: str, msg: str) -> dict:
        with self.lock: s = self.subagents.get(sid)
        if not s: return {"error": "subagent not found", "id": sid}
        if s.status == "running": return {"error": "subagent is still running, cannot input/reply. Start a new subagent instead.", "id": sid}
        s.prompt = msg
        s.reply = ""
        s.status = "running"
        s.updated_at = time.time()
        return self._send_msg(sid, msg)
    def keyinfo_subagent(self, sid: str, msg: str) -> dict:
        with self.lock: s = self.subagents.get(sid)
        if not s: return {"error": "subagent not found", "id": sid}
        h = s.agent.handler
        h.working['key_info'] = h.working.get('key_info', '') + f"\n[MASTER] {msg}"
        s.updated_at = time.time()
        return {"id": sid, "status": "keyinfo_injected"}        

pool = SubagentPool()

READMES = {
"api": f"""\
Conductor API\tBase: http://{HOST}:{PORT}

POST /chat\tbody: {{"msg": "..."}}\t给用户发消息
POST /subagent\tbody: {{"prompt": "..."}}\t启动新subagent，返回 {{"id": "xxx"}}
POST /approval\tbody: {{"prompt": "...", "source": "..."}}\t推一条待批任务到前端(后端不存)，用户同意则直接派发为subagent
POST /subagent/{{id}}\tbody: {{"action": "keyinfo", "msg": "..."}}\t注入key_info（agent下轮可见）
POST /subagent/{{id}}\tbody: {{"action": "input", "msg": "..."}}\t开新一轮任务（agent停下后追加）
POST /subagent/{{id}}\tbody: {{"action": "stop"}}\t中断执行但保留（可继续input/reply）
GET /chat?last=N\t返回最近N条对话（默认20）
GET /subagent\t返回 {{"items": [...]}}\t查看所有subagent状态
GET /subagent/{{id}}?max_len=N\t返回单个subagent详情，reply经清洗后截取尾部max_len字（默认5000）。仅在摘要不够判断时使用
""",
"usermsg": """\
用户消息流程：
1. 结合记忆、上下文和用户偏好判断真实需求；不清楚/不能代劳时，用精简checklist一次性问用户。
2. 判断是新任务还是延续现有任务；优先复用已有stopped subagent（用input追加），只有确实无关的新任务才新建。
3. 分派前必须POST /chat告知用户：改写后的prompt + 分派方案（新建/复用哪个subagent）。
4. 执行分派，完成即停。危险操作（改源码/删数据/安全敏感）必须改成先让subagent出方案；你验收后POST /chat请用户确认，确认后才继续执行。""",
"subagent": """\
subagent完成流程：
1. 如果是IM采集subagent，按GET /readme/im进行而非本流程
2. 读subagent输出；若最后一条不足以判断，GET /subagent/{id}?max_len=3000 补足信息。
3. 预测用户是否满意；不满意就reply/keyinfo要求返工、修改、优化，继续监督，不急着报告。
4. 预计用户满意后，POST /chat给简洁交付报告。""",
"im": """\
IM采集subagent刚完成，你要审查其输出，把值得用户关注的内容转化成"可点击执行"的待批任务（approval）。
先读L2记忆中User相关，推荐的动作和措辞要符合用户画像。
要求：
1. 不要只凭采集摘要；重要事实要核实，需要判断时先派subagent补做必要调查，再下结论。
2. 不要推"去看看/研究一下"这种半成品。推荐必须是最后一步可直接执行的动作（发某段微信回复、回复某封邮件草稿、处理某PR、整理某文件等）。
3. POST /approval 推送，prompt里同时写清两部分：
   ① 奏折式报告给用户拍板：背景(什么事/来自谁) + 已核实(你做了哪些调查/关键事实) + 判断(为什么这样建议) + 风险。用户看完这段就能直接拍板，不用再去翻原消息。
   ② 用户同意后该执行的完整任务指令（approval通过会直接作为subagent的prompt派发，必须具体到可直接执行）。
4. 没有值得用户点击执行的动作就直接结束，不要打扰；尤其不要对执行回执/完成确认/纯闲聊报"无需关注"。
5. 判断标准：私聊默认重要，群聊除非@用户或与用户工作相关否则忽略。""",
}

class Conductor:
    LOG_MAX = 50

    def __init__(self):
        self.inbox: "queue.Queue[dict]" = queue.Queue()   # 收件箱：唯一对外接口
        self.agent: Optional[GenericAgent] = None
        self.started = False
        self.log: list = []   
        self._model_lock = threading.Lock()
        self._model_state: dict = {"configured": None, "effective": None,
                                   "fallbackReason": None, "current": None, "running": False}
        self._runner_thread = None

    def notify(self, event: dict): self.inbox.put(event)

    def _build_prompt(self, events: list) -> str:
        running, stopped = pool.counts()
        unread = sum(1 for m in chat_messages if m.get("role") == "user" and not m.get("read"))
        done_count = sum(1 for e in events if e.get("type") == "subagent_done")
        summary = f"subagents: {running} running, {stopped} stopped | {unread}条用户未读消息, {done_count}个subagent完成报告"
        summary += "".join(f"\n[IM信号] {e['source']} 有新消息（GET /im_prompt/{e['source']} 取采集prompt），尽量复用已有subagent" for e in events if e.get("type") == "im_signal")
        base = f"http://{HOST}:{PORT}"
        return f"""你是agent总管。用户只和你对话，你负责调度、验收、交付，目标是降低用户管理多个agent的负担。
API: {base}；先requests，GET /readme查用法，GET /chat读未读对话，GET /subagent看状态；POST /chat是唯一对用户说话方式。
流程文档按需读取: GET /readme/usermsg | GET /readme/subagent | GET /readme/im

铁律：
- 绝不亲自执行任务/探测环境；一切执行交给subagent。你只分析、派遣、审查、沟通。
- 每次唤醒只做最小必要动作（发消息/开subagent/reply/keyinfo/abort），做完立刻停，等待下次事件唤醒。
- 改写prompt时严禁添加用户未提及的假设、工具、前提条件。只能精炼/结构化用户原意，不能脑补，只能做很小的改写

原则：
- 信任subagent足够聪明，不要写具体步骤和容易探测的信息；能自己判断的自己判断，只在真正需要用户决策时打扰。
{summary}"""

    def _drain(self, dq: "queue.Queue", events: list) -> str:
        event_label = ",".join(e.get("type", "") for e in events) or "wake"
        cur_turn = None;  buf = ""

        def flush():
            nonlocal buf
            cleaned = clean_log_text(buf)
            if cleaned:
                item = {"id": short_id(), "ts": now_ms(), "event": event_label,
                        "turn": cur_turn, "text": cleaned}
                self.log.append(item)
                if len(self.log) > self.LOG_MAX: self.log.pop(0)
                schedule_broadcast({"type": "log", "item": item})
            buf = ""

        while True:
            item = dq.get()
            if "next" in item:
                t = item.get("turn")
                if cur_turn is None: cur_turn = t
                elif t != cur_turn:
                    flush(); cur_turn = t
                buf += item.get("next", "") or ""
            elif "done" in item:
                if cur_turn is None: cur_turn = item.get("turn")
                flush()
                print("Conductor task done")
                return

    def model_snapshot(self) -> dict:
        with self._model_lock:
            return dict(self._model_state)

    def _publish_model_state(self, state: dict, running: bool) -> None:
        snapshot = {**state, "running": bool(running)}
        with self._model_lock:
            self._model_state = snapshot
        schedule_broadcast({"type": "model", "model": snapshot})

    def _record_unavailable_model(self, events: list) -> None:
        item = {"id": short_id(), "ts": now_ms(),
                "event": ",".join(e.get("type", "") for e in events) or "wake",
                "turn": None,
                "text": "Conductor paused: no usable model profiles are configured; events are deferred."}
        self.log.append(item)
        if len(self.log) > self.LOG_MAX: self.log.pop(0)
        schedule_broadcast({"type": "log", "item": item})

    def _run(self):
        self.agent = GenericAgent()
        self.agent.inc_out = True
        self._runner_thread = start_agent_runner(self.agent, "conductor-agent")
        self.started = True
        while True:
            # Block until first event arrives
            first = self.inbox.get()
            self.inbox.task_done()
            # Short debounce: collect any additional events that arrived meanwhile
            time.sleep(0.3)
            events = [*deferred_events, first]
            deferred_events = []
            while not self.inbox.empty():
                try:
                    events.append(self.inbox.get_nowait())
                    self.inbox.task_done()
                except Exception:
                    break
            try:
                # 设置可能在进程存活期间变化；只在任务边界刷新，使 in-flight 任务保留原客户端
                model_state = _apply_desktop_model(self.agent)
                if model_state.get("effective") is None:
                    self._publish_model_state(model_state, running=False)
                    self._record_unavailable_model(events)
                    deferred_events = events
                    continue
                prompt = self._build_prompt(events)
                self._publish_model_state(model_state, running=True)
                try:
                    dq = self.agent.put_task(prompt, source="conductor")
                    self._drain(dq, events)
                finally:
                    self._publish_model_state(model_state, running=False)
            except Exception as e: print(f"Conductor error: {e}")

    def start(self):
        # 起线程前先做一次模型对齐，避免前端首次连接时状态为空
        threading.Thread(target=self._run, name="conductor-loop", daemon=True).start()


conductor = Conductor()

# ---- IM poller: 探测conductor_im_plugins/下各插件,信号变化→唤醒总管 ----
IM_DIR, IM_COOLDOWN = os.path.join(os.path.dirname(__file__), "conductor_im_plugins"), 300
IM_PROMPTS: Dict[str, str] = {}   # source -> 采集prompt（派采集subagent时按需取）

def im_poll_loop():
    import importlib.util
    mods, last_fire = {}, {}
    for f in (x for x in os.listdir(IM_DIR) if x.endswith(".py") and not x.startswith("_")):
        spec = importlib.util.spec_from_file_location(f[:-3], os.path.join(IM_DIR, f))
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        if hasattr(m, "check"):
            mods[f[:-3]] = m
            IM_PROMPTS[f[:-3]] = getattr(m, "PROMPT", "")
    last_check = {}
    while True:
        time.sleep(10)
        for name, m in mods.items():
            now = time.time()
            if now - last_check.get(name, 0) < getattr(m, "INTERVAL", 30): continue
            last_check[name] = now
            try:
                if not m.check() or now - last_fire.get(name, 0) < IM_COOLDOWN: continue
            except Exception: continue
            last_fire[name] = now
            conductor.notify({"type": "im_signal", "source": name})

@app.get("/")
def index(): return FileResponse(HTML_PATH)

@app.get("/readme")
def readme(): return PlainTextResponse(READMES["api"])

@app.get("/readme/{topic}")
def readme_topic(topic: str):
    if topic not in READMES:
        return PlainTextResponse(f"Unknown topic: {topic}. Available: {', '.join(READMES.keys())}", status_code=404)
    return PlainTextResponse(READMES[topic])

@app.get("/im_prompt/{source}")
def im_prompt(source: str):
    if source not in IM_PROMPTS:
        return PlainTextResponse(f"Unknown source: {source}. Available: {', '.join(IM_PROMPTS.keys())}", status_code=404)
    return PlainTextResponse(IM_PROMPTS[source])

@app.get("/llms")
def api_llms():
    if not conductor.agent: return {"cur": -1, "items": []}
    return {"cur": _selected_conductor_llm_no(conductor.agent),
            "items": conductor.agent.list_llms(), "model": conductor.model_snapshot()}


@app.post("/llm")
def api_llm(body: dict):
    if not conductor.agent: return JSONResponse({"error": "conductor not started"}, status_code=503)
    try:
        no = _set_conductor_llm_no(conductor.agent, body.get("no"))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    schedule_broadcast({"type": "model_selected", "llm": no})
    return {"ok": True, "llm": no}


@app.get("/subagent")
def list_subagents(): return {"items": pool.snapshot()}

@app.get("/subagent/{sid}")
def get_subagent(sid: str, max_len: int = 5000):
    s = pool.get(sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    cleaned = clean_log_text(s.reply or "")
    return {"id": s.id, "prompt": s.prompt, "status": s.status,
            "reply": cleaned[-max_len:] if len(cleaned) > max_len else cleaned,
            "created_at": s.created_at, "updated_at": s.updated_at}

INSTR_DISPATCHED = "Task received. I'll handle THIS TASK from here. You MUST to do other task or end your reply."

@app.post("/subagent")
def api_start_subagent(body: StartSubagentIn):
    result = pool.start_subagent(body.prompt)
    result["instruction"] = INSTR_DISPATCHED
    return result

@app.post("/subagent/{sid}")
def api_subagent_action(sid: str, body: SubagentActionIn):
    s = pool.get(sid)
    if not s: return JSONResponse({"error": "subagent not found", "id": sid}, status_code=404)
    action = body.action.lower().strip()
    if action == "keyinfo":
        result = pool.keyinfo_subagent(sid, body.msg)
        result["instruction"] = "Received. I'll incorporate this. You MUST to do other task or end your reply."
        return result
    if action in ("input", "reply", "append", "message", "msg"):
        result = pool.input_subagent(sid, body.msg)
        result["instruction"] = INSTR_DISPATCHED
        return result
    if action in ("abort", "stop"):
        s.agent.abort()
        s.status = "stopped"
        s.updated_at = time.time()
        push_cards()
        return {"id": sid, "status": "stopped"}
    return JSONResponse({"error": f"unknown action: {body.action}"}, status_code=400)

@app.get("/chat")
def api_get_chat(last: int = 20):
    for m in chat_messages:
        if m.get("role") == "user" and not m.get("read"): m["read"] = True
    schedule_broadcast({"type": "chat_read"})
    return {"items": chat_messages[-last:]}

@app.post("/chat")
def api_chat(body: ChatIn):
    return add_chat(body.msg, role=body.role)

@app.post("/approval")
def api_approval(body: ApprovalIn):
    schedule_broadcast({"type": "approval", "item": {"id": short_id(), "prompt": body.prompt, "source": body.source}})
    return {"ok": True}

@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        await ws.send_json({"type": "hello", "subagents": pool.snapshot(), "chat": chat_messages, "log": conductor.log,
                            "model": conductor.model_snapshot(),
                            "llms": conductor.agent.list_llms() if conductor.agent else [],
                            "llm": _selected_conductor_llm_no(conductor.agent) if conductor.agent else -1})
        while True:
            data = await ws.receive_json()
            if "llm" in data:
                # 只持久化绑定；运行中的任务不受影响，下个任务边界生效
                try:
                    no = _set_conductor_llm_no(conductor.agent, data.get("llm"))
                    schedule_broadcast({"type": "model_selected", "llm": no})
                except Exception as e:
                    schedule_broadcast({"type": "model_error", "error": str(e),
                                        "llm": _selected_conductor_llm_no(conductor.agent)})
                continue
            msg = (data.get("msg") or "").strip()
            if not msg: continue
            add_chat(msg, role="user")
            conductor.notify({"type": "user_message", "msg": msg})
    except WebSocketDisconnect: pass
    finally: ws_clients.discard(ws)

if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    uvicorn.run("conductor:app", host=HOST, port=PORT, reload=False)
