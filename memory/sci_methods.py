"""SciMethods — 科研方法工具箱（吸收自 OpenAI4S / PKU-YuanGroup）

两组纯标准库实现：
A. 可复现 ML 实验：防泄漏切分(random/chronological/grouped_split) + 配置指纹 + 实验manifest
B. 文献检索与验证：DOI验证(CrossRef+doi.org)、文献查询(Crossref/OpenAlex)、引用图双向扩展

来源: OpenAI4S skills/plan-ml-experiment/kernel.py 与 skills/literature-review/kernel.py
适配: 移除 host RPC 依赖，网络用 urllib.request（GenericAgent 单进程环境）
用法: from sci_methods import grouped_split, experiment_manifest, verify_dois, ...
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# ============ A. 可复现 ML 实验 ============

_NAMES = ("train", "validation", "test")


def _fractions(values: Sequence[float]) -> tuple[float, float, float]:
    if len(values) != 3:
        raise ValueError("fractions must contain train, validation, and test")
    fractions = tuple(float(value) for value in values)
    if any(value < 0 for value in fractions):
        raise ValueError("fractions must be non-negative")
    if not abs(sum(fractions) - 1.0) < 1e-9:
        raise ValueError("fractions must sum to 1")
    return fractions  # type: ignore[return-value]


def _sizes(size: int, fractions: Sequence[float]) -> tuple[int, int, int]:
    if size < 0:
        raise ValueError("size must be non-negative")
    train_fraction, validation_fraction, _ = _fractions(fractions)
    train = int(size * train_fraction)
    validation = int(size * validation_fraction)
    return train, validation, size - train - validation


def _partition(indices: Sequence[int], sizes: Sequence[int]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    cursor = 0
    for name, size in zip(_NAMES, sizes):
        result[name] = list(indices[cursor : cursor + size])
        cursor += size
    return result


def random_split(
    size: int,
    *,
    fractions: Sequence[float] = (0.7, 0.15, 0.15),
    seed: int = 0,
) -> dict[str, list[int]]:
    """Shuffle independent row indices deterministically."""
    sizes = _sizes(size, fractions)
    indices = list(range(size))
    random.Random(seed).shuffle(indices)
    return _partition(indices, sizes)


def chronological_split(
    timestamps: Sequence[Any],
    *,
    fractions: Sequence[float] = (0.7, 0.15, 0.15),
) -> dict[str, list[int]]:
    """Split indices after stable ascending timestamp ordering."""
    sizes = _sizes(len(timestamps), fractions)
    try:
        indices = sorted(range(len(timestamps)), key=timestamps.__getitem__)
    except TypeError as exc:
        raise ValueError("timestamps must be mutually comparable") from exc
    return _partition(indices, sizes)


def grouped_split(
    groups: Sequence[Any],
    *,
    fractions: Sequence[float] = (0.7, 0.15, 0.15),
    seed: int = 0,
) -> dict[str, list[int]]:
    """Assign every equal group value to exactly one split.

    每个分组值整体进入唯一一个 split（防组泄漏）。
    组按规模降序 + 种子平局打破，放入填充率最低的目标 split。
    """
    fractions_tuple = _fractions(fractions)
    encoded = [
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=repr)
        for value in groups
    ]
    counts = Counter(encoded)
    rng = random.Random(seed)
    tie_breakers = {group: rng.random() for group in counts}
    ordered = sorted(counts, key=lambda group: (-counts[group], tie_breakers[group]))
    targets = [len(groups) * fraction for fraction in fractions_tuple]
    assigned_counts = [0, 0, 0]
    group_split: dict[str, int] = {}
    for group in ordered:
        eligible = [index for index, fraction in enumerate(fractions_tuple) if fraction]
        destination = min(
            eligible,
            key=lambda index: (
                (assigned_counts[index] + counts[group]) / targets[index],
                index,
            ),
        )
        group_split[group] = destination
        assigned_counts[destination] += counts[group]

    result = {name: [] for name in _NAMES}
    for index, group in enumerate(encoded):
        result[_NAMES[group_split[group]]].append(index)
    return result


def config_fingerprint(config: Mapping[str, Any]) -> str:
    """SHA-256 of a canonical JSON-compatible experiment configuration."""
    payload = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def experiment_manifest(
    config: Mapping[str, Any],
    *,
    data_paths: Sequence[str | Path] = (),
    seeds: Sequence[int] = (),
    code_revision: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-compatible manifest without inventing environment state."""
    return {
        "config": dict(config),
        "config_fingerprint": config_fingerprint(config),
        "data": [
            {"path": str(path), "sha256": file_sha256(path)} for path in data_paths
        ],
        "seeds": [int(seed) for seed in seeds],
        "code_revision": code_revision,
    }


# ============ B. 文献检索与验证 ============

_UA = "sci_methods/1.0 (GenericAgent; research helper)"


def _http_get_json(url: str, timeout: float = 15) -> dict | None:
    """GET `url` and JSON-decode. One 2s retry on HTTP 429; None on error."""
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:
            if attempt == 0 and hasattr(exc, "code") and exc.code == 429:
                time.sleep(2)
                continue
            return None
    return None


def _http_head_status(url: str, timeout: float = 10) -> int | None:
    """HEAD `url` WITHOUT following redirects; return origin status.
    doi.org 返回 302(已注册) / 404(未注册)，而非出版社状态。"""
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(2)
                continue
            return e.code
        except Exception:
            return None
    return None


def quote_doi_path(doi: str) -> str:
    """URL-encode a DOI path; unquote each segment first so a pre-encoded
    %28 stays single-encoded (caller may pass either form)."""
    return "/".join(
        urllib.parse.quote(urllib.parse.unquote(seg), safe="") for seg in doi.split("/")
    )


def crossref_year(m: dict) -> int | None:
    """Safely extract the publication year from a CrossRef `message` record."""
    dp = (m.get("published") or {}).get("date-parts") or [[None]]
    return (dp[0] or [None])[0]


def verify_dois(dois: list[str]) -> dict[str, dict]:
    """Resolve each DOI against CrossRef, with a doi.org HEAD fallback.
    返回 {doi: {ok, title?, year?, journal?, retracted?, registry?, error?}}
    ok=True 可解析 / ok=False 不可解析(疑似伪造或typo) / ok=None 无法验证(网络)
    retracted 仅在 CrossRef 命中时为 True/False，其余为 None。
    """
    out: dict[str, dict] = {}
    for d in dois:
        d = d.strip()
        segs = urllib.parse.unquote(d).split("/")
        if any(seg in ("", ".", "..") for seg in segs[1:]):
            out[d] = {"ok": False, "error": "dot-segment in DOI"}
            continue
        enc = quote_doi_path(d)
        j = _http_get_json(f"https://api.crossref.org/works/{enc}")
        time.sleep(0.06)
        if j and "message" in j:
            m = j["message"]
            title = (m.get("title") or [""])[0]
            upd = [u.get("type", "") for u in (m.get("update-to") or [])]
            retracted = (
                any("retract" in t.lower() for t in upd)
                or str(m.get("subtype") or "").lower() == "retraction"
                or title.upper().startswith("RETRACTED")
            )
            out[d] = {
                "ok": True,
                "title": title,
                "year": crossref_year(m),
                "journal": (m.get("container-title") or [""])[0],
                "retracted": retracted,
                "registry": "crossref",
            }
            continue
        code = _http_head_status(f"https://doi.org/{enc}")
        if code is not None and 200 <= code < 400:
            out[d] = {"ok": True, "registry": "non-crossref", "retracted": None}
        elif code == 404:
            out[d] = {"ok": False}
        else:
            out[d] = {"ok": None, "error": "unverified (network)", "retracted": None}
    return out


def crossref_lookup(ref_string: str) -> dict | None:
    """Find a DOI from a free-text citation (author/title/year)."""
    q = urllib.parse.quote(ref_string)
    j = _http_get_json(f"https://api.crossref.org/works?query.bibliographic={q}&rows=1")
    items = (j or {}).get("message", {}).get("items", [])
    if not items:
        return None
    m = items[0]
    return {
        "doi": m.get("DOI"),
        "title": (m.get("title") or [""])[0],
        "year": crossref_year(m),
        "score": m.get("score"),
    }


def search_openalex(query: str, n: int = 10, filters: str = "") -> list[dict]:
    """Search OpenAlex (~250M works). Returns up to n hits as
    [{doi, title, year, cited_by, venue, oa_url}]."""
    q = urllib.parse.quote(query)
    flt = f"&filter={filters}" if filters else ""
    j = _http_get_json(
        f"https://api.openalex.org/works?search={q}&per-page={min(n, 25)}"
        f"&sort=cited_by_count:desc{flt}"
    )
    out = []
    for w in (j or {}).get("results", [])[:n]:
        loc = w.get("primary_location") or {}
        venue = ((loc.get("source") or {}) or {}).get("display_name")
        out.append(
            {
                "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                "title": w.get("title"),
                "year": w.get("publication_year"),
                "cited_by": w.get("cited_by_count"),
                "venue": venue,
                "oa_url": (w.get("open_access") or {}).get("oa_url"),
            }
        )
    return out


def expand_citations(doi: str, n_backward: int = 50, n_forward: int = 15) -> dict:
    """One citation-graph step in both directions via OpenAlex.
    `references`=backward(本文引用, filter=cited_by:<id>, 按被引降序)
    `cited_by`  =forward(引用本文, filter=cites:<id>)
    每项 {doi, title, year, cited_by}。DOI 未知时返回空列表。"""
    enc = quote_doi_path(doi)
    j1 = _http_get_json(
        f"https://api.openalex.org/works?filter=cited_by:{enc}&per-page={min(n_backward, 25)}&sort=cited_by_count:desc"
    )
    j2 = _http_get_json(
        f"https://api.openalex.org/works?filter=cites:{enc}&per-page={min(n_forward, 25)}&sort=cited_by_count:desc"
    )
    out = {"references": [], "cited_by": []}
    for w in (j1 or {}).get("results", [])[:n_backward]:
        out["references"].append(
            {
                "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                "title": w.get("title"),
                "year": w.get("publication_year"),
                "cited_by": w.get("cited_by_count"),
            }
        )
    for w in (j2 or {}).get("results", [])[:n_forward]:
        out["cited_by"].append(
            {
                "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                "title": w.get("title"),
                "year": w.get("publication_year"),
                "cited_by": w.get("cited_by_count"),
            }
        )
    return out
