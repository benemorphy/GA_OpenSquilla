import webview, threading, subprocess, sys, time, os, ctypes, atexit, socket, random, json

WINDOW_WIDTH, WINDOW_HEIGHT, RIGHT_PADDING, TOP_PADDING = 1200, 900, 0, 50

script_dir = os.path.dirname(os.path.abspath(__file__))
frontends_dir = os.path.join(script_dir, "frontends")

def find_free_port(lo=18501, hi=18599):
    ports = list(range(lo, hi+1)); random.shuffle(ports)
    for p in ports:
        try: s = socket.socket(); s.bind(('127.0.0.1', p)); s.close(); return p
        except OSError: continue
    raise RuntimeError(f'No free port in {lo}-{hi}')

def get_screen_width():
    try: return ctypes.windll.user32.GetSystemMetrics(0)
    except: return 1920

def start_streamlit(port):
    global proc
    cmd = [sys.executable, "-m", "streamlit", "run", os.path.join(frontends_dir, "stapp.py"), "--server.port", str(port), "--server.address", "localhost", "--server.headless", "true", "--client.toolbarMode", "viewer"]
    proc = subprocess.Popen(cmd)
    atexit.register(proc.kill)

def inject(text):
    window.evaluate_js(f"""
        const textarea = document.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (textarea) {{
            // 1. 用原生 setter 设置值（绕过 React）
            const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
            nativeTextAreaValueSetter.call(textarea, {json.dumps(text)});
            // 2. 触发 React 的 input 事件
            textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
            // 3. 触发 change 事件（有些组件需要）
            textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
            // 4. 延迟提交
            setTimeout(() => {{
                const btn = document.querySelector('[data-testid="stChatInputSubmitButton"]');
                if (btn) {{btn.click();console.log('Submitted:', {json.dumps(text)});}}
            }}, 200);
        }}""")

def get_last_reply_time():
    last = window.evaluate_js("""
        const el = document.getElementById('last-reply-time');
        el ? parseInt(el.textContent) : 0;
    """) or 0
    return last or int(time.time())

PASTE_HOOK_JS = """if (!window._pasteHooked) { window._pasteHooked = true;
    document.addEventListener('paste', e => {
        const items = e.clipboardData?.items; if (!items) return;
        let t = null, hasText = false;
        for (const item of items) {
            if (item.kind === 'string' && (item.type === 'text/plain' || item.type === 'text/html')) hasText = true;
            if (item.kind === 'file') { t = item.type.startsWith('image/') ? 'image in clipboard, ' : 'file in clipboard, '; }
        }
        if (!t || hasText) return;
        e.preventDefault(); e.stopImmediatePropagation();
        const el = document.querySelector('textarea[data-testid="stChatInputTextArea"]') || document.activeElement;
        if (el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT')) {
            const s = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            s.call(el, el.value + t); el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }, true);
}"""

def idle_monitor():
    global window
    last_trigger_time = 0
    while True:
        time.sleep(5)
        try:
            if 'window' not in globals() or window is None:
                continue
            window.evaluate_js(PASTE_HOOK_JS)
            now = time.time()
            if now - last_trigger_time < 120: continue
            last_reply = get_last_reply_time()
            if now - last_reply > 1800:
                print('[Idle Monitor] Detected idle state, injecting task...')
                inject("[AUTO]🤖 用户已经离开超过30分钟，作为自主智能体，请阅读自动化sop，执行自动任务。")
                last_trigger_time = now
        except Exception as e:
            print(f'[Idle Monitor] Error: {e}')

MUTEX_NAMES = [
    "Global\\GenericAgent_LaunchMutex",
    "GenericAgent_LaunchMutex",
]
LOCK_FILE = os.path.join(script_dir, ".launch.lock")

def _pid_exists(pid):
    """跨平台PID存在性检查"""
    try:
        if os.name == 'nt':
            handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError, AttributeError):
        return False

def _check_lock_file():
    """PID锁文件：跨Python环境防重复启动"""
    if not os.path.exists(LOCK_FILE):
        return None
    try:
        with open(LOCK_FILE) as f:
            old_pid = int(f.read().strip())
        if old_pid == os.getpid():
            return None  # 自身
        if _pid_exists(old_pid):
            return old_pid  # 其他实例存活
        # PID不存在，锁文件过期
        return None
    except (ValueError, OSError):
        return None

def ensure_single_instance():
    """防重复启动：Mutex名回退 + PID锁文件 + 竞态退避"""
    import random as _random
    time.sleep(_random.uniform(0, 0.3))  # 竞态退避
    
    # 1) PID锁文件辅助（跨venv/uv可靠）
    old_pid = _check_lock_file()
    if old_pid:
        print(f'[Launch] Another instance (PID {old_pid}) running via lock file, exiting.')
        sys.exit(0)
    # 写入当前PID
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    def _cleanup_lock():
        try:
            if os.path.exists(LOCK_FILE):
                with open(LOCK_FILE) as f:
                    cur = f.read().strip()
                if cur == str(os.getpid()):
                    os.remove(LOCK_FILE)
        except: pass
    atexit.register(_cleanup_lock)
    
    # 2) Windows Mutex（带名回退，某些受限环境Global\无效）
    for mutex_name in MUTEX_NAMES:
        try:
            ctypes.windll.kernel32.SetLastError(0)
            mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
            err = ctypes.windll.kernel32.GetLastError()
            
            if err == 183:  # ERROR_ALREADY_EXISTS
                print(f'[Launch] Another instance running (mutex: {mutex_name})')
                if mutex:
                    ctypes.windll.kernel32.CloseHandle(mutex)
                sys.exit(0)
            
            if mutex:
                print(f'[Launch] Instance lock acquired: {mutex_name}')
                atexit.register(lambda h=mutex: ctypes.windll.kernel32.CloseHandle(h))
                return  # 成功
        except Exception as e:
            print(f'[Launch] Mutex error on {mutex_name}: {e}')
            continue
    
    print('[Launch] All mutex names failed, lock file only')

def wait_for_port(port, timeout=30):
    """等待streamlit实际监听端口后再打开窗口"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.socket(); s.settimeout(1)
            s.connect(('127.0.0.1', port)); s.close()
            return True
        except:
            time.sleep(0.3)
    return False

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('port', nargs='?', default='0'); 
    parser.add_argument('--tg', action='store_true', help='启动 Telegram Bot'); 
    parser.add_argument('--qq', action='store_true', help='启动 QQ Bot');
    parser.add_argument('--feishu', '--fs', dest='feishu', action='store_true', help='启动 Feishu Bot');
    parser.add_argument('--wechat', '--wx', dest='wechat', action='store_true', help='启动 WeChat Bot');
    parser.add_argument('--wecom', action='store_true', help='启动 WeCom Bot');
    parser.add_argument('--dingtalk', '--dt', dest='dingtalk', action='store_true', help='启动 DingTalk Bot');
    parser.add_argument('--sched', action='store_true', help='启动计划任务调度器')
    parser.add_argument('--llm_no', type=int, default=0, help='LLM编号')
    args = parser.parse_args()
    ensure_single_instance()
    port = str(find_free_port()) if args.port == '0' else args.port
    print(f'[Launch] Using port {port}')
    threading.Thread(target=start_streamlit, args=(port,), daemon=True).start()

    if args.tg:
        tgproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "tgapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(tgproc.kill)
        print('[Launch] Telegram Bot started')
    else: print('[Launch] Telegram Bot not enabled (use --tg to start)')

    if args.qq:
        qqproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "qqapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(qqproc.kill)
        print('[Launch] QQ Bot started')
    else: print('[Launch] QQ Bot not enabled (use --qq to start)')

    if args.feishu:
        fsproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "fsapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(fsproc.kill)
        print('[Launch] Feishu Bot started')
    else: print('[Launch] Feishu Bot not enabled (use --feishu to start)')

    if args.wechat:
        wxproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, 'wechatapp.py')], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(wxproc.kill)
        print('[Launch] WeChat Bot started')
    else: print('[Launch] WeChat Bot not enabled (use --wechat to start)')

    if args.wecom:
        wcproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "wecomapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(wcproc.kill)
        print('[Launch] WeCom Bot started')
    else: print('[Launch] WeCom Bot not enabled (use --wecom to start)')

    if args.dingtalk:
        dtproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "dingtalkapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(dtproc.kill)
        print('[Launch] DingTalk Bot started')
    else: print('[Launch] DingTalk Bot not enabled (use --dingtalk to start)')
    
    if args.sched:
        scheduler_proc = subprocess.Popen([sys.executable, os.path.join(script_dir, "agentmain.py"), "--reflect", os.path.join(script_dir, "reflect", "scheduler.py"), "--llm_no", str(args.llm_no)], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(scheduler_proc.kill)
        print('[Launch] Task Scheduler started (duplicate prevented by scheduler port lock)')
    else: print('[Launch] Task Scheduler not enabled (--sched)')

    monitor_thread = threading.Thread(target=idle_monitor, daemon=True)
    monitor_thread.start()
    if os.name == 'nt':
        screen_width = get_screen_width()
        x_pos = screen_width - WINDOW_WIDTH - RIGHT_PADDING
    else: x_pos = 100
    print(f'[Launch] Waiting for streamlit on port {port}...')
    if not wait_for_port(int(port)):
        print(f'[Launch] Warning: streamlit did not start within timeout, continuing anyway')
    window = webview.create_window(
        title='GenericAgent', url=f'http://localhost:{port}',
        width=WINDOW_WIDTH, height=WINDOW_HEIGHT, x=x_pos, y=TOP_PADDING,
        resizable=True, text_select=True)
    webview.start()
