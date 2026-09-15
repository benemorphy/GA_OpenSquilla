# Streamlit 应用开发与无头验证 SOP

**触发**：用户要求"py 写一段程序 + 参数面板/可视化"；或需验证本地 Web UI 真的能跑。

## 1. 技术选型（本机已验证）
- 面板首选 **Streamlit**（GA venv 已装 1.57）；无 panel / PyQt5 / PySide6
- tkinter 存在但历史记录显示 GUI 环境不可用（无窗口任务），**不要选 Tk 做交付物**
- 结构：`xxx_core.py`（纯计算+绘图，无 UI 依赖，可 unittest/自检）+ `xxx_app.py`（Streamlit 面板，只做参数绑定与展示）
- 交付前必修：`python -m py_compile app.py` → AppTest 自测 → 实启服务 + 真浏览器截图

## 2. 三层验证（缺一不可）
```python
# ① AppTest 无头逻辑验证（秒级，覆盖所有分支）
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=180); at.run()
at.sidebar.radio[0].set_value("贝塞尔曲线").run()
assert not at.exception          # 关键断言
# ② 实启服务
# ③ playwright 真浏览器截图（见 §3）
```
AppTest 也支持：`at.markdown / at.dataframe / at.tabs / at.button / at.sidebar.slider[0].set_value(x)`。

## 3. playwright 截图（本机铁律）
- **没有内置浏览器**（`%LOCALAPPDATA%\ms-playwright` 只有 ffmpeg/winldd），`launch()` 会报 Executable doesn't exist
- 正确做法：`pw.chromium.launch(channel="chrome", headless=True)` 复用系统 Chrome
- 截图后用 `PIL` 统计非白像素比例（<1% 说明页面空白）确认真的渲染了
- 页面组件探针（一次性拿全）：`canvas / [data-testid="stImage"] img / [data-testid="stDataFrame"] / .stSlider / .katex / [role="tab"] / [data-testid="stException"]`
- 图片更新验证：比较 `img.src` 前后是否变化（Streamlit 每次 rerun 会换 src）

## 4. 交互测试坑
- Streamlit 滑块**不是原生 `<input>`**：`.stSlider input` 会超时找不到
- 正确：`page.locator('[role="slider"]')` 读 `aria-valuenow`，`.click()` 后 `keyboard.press("ArrowRight")` × N
- 侧边栏截图：`page.locator("section[data-testid='stSidebar']").screenshot(...)`

## 5. 生命周期坑
- 服务启动：`Popen([...,"-m","streamlit","run","app.py","--server.port","8511","--server.headless","true"])` + 轮询 `/_stcore/health`（返回 `ok`）
- **stdout 重定向的日志文件在进程退出前无法删除**（WinError 32）→ 先 `taskkill /F /PID <精确PID>`，再删日志
- 重启验证默认端口时注意：GA 自身 frontends/stapp.py 也跑 streamlit（端口不同），不要误杀
- 关掉服务后再清 `__pycache__` 与临时 `_*.log/_*.txt/_apptest*.py`

## 6. 中文字符串坑（本次踩到 2 次）
- 中文文案里嵌 ASCII 双引号会截断 Python 字符串 → 语法错误。**统一用中文引号「」或 “”**
- 批量替换时按"每行引号计数"处理，并保证首个/末个引号是字符串定界符（本次第一版替换把定界符也换了，需要二次修正）
- matplotlib 中文：`Microsoft YaHei` 可用；公式用 mathtext（不支持 `\mathbb` / `\begin{pmatrix}`）
- 校验字体缺失：`warnings.simplefilter("error"); fig.canvas.draw()` —— 缺字形会抛 warning

## 7. Windows 启动 .bat 坑（2026-09-15 实测定位）
- **用户双击时 PATH 与终端不同**：双击的 cmd 不含 venv 路径，`python` 会命中 `C:\Users\<u>\AppData\Local\Microsoft\WindowsApps\python.exe`（Microsoft Store 别名）→ 报 `Python was not found; ... App execution aliases`。**别在 .bat 里裸写 `python`**
- 正确做法：用 `call :try "<绝对路径解释器>"` 逐个探测 `"%~1" -c "import streamlit" >nul 2>nul`，`if not errorlevel 1 set "PY=%~1"`，找不到再退回 `py -3.12` / `python`；探测用 **goto 结构**，不要用 `if (...)` 多行块
- **`echo` 文本里的 `)` 会提前闭合 `if (...)` 块**：`if errorlevel 1 ( echo 1) 指定解释器 ... )` → 报 `was unexpected at this time` 且**整个脚本静默走错分支**（表现为"探测不到解释器"）
- **中文注释在 GBK 环境（社区版 cmd 默认 936）会乱码并干扰解析**：即使 `chcp 65001` 也可能出问题 → 交付给用户的 .bat **只用 ASCII + 英文提示**，不要中文
- 换行必须是纯 CRLF：用 Python 写 bat 时 `open(p,"w",encoding="ascii",newline="\r\n")`，若先用 `\r\n` 字符串再 `.replace("\n","\r\n")` 会得到 `\r\r\n`（cmd 一般能忍，但要检查）
- 自检方式：`env["PATH"]=r"C:\Windows\system32;C:\Windows"` 下 `subprocess.Popen(["cmd","/c","run.bat","8599"])` 实跑，确认端口监听 + 输出里打印出选中的解释器

## 验证于
- 2026-09-15 `refer_docs/线性代数学习笔记/bernstein/`（伯恩斯坦多项式 Streamlit 面板：4 模式 + 性质数值验证 + CSV/PNG 导出，AppTest 四模式 0 异常，Chrome 截图渲染正常）
