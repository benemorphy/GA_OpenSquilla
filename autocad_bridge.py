# -*- coding: utf-8 -*-
"""autocad_bridge.py — GA 到 AutoCAD 2014 的桥接器
基于 COM Automation (AutoCAD.Application.19)
功能: 连接/启动/文档管理/实体绘制(线/圆/文本)/命令发送/读取
用法: from autocad_bridge import AcadBridge; b = AcadBridge(); b.draw_line(...)
"""
import os, subprocess, time
import win32com.client
import pythoncom

ACAD_EXE = r"D:\Program Files\Autodesk\AutoCAD 2014\acad.exe"
PROGID = "AutoCAD.Application.19"

RPC_E_CALL_REJECTED = -2147418111  # 0x80010001 被呼叫方忙

def _retry(fn, retries=10, delay=0.8, label=""):
    """AutoCAD COM 忙时重试 (RPC_E_CALL_REJECTED / 被呼叫方拒绝接收呼叫)"""
    import pywintypes
    last = None
    for i in range(retries):
        try:
            return fn()
        except pywintypes.com_error as e:
            last = e
            if getattr(e, "hr", None) == RPC_E_CALL_REJECTED or "拒绝" in str(e) or "busy" in str(e).lower():
                time.sleep(delay)
                continue
            raise
    raise last

class AcadBridge:
    def __init__(self, launch=True, visible=True):
        """连接 AutoCAD; 若未运行且 launch=True 则拉起 acad.exe"""
        self.app = None
        pythoncom.CoInitialize()
        try:
            self.app = win32com.client.Dispatch(PROGID)
        except Exception:
            if not launch:
                raise RuntimeError("AutoCAD 未运行且 launch=False")
            self._launch()
            self._wait_ready(120)
            self.app = win32com.client.Dispatch(PROGID)
        try:
            self.app.Visible = visible
        except Exception:
            pass

    def _launch(self):
        subprocess.Popen([ACAD_EXE], creationflags=subprocess.CREATE_NO_WINDOW)
        print("AutoCAD 启动中...", flush=True)

    def _wait_ready(self, timeout=120):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                a = win32com.client.Dispatch(PROGID)
                _ = a.Version
                return
            except Exception:
                time.sleep(3)
        raise TimeoutError("AutoCAD 启动超时")

    # ===== 文档 =====
    @property
    def doc(self):
        return _retry(lambda: self.app.ActiveDocument, label="ActiveDocument")

    def new_doc(self):
        return _retry(lambda: self.app.Documents.Add(), label="NewDoc")

    def open_doc(self, path):
        return _retry(lambda: self.app.Documents.Open(path), retries=20, delay=1.0, label="OpenDoc")

    def save(self, path=None):
        if path:
            self.doc.SaveAs(path)
        else:
            self.doc.Save()

    # ===== 实体绘制 =====
    def draw_line(self, x1, y1, x2, y2, layer=None):
        """画线段, 返回实体"""
        ms = self.doc.ModelSpace
        ln = ms.AddLine(
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x1, y1, 0.0]),
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x2, y2, 0.0]))
        if layer:
            ln.Layer = layer
        return ln

    def draw_circle(self, cx, cy, radius):
        ms = self.doc.ModelSpace
        return ms.AddCircle(
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [cx, cy, 0.0]),
            radius)

    def draw_text(self, text, x, y, height=2.5):
        ms = self.doc.ModelSpace
        return ms.AddText(text,
            win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [x, y, 0.0]),
            height)

    def count_entities(self):
        return self.doc.ModelSpace.Count

    # ===== 命令 =====
    def send_command(self, cmd):
        """发送 AutoCAD 命令行命令, cmd 需以 \\n 结束"""
        self.doc.SendCommand(cmd)

    def zoom_extents(self):
        self.send_command("ZOOM\nE\n")

    # ===== 信息 =====
    def version(self):
        return self.app.Version

    def doc_name(self):
        return self.doc.Name

if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    b = AcadBridge()
    print(f"连接OK version={b.version()} doc={b.doc_name()}")
    if mode == "test":
        b.new_doc()
        b.draw_line(0, 0, 100, 50)
        b.draw_circle(50, 50, 20)
        b.draw_text("GA-Bridge", 10, 60)
        b.zoom_extents()
        print(f"实体数: {b.count_entities()}")
