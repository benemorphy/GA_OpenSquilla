"""Workspace 命令的共享逻辑(tuiapp_v2 / tui_v3 复用)。

设计要点(详见对话设计稿):
  * **兼容旧入口** `plugins/project_mode.py` 与 `memory/project_mode_sop.md` 的 pid 锚。
    前端在
    `<repo>/temp/projects/<name>` 建一个指向用户真实绝对路径的目录联接(junction),
    并可按需写激活锚 `<repo>/temp/.active_project.<pid>`。project_mode 插件
    照常每轮注入 L1,并把 project_memory.md / 产物经 junction 写进真实仓库根
    (与 Claude Code 在仓库根放 CLAUDE.md 同理,已接受)。
  * **路径基准必须与插件一致**:插件的 `_TEMP` 是基于其 `__file__` 的 `<repo>/temp`
    绝对路径(非 cwd)。本模块也从自身 `__file__` 推 `<repo>/temp`(frontends/ 的上一级
    即 repo 根),两边独立计算但结果一致,互不 import。
  * **pid 语义**:插件读 `os.getpid()`(GA 进程)。前端就跑在 GA 进程里,写锚同样用
    `os.getpid()`(不是 SOP 里 code_run 子进程用的 getppid)。
  * **命名** `name = f"{basename}-{hash8}"`,hash8 = blake2b(规范化绝对路径)[:8]。
    同一 workspace 恒定同名(幂等复用);hash 后缀又让 junction 名不与其它 UI 人工命名的
    普通项目目录相撞。
  * **junction 安全**:检测用 reparse 属性(`os.path.islink` 对 junction 返回 False!);
    删除用 `os.rmdir`,**绝不 rmtree**(会击穿删真实文件)。cleanup 只动确认是 junction
    且悬空/未注册的条目,真实目录(其它 UI 的普通项目)一律不碰。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from typing import Optional


# --------------------------------------------------------------------------- #
# 路径基准(与 plugins/project_mode.py 的 _TEMP 保持一致)
# --------------------------------------------------------------------------- #
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _temp_root() -> str:
    return os.path.join(_REPO_ROOT, "temp")


def _projects_root() -> str:
    return os.path.join(_temp_root(), "projects")


def _anchor_path() -> str:
    """激活锚,pid 键控,与插件 `_ANCHOR` 同。"""
    return os.path.join(_temp_root(), f".active_project.{os.getpid()}")


def _registry_path() -> str:
    return os.path.join(_temp_root(), "workspaces.json")


_REGISTRY_VERSION = 1


# --------------------------------------------------------------------------- #
# 命名
# --------------------------------------------------------------------------- #
def workspace_name(real_path: str) -> str:
    """归一命名: `basename-hash8`。"""
    norm = os.path.normcase(os.path.realpath(real_path))
    h = hashlib.blake2b(norm.encode()).hexdigest()[:8]
    return f"{os.path.basename(norm)}-{h}"


# --------------------------------------------------------------------------- #
# junction / symlink 工具
# --------------------------------------------------------------------------- #
def _is_reparse_point(path: str) -> bool:
    """Windows: 用 fsutil 或 stat 检查 reparse 属性(覆盖 junction/symlink)。
    稳妥检测: os.stat + stat.S_IFMT。"""
    try:
        st = os.stat(path)
        return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) if os.name == 'nt' else os.path.islink(path)
    except OSError:
        return False


def is_dir_link(path: str) -> bool:
    """路径本身是 directory junction / symlink 吗？
    Windows junction: os.path.islink 返回 False, 需 reparse 检测。
    POSIX symlink: os.path.islink 返回 True。"""
    if not os.path.exists(path):
        return False
    if not os.path.isdir(path):
        return False
    # os.path.islink 对 Windows junction 返回 False, 但 pathlib.is_symlink
    # 用 GetFileAttributes 对 reparse 点返回 True, 但 os.path.islink 可能
    # 仍为 False。统一用 reparse 检测。
    return _is_reparse_point(path)


def create_dir_link(source: str, link: str) -> bool:
    """创建目录联接。Windows 用 mklink /J, POSIX 用 ln -s。
    失败返回 False, 并在 stderr 写原因。"""
    try:
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.name == 'nt':
            # mklink /J 要求 link 不存在
            if os.path.exists(link):
                return False
            # 用 cmd /c mklink /J
            result = subprocess.run(
                ['cmd', '/c', 'mklink', '/J', link, source],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                sys.stderr.write(f"[workspace] mklink failed: {result.stderr}\n")
                return False
        else:
            os.symlink(source, link, target_is_directory=True)
        return True
    except OSError as e:
        sys.stderr.write(f"[workspace] create link {link} -> {source}: {e}\n")
        return False


def link_target(path: str) -> Optional[str]:
    """读链接目标;清洗 Windows 的 \\??\\ / \\\\?\\ 前缀。失败返回 None。"""
    try:
        t = os.readlink(path)
    except OSError:
        return None
    for pre in ("\\??\\", "\\\\?\\"):
        if t.startswith(pre):
            t = t[len(pre):]
            break
    return t


def remove_dir_link(path: str) -> bool:
    """只摘掉链接本身,绝不递归删目标。Windows junction / 符号链接目录用 os.rmdir,
    POSIX symlink 用 os.unlink。**调用前务必 is_dir_link 确认。**"""
    try:
        if os.name == "nt":
            os.rmdir(path)
        else:
            os.unlink(path)
        return True
    except OSError as e:
        sys.stderr.write(f"[workspace] remove link {path} failed: {e}\n")
        return False


# --------------------------------------------------------------------------- #
# 注册表 temp/workspaces.json(本功能私有;v2/v3 可能并发 -> 原子写)
# --------------------------------------------------------------------------- #
def registry_load() -> dict:
    try:
        with open(_registry_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("version") == _REGISTRY_VERSION:
            items = data.get("items")
            if isinstance(items, dict):
                return items
    except (OSError, ValueError):
        pass
    return {}


def _registry_save(items: dict) -> None:
    path = _registry_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": _REGISTRY_VERSION, "items": items},
                      fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError as e:
        sys.stderr.write(f"[workspace] registry save failed: {e}\n")


def _registry_add(name: str, real_path: str) -> None:
    items = registry_load()
    items[name] = {
        "real_path": os.path.realpath(real_path),
        "created": time.time(),
    }
    _registry_save(items)


def registry_remove(name: str) -> bool:
    items = registry_load()
    if name in items:
        del items[name]
        _registry_save(items)
        return True
    return False


# --------------------------------------------------------------------------- #
# 核心操作
# --------------------------------------------------------------------------- #
def add(repo_abs_path: str) -> str:
    """注册一个 workspace,建 junction,写锚。返回 display name。"""
    name = workspace_name(repo_abs_path)
    link = os.path.join(_projects_root(), name)
    if not os.path.exists(link):
        ok = create_dir_link(repo_abs_path, link)
        if not ok:
            return f"创建 workspace 链接失败: {link} -> {repo_abs_path}"
    _registry_add(name, repo_abs_path)
    # 写激活锚
    try:
        with open(_anchor_path(), "w") as fh:
            fh.write(repo_abs_path)
    except OSError as e:
        sys.stderr.write(f"[workspace] write anchor failed: {e}\n")
    return name


def remove(name: str) -> str:
    """取消注册,删 junction。"""
    items = registry_load()
    if name not in items:
        return f"workspace {name} 不存在"
    link = os.path.join(_projects_root(), name)
    if os.path.exists(link) and is_dir_link(link):
        remove_dir_link(link)
    registry_remove(name)
    # 若当前锚是这个 workspace,清掉
    anchor = _anchor_path()
    if os.path.exists(anchor):
        try:
            with open(anchor) as fh:
                cur = fh.read().strip()
            if cur and workspace_name(cur) == name:
                os.remove(anchor)
        except OSError:
            pass
    return f"已移除 workspace: {name}"


def list_all() -> str:
    """列出所有注册的 workspace。"""
    items = registry_load()
    if not items:
        return "无已注册 workspace"
    lines = []
    active = active_workspace()
    for name, info in sorted(items.items()):
        mark = " *" if active and name == workspace_name(active) else ""
        lines.append(f"  {name}{mark}  ->  {info.get('real_path', '?')}")
    return "\n".join(lines)


def active_workspace() -> Optional[str]:
    """返回当前激活锚中的真实路径,若存在且有效。"""
    anchor = _anchor_path()
    if not os.path.exists(anchor):
        return None
    try:
        with open(anchor) as fh:
            raw = fh.read().strip()
        return raw if raw and os.path.isdir(raw) else None
    except OSError:
        return None


def cleanup_unregistered() -> str:
    """清理 projects/ 下未在注册表中且为 junction 的悬浮条目。"""
    proot = _projects_root()
    if not os.path.isdir(proot):
        return "projects 目录不存在,无需清理"
    items = registry_load()
    cleaned = []
    for entry in os.listdir(proot):
        path = os.path.join(proot, entry)
        if entry in items:
            continue
        if is_dir_link(path):
            tgt = link_target(path)
            remove_dir_link(path)
            cleaned.append(f"  移除悬空 junction: {entry} -> {tgt}")
    if cleaned:
        return "清理了以下悬空 junction:\n" + "\n".join(cleaned)
    return "无悬空 junction 需要清理"


# --------------------------------------------------------------------------- #
# filesystem 路径字面串中的 workspace 引用解析
# --------------------------------------------------------------------------- #
_WORKSPACE_REF_RE = re.compile(r'@workspace[/\\]([^\s"\']+)')


def resolve_path(text: str) -> str:
    """把文本中的 `@workspace/...` 引用替换为真实路径。
    如 `@workspace/src/main.py` -> `C:/real/project/src/main.py`。"""
    active = active_workspace()
    if not active:
        return text
    def _repl(m):
        return os.path.join(active, m.group(1))
    return _WORKSPACE_REF_RE.sub(_repl, text)