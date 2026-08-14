# ML 实验规划 SOP（吸收自 OpenAI4S plan-ml-experiment）

**触发**：开始训练/建模前（含 iT-NDF、ITNDF、任何 torch/sklearn 实验）
**核心**：可复现实验 = 可证伪的问题 + 不可变输入 + 防泄漏评估边界 + 声明的指标 + 足够重跑的记录状态
**工具**：`memory/sci_methods.py`（grouped_split / chronological_split / random_split / experiment_manifest / config_fingerprint）

---

## 规划序列（训练前完成，禁先看测试性能再写假设）

1. **写假设/干预/基线/主指标/决策规则**（在查看测试集性能之前）
2. **选择独立单元**：
   - 患者/分子骨架/站点/文档/重复测量 → `grouped_split`（组整体进入同一 split）
   - 部署预测未来 → `chronological_split`（按时间排序不洗牌）
   - 行真正独立 → `random_split`
3. **测试集保留到最后对比**：预处理拟合和超参选择只用 train/validation
4. **固定 seeds、环境、输入版本、精确配置**
5. **先跑基线，再单因子消融，最后计划模型**
6. **画结论前保存逐样本预测 + manifest**

## 代码用法

```python
from sci_methods import grouped_split, experiment_manifest, config_fingerprint

# 防组泄漏切分（如：同一患者的窗归同一 split）
splits = grouped_split(patient_ids, seed=42)
# train/validation/test 是原始行索引

# 实验 manifest（含配置指纹 + 数据 sha256 + seeds + code_revision）
manifest = experiment_manifest(
    config,
    data_paths=["data/cohort.csv"],
    seeds=[42, 43, 44],
    code_revision="<git commit>",
)
```

## 最小产物集

- 冻结 config + `config_fingerprint`
- 源数据/版本 + SHA-256 校验和
- code_revision、运行时/环境版本、随机 seeds
- split 索引或稳定样本 ID + 分组/时间策略
- 基线/消融/最终逐样本预测
- 聚合指标（含不确定性）+ 失败分析

## 关键坑

1. **组泄漏是最大陷阱**：按窗随机切分时，同一受试者/录次的相邻窗高度相关 → 指标虚高（breaker 案例 98.19% 被高估）
2. **确定性 ≠ 有效性**：硬件 kernel 可能非确定性；重复一个有偏 split 不能修复泄漏
3. **报告偏离计划而非覆盖计划**
4. **禁止发明环境状态**：manifest 只记录真实值（代码版本、文件 sha256），不虚构

## 与现有 SOP 衔接

- `itndf_train_sop.md`：训练脚本细节（TimeEncoder/ValMSE/EMA）→ 本 SOP 是其"实验规划前置"
- 交付前自测规则仍按 `itndf_train_sop` 第8条（py_compile + 3-5 epoch 双路径）
