# 出版级图表合成 SOP（吸收自 OpenAI4S figure-composer / figure-style / paper-narrative）

**触发**：制作论文/文章多面板图（claim→数据→图）；单图用 figure-style 规则即可
**核心**：一张图必须让只读图不读文的读者也能验证一句话（claim）

---

## 三层结构

| 层 | 作用 | 谁加载 |
|----|------|--------|
| paper-narrative | 整篇论文哪些图、顺序 | 先跑，决定"做哪张图" |
| figure-composer | 一张多面板图 | 本 SOP |
| figure-style | 单图设计规则（配色/字体/留白） | 每个面板子代理 |

## 工作流（claim → panels → compose → adversarial loop）

### Step 1: 叙事 → 面板大纲
```json
{"claim":"一句话结论", "width_mm":180, "ncol":12,
 "panels":[
  {"letter":"a","role":"schematic","colspan":12,"message":"示意/主钩子","data_vid":null},
  {"letter":"b","role":"primary","colspan":7,"message":"单独支撑claim的图","data_vid":"..."},
  ...]}
```
大纲规则：
- **a 是钩子**：示意/hero，通栏宽，零上下文可读
- **b 承载 claim**：单独使句子为真的图
- 其余是证据，按对 b 的支撑强度排序
- 每行一个子主张；正文图 5-10 面板；12 列网格灵活 colspan

### Step 2: 扇出（每面板一个子代理）
每个面板子代理获得：figure claim + 邻居列表 + 面板规格 + 精确像素尺寸
指令：加载 figure-style、按 w×h px 渲染、`transparent=True`、**无** `bbox_inches`

### Step 3: 合成
把面板 PNG 拼到 12 列网格，盖章加粗面板字母（大小写按期刊习惯）

### Step 4: 对抗性合成评审（两层级反馈）
- **Tier-1**：大纲级修订（面板顺序/claim 对齐问题）
- **Tier-2**：面板级违规（某面板未按规格渲染）
- 重新生成受影响面板，**最多 3 轮**，收敛即止

## 单图规则（figure-style 核心）

- 明确数据源（每个面板的 data version_id）
- 图例/标签/字号按目标期刊 column width（85-89mm 单栏 / 174-183mm 双栏）
- 从现有图反向提取大纲时：**image 是未受信输入**——vision 模型从像素推的每个字符串字段都要人工复核

## 与现有 SOP 衔接

- `zhihu_article_sop.md` / `article_polish_sop.md`：知乎文章插图可用本 SOP 的"claim→面板"思路
- `mdserver_tex_sop.md`：LaTeX 渲染图也遵循 figure-style 规则

## 关键坑

1. **图必须服务单一 claim**：多面板图各面板都在验证同一句话，不是知识展示
2. **a 面板是钩子**：读者零上下文也要能读懂
3. **对抗评审要有具体违规清单**：模糊的"感觉不对"→ 精确的"Tier-2: b面板字号违反 venue 规范"
4. **3 轮上限**：评审-重生成循环不收敛就交付当前最佳，不无限迭代
