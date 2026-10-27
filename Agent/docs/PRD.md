# Product Insight Agent — MVP Requirements v0.1

## 1. Product Overview（产品概述）

**Product Name:** Product Insight Agent

**Goal:** 帮助海外产品营销人员分析消费者评论，识别产品痛点、竞争品牌优劣势和潜在市场机会。

**Target Users:**
- Product Marketing Managers
- Market Researchers
- 海外消费硬件品牌与出海团队

**First Use Case:** 美国泳池清洁机器人市场（Pool Cleaning Robots）

### 核心研究问题

1. 消费者对这一类产品最满意和最不满意的地方是什么？
2. 不同品牌分别因为什么受到好评或差评？
3. 哪些消费者需求还没有得到充分满足？
4. 品牌可以采取哪些产品或营销行动？

---

## 2. Core Features（核心功能）

### F1. Research Setup — 创建研究任务

**优先级：P0，必须实现**

用户可以：

- 输入产品品类，例如 `Pool Cleaning Robots`
- 选择目标市场，例如 `United States`
- 输入 2–3 个待研究的竞争品牌
- 上传 CSV 格式评论文件
- 点击 `Generate Report` 开始分析

第一版不要求自动搜索全网，不要求输入关键词后自动抓取评论。

### F2. Data Processing — 评论预处理

**优先级：P0，必须实现**

系统自动：

- 检查 CSV 字段是否完整
- 删除完全重复的评论
- 识别空白、无关或无法分析的内容
- 标记未知品牌及缺失字段
- 保留每条有效评论的原始来源链接
- 统计导入数量、有效数量和排除数量

如果数据不足，明确提示用户，而不是编造分析结果。

### F3. Consumer Insights — 消费者洞察

**优先级：P0，必须实现**

AI 为有效评论提取：

| 分析维度 | 输出内容 |
|---|---|
| Sentiment | Positive / Negative / Neutral / Mixed |
| Product Aspect | 续航、清洁效果、价格、维护、可靠性等 |
| Pain Point | 消费者反馈的具体问题 |
| Positive Feedback | 消费者认可的产品优势 |
| Unmet Need | 评论明确提出或有证据支持的未满足需求 |
| Evidence | 对应原始评论 ID 和链接 |

**分析规则：**

- 一条评论允许包含多个产品话题。
- 同一条评论可以同时表达正面与负面观点。
- AI 不能仅根据评论的情绪就推断具体痛点。
- 评论没有提到的产品属性不能凭空补充。
- 重要结论应由多条独立评论支持。

### F4. Competitive Intelligence — 竞品比较

**优先级：P0，必须实现**

针对用户选择的品牌，比较：

1. 各品牌的正面和负面反馈主题
2. 各品牌最常被提及的产品优势
3. 各品牌最常被提及的问题
4. 消费者明确表达的品牌比较
5. 有证据支持的差异化机会

**输出示意：**

| Aspect | Brand A | Brand B | Brand C |
|---|---|---|---|
| Cleaning Performance | Positive | Mixed | Positive |
| Battery Life | Negative | Positive | Mixed |
| Maintenance | Mixed | Negative | Positive |

以上内容仅为格式示意，不代表真实品牌评价。

**重要限制：**

- 仅在评论能可靠归属于某品牌时，纳入该品牌比较。
- 不得仅凭视频标题就假定评论者使用过该品牌。
- 如果没有足够证据，标注 `Insufficient Data`。
- 品牌比较要展示各品牌有效评论数量。
- 不把小样本评论分析称为整个市场的品牌排名。

### F5. Report Generation — 生成研究报告

**优先级：P0，必须实现**

自动生成以下六部分：

1. **Executive Summary**：3 个最重要的发现
2. **Consumer Pain Points**：主要痛点、出现次数、证据链接
3. **Consumer Sentiment**：正负面反馈及相关产品特征
4. **Competitor Comparison**：品牌优势与不足
5. **Business Opportunities**：最多 3 条可进一步验证的商业建议
6. **Sources & Methodology**：数据来源、样本数量、筛选与研究局限

每个关键发现都应可以追溯至具体评论。将事实、AI 解释和行动建议明确区分。

### F6. Report Export — 导出结果

**优先级：P1，可稍后加入**

- 下载 Markdown 报告
- 导出评论分类结果为 CSV
- 后续支持 PDF 报告

---

## 3. Data Requirements（数据需求）

### 3.1 输入数据结构

第一版使用用户获准提供的 CSV 文件。

| Field | Required | Description |
|---|---|---|
| `review_id` | Yes | 评论唯一编号 |
| `review_text` | Yes | 评论正文 |
| `source_platform` | Yes | 数据来源平台 |
| `source_url` | Yes* | 原始评论链接 |
| `brand` | Yes* | 可归属品牌 |
| `product_model` | No | 产品型号 |
| `posted_at` | No | 评论发布日期 |
| `rating` | No | 原始评分 |
| `country` | No | 评论明确支持的国家信息 |
| `language` | No | 评论语言 |

\*真实证据报告需要可用的 `source_url`；缺失时可参与内部流程测试，但不能冒充可追溯证据。未知品牌可以使用 `unknown`，但不能进入单品牌对比统计。

禁止 AI 猜测缺失的真实评分、国家或评论日期。

### 3.2 第一版样本规模

**技术测试：**

- 30–50 条合规评论或明确标记的合成测试评论
- 目标是验证数据处理、AI 分类和报告生成能否运行

**正式 MVP 案例：**

- 目标收集约 90–150 条获准使用的真实评论
- 选择最多 3 个竞争品牌
- 尽量保证每个品牌约 30–50 条有效评论
- 如果某品牌不足 20 条有效评论，默认不进行强结论的横向比较

这些是开发阶段的测试目标，不代表统计学意义上的市场代表性。

### 3.3 数据筛选要求

需要识别并处理：

- 重复评论
- 与目标产品无关的评论
- 只有表情或无法理解的文本
- 无法明确归属品牌的评论
- 内容可能为广告或推广的评论

保留排除原因与处理数量，方便后续人工检查。

---

## 4. Analysis Rules（分析与统计规则）

**Pain Point Frequency**

某痛点被多少条有效评论提及，就记录多少条；一条评论在同一个痛点下最多计一次。

**Mention Rate**

`提及某痛点的评论数 ÷ 相应分析范围内的有效评论数`

这一比例只表示**当前收集样本内部的提及情况**，不是总体消费者发生率。

**Competitor Comparison**

优先比较有明确评论证据的产品属性。每项结果同时展示：

- 品牌有效样本量
- 相关评论提及次数
- 情绪或态度分类
- 代表性证据链接

**Evidence Standard**

每条关键结论至少附上可追溯的评论 ID。重要共性问题优先要求多条独立评论支持。

**No Hallucination**

没有足够证据时，直接输出 `Insufficient Evidence`，不得编造评论、数量、品牌表现或链接。

---

## 5. Recommended Technical Architecture（技术方案）

| Component | MVP Selection |
|---|---|
| User Interface | Streamlit（Python 网页应用） |
| Data Processing | Python + pandas |
| AI Analysis | 支持结构化输出的大模型 API |
| Data Storage | 初期使用临时文件，必要时使用 SQLite |
| Report | 网页展示 + Markdown |
| Deployment | 现有阿里云新加坡服务器 |

初期使用固定的分析流程，不必开发复杂的多 Agent 系统。

### Processing Pipeline

1. Upload CSV
2. Validate & Clean Data
3. Classify Consumer Feedback
4. Identify Brands & Product Attributes
5. Aggregate Results
6. Generate Business Insights
7. Validate Evidence References
8. Display Report

所有 AI API Key 保存在服务端环境变量中，不写进 GitHub 仓库，也不传给浏览器。

测试版本限制访问，并设置上传文件大小、评论数量和 API 调用上限，以控制成本。

---

## 6. MVP Success Criteria（验收标准）

第一版完成时，应满足：

- [ ] 用户可以上传 CSV 并设置研究任务
- [ ] 系统可以处理至少 50 条测试评论
- [ ] 能识别消费者正负面反馈和产品属性
- [ ] 能根据可靠的品牌归属进行竞品比较
- [ ] 能生成六部分研究报告
- [ ] 关键结论具备真实、有效的来源链接
- [ ] 人工随机抽查至少 20 条 AI 分类结果
- [ ] 没有来源支持时不会虚构结论
- [ ] 可在网页中完整展示报告

人工抽查需要记录正确、部分正确和错误的分类，而不是仅凭报告看起来合理就判定成功。

---

## 7. Out of Scope（第一版暂不开发）

- 全网自动爬虫
- Reddit、Amazon、YouTube 三平台实时整合
- 自动识别全部市场竞争品牌
- 大规模历史评论数据库
- 市场份额预测
- 销量预测
- 多用户账号和付费系统
- 复杂交互式数据仪表盘

这些功能可以在核心流程验证有效后逐步增加。

---

## 8. Future Development

**MVP v0.1：** CSV 上传 → AI 分析 → 竞品比较 → 报告

**MVP v0.2：** 在确认授权与使用规则后，接入第一个真实数据源

**MVP v0.3：** 支持多个合法数据来源、完善报告交互和导出

**MVP v1.0：** 邀请真实营销人员测试，并根据反馈调整产品功能