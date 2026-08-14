"""SquillaRouter 配置: Tier模型映射 + 模型路径"""

import os
import json

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_GEAR_FILE = os.path.join(_PKG_DIR, ".gear_offset")

_TIER_ORDER = ["c0", "c1", "c2", "c3"]

def _read_gear() -> int:
    """从文件读取齿轮偏移"""
    try:
        with open(_GEAR_FILE, 'r') as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0

def _write_gear(offset: int):
    """写入齿轮偏移到文件"""
    with open(_GEAR_FILE, 'w') as f:
        f.write(str(offset))

# Tier -> 模型配置映射
# 用户在 mykey.py 中覆盖此映射
TIER_MODEL_MAP = {
    "c0": {
        "provider": "native_oai",
        "model": "deepseek-v4-flash",
        "max_tokens": 4096,
        "reasoning": False,
        "description": "极轻量模型 - 简单问答/翻译",
    },
    "c1": {
        "provider": "native_oai",
        "model": "deepseek-v4-flash",
        "max_tokens": 8192,
        "reasoning": False,
        "description": "中等模型 - 常规对话",
    },
    "c2": {
        "provider": "native_oai",
        "model": "deepseek-v4-flash",
        "max_tokens": 32768,
        "reasoning": False,
        "description": "强模型(Pro) - 复杂推理/代码",
    },
    "c3": {
        "provider": "native_oai",
        "model": "deepseek-v4-pro",
        "max_tokens": 32768,
        "reasoning": True,
        "description": "最强模型+深度思考 - 高难度分析",
    },
}

# ── 齿轮换档 ───────────────────────────────────
# ── 齿轮换档 ───────────────────────────────────
# 通过 .gear_offset 文件持久化，跨进程生效

def upgear() -> int:
    v = _read_gear()
    if v < 1:
        v += 1; _write_gear(v)
    return v

def downgear() -> int:
    v = _read_gear()
    if v > -1:
        v -= 1; _write_gear(v)
    return v

def gear_status() -> dict:
    offset = _read_gear()
    tiers = {}
    for tier in _TIER_ORDER:
        idx = _TIER_ORDER.index(tier)
        src_idx = max(0, min(len(_TIER_ORDER)-1, idx + offset))
        src_tier = _TIER_ORDER[src_idx]
        tiers[tier] = {"served_by": src_tier, "model": TIER_MODEL_MAP[src_tier]["model"], "shift": src_idx - idx}
    return {"offset": offset, "tiers": tiers}
# ─────────────────────────────────────────────────

# BGE 模型目录 (ONNX INT8)
BGE_MODEL_DIR = os.path.join(_PKG_DIR, "models", "bge_onnx")

# LightGBM 模型目录
LGBM_MODEL_DIR = os.path.join(_PKG_DIR, "models", "lightgbm")

# MLP 校准模型目录
MLP_MODEL_DIR = os.path.join(_PKG_DIR, "models", "mlp")

# 运行时配置目录
V4_BUNDLE_DIR = os.path.join(_PKG_DIR, "models", "v4_bundle")


def get_model_config(tier: str) -> dict:
    """获取指定 tier 的模型配置（已应用齿轮偏移）"""
    idx = _TIER_ORDER.index(tier) if tier in _TIER_ORDER else 1
    src_idx = max(0, min(len(_TIER_ORDER)-1, idx + _read_gear()))
    src_tier = _TIER_ORDER[src_idx]
    return TIER_MODEL_MAP.get(src_tier, TIER_MODEL_MAP["c1"])


def list_tiers() -> list[str]:
    """返回所有可用 tier 列表"""
    return sorted(TIER_MODEL_MAP.keys())
