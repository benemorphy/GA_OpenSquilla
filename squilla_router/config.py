"""SquillaRouter 配置: Tier模型映射 + 模型路径"""

import os

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

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

# BGE 模型目录 (ONNX INT8)
BGE_MODEL_DIR = os.path.join(_PKG_DIR, "models", "bge_onnx")

# LightGBM 模型目录
LGBM_MODEL_DIR = os.path.join(_PKG_DIR, "models", "lightgbm")

# MLP 校准模型目录
MLP_MODEL_DIR = os.path.join(_PKG_DIR, "models", "mlp")

# 运行时配置目录
V4_BUNDLE_DIR = os.path.join(_PKG_DIR, "models", "v4_bundle")


def get_model_config(tier: str) -> dict:
    """获取指定 tier 的模型配置"""
    return TIER_MODEL_MAP.get(tier, TIER_MODEL_MAP["c1"])


def list_tiers() -> list[str]:
    """返回所有可用 tier 列表"""
    return sorted(TIER_MODEL_MAP.keys())
