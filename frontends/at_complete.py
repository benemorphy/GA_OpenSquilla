"""@ file completion — shared UI-less logic for tui_v2 / tui_v3.

File index (os.scandir, cached per root) + fuzzy match + @token detection +
insert text. No UI deps; each front-end renders candidates its own way and
calls candidates_for(query, root). Index root is the front-end's choice
(session workspace, else CWD). Submit-time: completion-only does NOT read
content, but absolutize_mentions() rewrites @relative -> @absolute so the
agent's file_read (relative to its own cwd) can locate the file. The
content-injecting auto-read variant lives in
temp/plan_v2_at_mention/autoread_version.py.
"""

import os
import re
import threading

# ---------------------------------------------------------------- index

_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", ".idea", ".vscode", "target", ".cache", ".eggs",
    "model_responses",   # GA 会话日志（上千个 .txt），未绑时根=temp 会淹没 @ 候选
}
_IGNORE_EXT = {".pyc", ".pyo", ".so", ".o", ".class", ".lock", ".dll", ".exe"}
_MAX_FILES = 50_000          # 超大目录宁缺毋卡：到上限就停


def scan_files(root: str, max_files: int = _MAX_FILES) -> list[str]:
    """Collect relative file paths under root, '/'-normalized.

    os.scandir over os.walk: one syscall yields is_dir without an extra
    stat per entry. Dotted dirs are skipped wholesale (.git, .venv...).
    """
    out: list[str] = []
    stack = [root]
    while stack and len(out) < max_files:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name not in _IGNORE_DIRS and not e.name.startswith("."):
                                stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            ext = os.path.splitext(e.name)[1].lower()
                            if ext not in _IGNORE_EXT:
                                out.append(os.path.relpath(e.path, root).replace("\\", "/"))
                    except OSError:
                        pass
        except PermissionError:
            pass
        except OSError:
            pass
    return out


# ---------------------------------------------------------------- cache

_cache: dict[str, tuple[list[str], float]] = {}          # root -> (files, mtime)
_cache_lock = threading.Lock()
_CACHE_TTL = 5.0                                          # seconds


def _is_index_stale(root: str) -> bool:
    """Check if root's mtime has changed since last cache write."""
    try:
        cur = os.path.getmtime(root)
    except OSError:
        return True
    with _cache_lock:
        entry = _cache.get(root)
        return entry is None or entry[1] < cur


def cached_scan(root: str) -> list[str]:
    """scan_files with a simple mtime-based cache."""
    if not _is_index_stale(root):
        with _cache_lock:
            return _cache[root][0][:]
    files = scan_files(root)
    try:
        mtime = os.path.getmtime(root)
    except OSError:
        mtime = 0.0
    with _cache_lock:
        _cache[root] = (files, mtime)
    return files


def invalidate_cache(root: str | None = None):
    with _cache_lock:
        if root:
            _cache.pop(root, None)
        else:
            _cache.clear()


# ---------------------------------------------------------------- fuzzy match

def _fuzzy_match(query: str, text: str) -> int | None:
    """Return score (lower is better) if query matches text by subsequence,
    else None. Case-insensitive. Characters in query need not be contiguous
    but must appear in order."""

    q = query.lower()
    t = text.lower()
    qi = 0
    for ti, tc in enumerate(t):
        if qi < len(q) and tc == q[qi]:
            qi += 1
    if qi < len(q):
        return None

    # score: shorter match distance is better
    score = 0
    qi = 0
    last = -1
    for ti, tc in enumerate(t):
        if qi < len(q) and tc == q[qi]:
            if last >= 0:
                score += (ti - last - 1)
            last = ti
            qi += 1
    return score


# ---------------------------------------------------------------- segment match

def _segment_prefix(query: str) -> list[str]:
    """Split query into path segments: 'src/foo/bar' -> ['src', 'foo', 'bar']."""
    return query.replace("\\", "/").split("/")


def _segment_match(query_parts: list[str], path: str) -> bool:
    """Each segment must be a fuzzy subsequence of some path segment (in order)."""
    path_segments = path.replace("\\", "/").split("/")
    qi = 0
    for ps in path_segments:
        if qi < len(query_parts) and _fuzzy_match(query_parts[qi], ps) is not None:
            qi += 1
    return qi == len(query_parts)


# ---------------------------------------------------------------- public API

def candidates_for(query: str, root: str, limit: int = 20) -> list[str]:
    """Return sorted candidate paths for @-completion.

    Scoring: exact prefix match > segment match > fuzzy match.
    Within each tier, shorter paths and fewer dir depth win.
    """
    if not query:
        return cached_scan(root)[:limit]

    files = cached_scan(root)
    ql = query.lower()
    q_parts = _segment_prefix(query)
    scored: list[tuple[int, int, int, str]] = []  # (tier, depth, score, path)

    for f in files:
        fl = f.lower()
        # tier 0: exact prefix match (case-insensitive)
        if fl.startswith(ql):
            tier = 0
            score = len(f)
        # tier 1: segment match
        elif _segment_match(q_parts, f):
            tier = 1
            score = len(f)
        # tier 2: fuzzy match on full path
        else:
            s = _fuzzy_match(query, f)
            if s is None:
                continue
            tier = 2
            score = s + len(f) // 10
        depth = f.count("/") + f.count("\\")
        scored.append((tier, depth, score, f))

    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [p for _, _, _, p in scored[:limit]]


# ---------------------------------------------------------------- detect @

_AT_TOKEN_RE = re.compile(r'(^|[\s(])@([\w./\\_-]*)')


def detect_at_token(line_before_cursor: str):
    """Return (query, at_pos) when the cursor sits in an @token being
    typed on this line, else None. at_pos is the index of '@'."""
    m = _AT_TOKEN_RE.search(line_before_cursor)
    if not m:
        return None
    tok = m.group(1)
    return tok[1:], m.start(1)


def format_pick(path: str) -> str:
    """`@path` insert text; dirs get no trailing space (keep completing next
    level), files get one (close token). Spaces -> quoted."""
    trailing = '' if path.endswith(('/', '\\')) else ' '
    return f'@"{path}"{trailing}' if ' ' in path else f'@{path}{trailing}'


# --- path-like completion: an explicit-path @token (~/ / ./ ../ or C:\) goes
# to live directory completion instead of index fuzzy — this is how absolute
# paths outside the index root get completed level by level (claude-code parity).

def is_path_like(token: str) -> bool:
    if token in ('~', '.', '..'):
        return True
    if token.startswith(('~/', '~\\', './', '.\\', '../', '..\\', '/', '\\')):
        return True
    return len(token) >= 3 and token[0].isalpha() and token[1] == ':' and token[2] in '/\\'


def path_completions(token: str, root: str, limit: int = 15) -> list[str]:
    """readdir the real dir of a path-like token, prefix-match, dirs first.
    `~` expanded, relative -> root, absolute as-is; candidates keep the token's
    spelling, dirs carry a trailing '/'."""
    sep = max(token.rfind('/'), token.rfind('\\'))
    if sep >= 0:
        dir_part, prefix = token[:sep + 1], token[sep + 1:]
    elif token in ('~', '.', '..'):
        dir_part, prefix = token.rstrip('/\\') + '/', ''
    else:
        return []
    exp = os.path.expanduser(dir_part)
    real_dir = exp if os.path.isabs(exp) else os.path.join(root, exp)
    try:
        with os.scandir(real_dir) as it:
            entries = [(e.name, e.is_dir(follow_symlinks=False)) for e in it]
    except OSError:
        return []
    # filter & prefix-match
    matching = [(name, is_dir) for name, is_dir in entries
                if name.lower().startswith(prefix.lower())]
    # sort: dirs first, then alphabetical
    matching.sort(key=lambda x: (not x[1], x[0].lower()))
    candidates = []
    for name, is_dir in matching[:limit]:
        if is_dir:
            candidates.append(f"{dir_part}{name}/")
        else:
            candidates.append(f"{dir_part}{name}")
    return candidates


# --- absolutize @-mentions at submit-time (rewrite relative -> absolute)

_AT_ABSOLUTE_RE = re.compile(r'(?<!\S)@([^\s"\'<>()]+)')


def absolutize_mentions(text: str, cwd: str) -> str:
    """Rewrite @relative/path -> @/absolute/path in the input text.

    Already-absolute paths (starts with / ~ C:\\) are kept; non-file mentions
    (e.g. @agent, @web) are left as-is.  Uses cwd to resolve relative paths.
    """
    def _repl(m: re.Match) -> str:
        raw = m.group(1)
        # strip surrounding quotes if any
        path = raw.strip('"\'')
        if os.path.isabs(path) or path.startswith('~') or not path:
            return m.group(0)
        # try to resolve relative to cwd
        abs_path = os.path.abspath(os.path.join(cwd, path))
        if os.path.exists(abs_path):
            return f'@"{abs_path}"'
        return m.group(0)   # not a real path, keep as-is
    return _AT_ABSOLUTE_RE.sub(_repl, text)