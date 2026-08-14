# 模型评估 SOP（吸收自 OpenAI4S evaluate-model）

**触发**：训练完成后评估/对比模型（分类/回归/时序预测）
**核心**：评估结论必须锚定到**数据**（逐样本预测+聚合指标+不确定性），不是"效果不错"

---

## 最小评估集

1. **逐样本预测**（测试集每个样本的预测值/概率/置信度）——一切聚合指标可回溯的底座
2. **聚合指标**：
   - 分类：accuracy + **F1（类别加权/宏/微都报）** + confusion matrix
   - 回归：MSE/MAE + 残差分布
   - 时序：MSE + 误差随预测步长变化曲线
3. **不确定性**：置信区间/多次 seed 的指标 std（**单次运行结论不可靠**）
4. **失败分析**：错误样本的典型模式（哪个类别/哪个区间错得最多）——比平均指标更说明问题

## 评估红线

1. **只看 accuracy 不看 F1** → 类别不平衡时自欺（参考 scientific_data_diagnosis_sop §1）
2. **测试集泄漏进预处理/超参选择** → 指标虚高（参考 ml_experiment_sop）
3. **单 seed 结论** → 至少 3 seeds 报 mean±std
4. **不保存逐样本预测就画结论** → 无法失败分析、无法复核

## 与现有 SOP 衔接

- `scientific_data_diagnosis_sop.md`：训练前数据诊断（不平衡/泄漏/结构）
- `ml_experiment_sop.md`：实验规划（manifest/切分/消融）
- `itndf_train_sop.md`：iT-NDF 特定训练细节（ValMSE 计算/EMA/归一化）

## 代码骨架

```python
from sci_methods import experiment_manifest

# 训练完 → 保存逐样本预测 + manifest
import json, numpy as np
np.save("test_preds.npy", preds)          # 逐样本
np.save("test_labels.npy", labels)
manifest = experiment_manifest(config, data_paths=["data/test.csv"],
                               seeds=[1,2,3], code_revision="<git>")
json.dump(manifest, open("manifest.json", "w"))

# 多次seed聚合
# accuracy_mean, accuracy_std, f1_macro_mean, ...
```
