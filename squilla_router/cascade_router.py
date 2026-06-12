"""CascadeRouter: GenericAgent 级联路由引擎入口。

在 agent_loop 的每个 turn 前调用，根据对话上下文
选择最优模型 tier，并支持级联降级/升级。
"""

import os, json, time, logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── 路由层级定义 ──────────────────────────────────────────
TIER_ORDER = ("c0", "c1", "c2", "c3")
DEFAULT_TIER = "c1"
HIGHEST_TIER = "c3"

def normalize_text_tier(raw: str) -> Optional[str]:
    if not raw:
        return None
    t = raw.strip().lower().replace("t", "c")
    if t in TIER_ORDER:
        return t
    return None

def tier_index(tier: str) -> int:
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 1

# ── 轨迹定义 ──────────────────────────────────────────
class Trajectory:
    COLD_START = "COLD_START"
    STABLE_LOW = "STABLE_LOW"
    STABLE_HIGH = "STABLE_HIGH"
    ESCALATING = "ESCALATING"
    DESCALATING = "DESCALATING"
    OSCILLATING = "OSCILLATING"

def classify_trajectory(history: list) -> str:
    if not history or len(history) < 2:
        return Trajectory.COLD_START
    tiers = history[-6:]
    try:
        diffs = [tier_index(tiers[i+1]) - tier_index(tiers[i]) for i in range(len(tiers)-1)]
    except (ValueError, IndexError):
        return Trajectory.COLD_START
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        if tier_index(tiers[-1]) <= 1:
            return Trajectory.STABLE_LOW
        return Trajectory.STABLE_HIGH
    if len(nonzero) >= 2 and all(d > 0 for d in nonzero):
        return Trajectory.ESCALATING
    if len(nonzero) >= 2 and all(d < 0 for d in nonzero):
        return Trajectory.DESCALATING
    direction_changes = sum(1 for a, b in zip(nonzero, nonzero[1:]) if a != b)
    if direction_changes >= 2:
        return Trajectory.OSCILLATING
    return Trajectory.COLD_START


@dataclass
class RouterDecision:
    """一次路由决策的结果"""
    tier: str                              # 选定的 tier
    model: str                             # 对应的模型名
    provider: str                          # 对应的 provider
    thinking_mode: str = "T1"              # T0-T3 推理模式
    prompt_policy: str = "P0"              # P0-P2 提示策略
    probs: dict = field(default_factory=dict)  # 各tier概率
    trajectory: str = Trajectory.COLD_START
    latency_ms: float = 0.0


class CascadeRouter:
    """级联路由器 - 策略感知+历史感知的模型选择器。

    工作流程:
    1. fallback: 如果未配置路由模型，返回默认 tier
    2. 检查用户显式请求 (如 "use c3")
    3. 调用预测器 (如果可用)
    4. 应用 sticky tier (防抖)
    5. 级联: 如果选定模型可用则返回，否则降级
    """

    def __init__(self, predictor=None):
        self._predictor = predictor  # V4Phase3Predictor 实例
        self._route_history: list[str] = []  # 每轮的 tier 决策历史
        self._sticky_tier: Optional[str] = None
        self._sticky_count = 0
        self._last_decision: Optional[RouterDecision] = None
        self._log_path = os.environ.get("SQUILLA_ROUTER_LOG", "")
        if not self._log_path:
            self._log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "temp", "router_log.jsonl")

    def decide(self,
               current_text: str,
               history_texts: list[str],
               prev_assistant_text: Optional[str] = None,
               prev_assistant_usage: Optional[dict] = None,
               force_tier: Optional[str] = None,
               available_tiers: list[str] | None = None,
               flags: dict | None = None,
               ) -> RouterDecision:
        """执行路由决策。"""
        start = time.time()

        # 1. 强制 tier (用户指定)
        if force_tier:
            tier = normalize_text_tier(force_tier) or DEFAULT_TIER
            probs = {tier: 1.0}
        else:
            # 2. 预测器 (如果已加载 V4 模型)
            if self._predictor and self._predictor.is_available():
                try:
                    result = self._predictor.predict(
                        current_user_text=current_text,
                        history_user_texts=history_texts,
                        prev_assistant_text=prev_assistant_text,
                        prev_assistant_usage=prev_assistant_usage or {},
                        prev_route_decisions=self._route_history[-5:] if self._route_history else [],
                        flags=flags or {},
                    )
                    tier = normalize_text_tier(result.decision.selected_model) or DEFAULT_TIER
                    probs = result.probabilities
                except Exception as e:
                    logger.warning(f"[Router] 预测失败, 使用默认: {e}")
                    tier = DEFAULT_TIER
                    probs = {}
            else:
                # 无预测器: 简单启发式
                tier = self._heuristic_route(current_text, history_texts)
                probs = {}

        # 3. 应用 sticky tier (防抖)
        tier = self._apply_sticky(tier)

        # 4. 级联降级: 确保模型可用
        final_tier = self._cascade(tier, available_tiers)

        # 5. 记录
        self._route_history.append(final_tier)
        trajectory = classify_trajectory(self._route_history)

        elapsed = (time.time() - start) * 1000

        from .config import get_model_config
        cfg = get_model_config(final_tier)
        decision = RouterDecision(
            tier=final_tier,
            model=cfg["model"],
            provider=cfg["provider"],
            probs=probs,
            trajectory=trajectory,
            latency_ms=elapsed,
        )
        self._last_decision = decision
        # 埋点: 写入 JSONL 日志
        try:
            import json
            log_entry = {
                "ts": time.time(), "tier": final_tier, "model": cfg["model"],
                "traj": str(trajectory), "latency_ms": round(elapsed, 1),
                "text_len": len(current_text) if current_text else 0,
            }
            with open(self._log_path, "a", encoding="utf-8") as lf:
                lf.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return decision

    def _heuristic_route(self, text: str, history: list) -> str:
        """无预测器时的启发式路由:
        - 短文本(<=50字)且轮次少 -> c0/c1
        - 包含复杂关键词 -> c2/c3
        """
        text_len = len(text)
        total_turns = len(history) if history else 0

        complex_keywords = [
            "分析", "总结", "解释", "optimize", "debug", "refactor",
            "架构", "设计", "比较", "优缺点", "影响",
            "complex", "difficult", "challenging",
        ]

        has_complex = any(kw in text.lower() for kw in complex_keywords)

        if text_len < 50 and not has_complex and total_turns < 3:
            return "c0"
        elif text_len < 200 and not has_complex:
            return "c1"
        elif has_complex or text_len > 500:
            return "c2"
        return "c1"

    def _apply_sticky(self, new_tier: str) -> str:
        """KV-cache 感知的 sticky tier: 避免频繁切换"""
        if self._sticky_tier and self._sticky_tier != new_tier:
            new_idx = tier_index(new_tier)
            sticky_idx = tier_index(self._sticky_tier)
            # 如果当前预测比 sticky 低且 sticky 还较新 -> 保持
            if new_idx < sticky_idx and self._sticky_count < 3:
                self._sticky_count += 1
                return self._sticky_tier
        self._sticky_tier = new_tier
        self._sticky_count = 0
        return new_tier

    def _cascade(self, tier: str, available: list[str] | None) -> str:
        """级联降级: 如果选定 tier 不可用，往下降"""
        if not available:
            return tier
        t = tier
        while t not in available and tier_index(t) >= 0:
            idx = tier_index(t)
            if idx <= 0:
                return DEFAULT_TIER
            t = TIER_ORDER[idx - 1]
        return t

    def report_llm_failure(self, tier_used: str):
        """反馈: LLM 调用失败，记录供下次降级使用"""
        logger.info(f"[Router] LLM failure for tier={tier_used}, will cascade next time")

    def reset(self):
        self._route_history.clear()
        self._sticky_tier = None
        self._sticky_count = 0
        self._last_decision = None

    def get_stats(self) -> dict:
        return {
            "total_turns": len(self._route_history),
            "history": self._route_history[-10:],
            "last_tier": self._route_history[-1] if self._route_history else None,
        }


# ── 便捷函数 ──────────────────────────────────────────
_DEFAULT_ROUTER: Optional[CascadeRouter] = None

def get_router() -> CascadeRouter:
    global _DEFAULT_ROUTER
    if _DEFAULT_ROUTER is None:
        _DEFAULT_ROUTER = CascadeRouter()
    return _DEFAULT_ROUTER

def route_decision(text: str,
                   history: list[str] | None = None,
                   force_tier: str | None = None,
                   available: list[str] | None = None) -> RouterDecision:
    router = get_router()
    return router.decide(
        current_text=text,
        history_texts=history or [],
        force_tier=force_tier,
        available_tiers=available,
    )
