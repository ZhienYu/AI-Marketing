# Consumer Needs Discovery：最小升级与验收

更新：2026-11-04。只启用合成离线研究；真实 YouTube 筛选、需求识别、Qwen 和报告继续关闭。

## 最小方案与已完成实现

新增 `consumer_needs.py` 作为研究扩展层，调用现有 `orchestrator.run_mock_pipeline` 完成搜索样例、评论归一化、资格筛选、分类、洞察和报告。
不重新实现这些阶段，也不把模拟分类冒充真实 Qwen 输出。独立 sidecar 保存需求证据，不修改旧分类结果或旧检查点。
使用新建运行目录，在旧报告之外输出目的对应报告，不覆盖历史文件。

研究目的：

| 目的 | 报告前置章节 | 商业价值边界 |
|---|---|---|
| Product Improvement Research | 使用场景、具体问题与复现线索、未满足需求假设、改进方向与验证实验 | 从证据导出需要访谈/复现/原型验证的问题，不把痛点直接变成工程结论或预算承诺 |
| Competitor Research | 品牌与场景覆盖、品牌问题证据、潜在差异化需求假设、定位与对照验证 | 复用现有品牌属性比较表和样本量；不作“竞品落后”或市场排名结论，unknown 不进入品牌比较 |

两种模板随后附加原有 Report Generator 的证据、情绪、属性和方法章节；事实与推断逐行区分。
当前合成需求样例只有一个有需求标注的场景，其余已审阅评论保留空数组，不能为了“完整”补造需求。
模板只提供有证据的研究方向；具体产品投入、付费意愿和 ROI 必须另行验证。

## 字段与校验

Qwen 可选研究响应由 `classification`（原有四字段）和 `consumer_needs` 组成。
后者包括 `usage_scenarios`、`specific_pain_points`、`unmet_needs`、`improvement_suggestions` 四个数组。
每项必须有 text、claim_type、quote、uncertainty、validation_step。

- `raw_feedback`：text 必须与 quote 完全一致，quote 必须是该条原文中的非空连续子串。
- `ai_inference`：翻译、概括、推断出的需求或建议，仍必须引用原文并声明不确定性与验证步骤。Mock 中此标签代表人工编写的模拟推断，报告已明确不是实际 AI 结果。
- 证据身份由程序绑定 review_id、brand、source_platform、source_url 和资格证据强度，不让模型编造 ID、品牌和链接。
- 只接收已成功分类且 `eligible_as_usage_review` 的记录；购买咨询、视频反馈、歧义记录不能升级为使用体验证据。
- 重复同评论/同维度/完全相同 claim 只保留一次；不将同一评论多个维度相加为需求人数。复用原有属性去重统计。
- 报告生成前重新验证需求 sidecar 与输入的一致性，同时复用旧报告对分类/原始 CSV/指纹/洞察的核对；被修改的结论或引句拒绝输出。
- 引句存在仅证明文字匹配，不能证明模型推断正确、品牌归属可靠或需求有商业规模；需要人工核验。
- 空数组表示证据不支持提取，不表示不存在需求；品牌样本不足继续标 Insufficient Data。

验收：两种模板均可生成；原文与推断明确分开；错误 ID、虚构引句、缺失不确定性、篡改结论、重复输入被校验；真实输入不得经该扩展分析；旧测试通过。

## Qwen Pipeline 适配结果

原 `check_classification` 严格校验四字段，直接增加字段会破坏兼容，因此不修改旧结构。
`classify_qwen(..., research=True)` 使用独立的研究提示词、响应 envelope 和校验器，保留原 Token 统计、北京地域、超时、错误处理和禁止自动重试。
研究模式只接受完整合成记录，先检查数据类型再接触凭据或 HTTP；真实评论和截断预览拒绝。当前没有研究模式的付费 CLI 或网页入口。
默认调用仍使用原提示词和分类签名，旧检查点不受影响。研究 sidecar 有自己的 `research_signature`；它不是旧检查点的一部分，不能把新旧缓存混用。
当前研究模式使用最多 3000 completion tokens（旧模式仍 1000）；结构大或截断会校验失败，不能将部分结果补齐。
离线测试用 Mock HTTP 响应验证新响应解析与 usage，未加载本机密钥或调用 Qwen。

获准后的接入仍需：真实资格适配/品牌证据、服务端审批范围校验、供应商地域与保留保障、保存删除生命周期、新 sidecar 检查点与预算限制。
不能仅移除 synthetic 检查或启用按钮。`real_pipeline.run_real_analysis` 本轮保持始终拒绝。

## 本地验证

在仓库根目录、已激活 `.venv`：

```sh
python -B -m unittest discover -s Agent/tests -v
python -B Agent/consumer_needs.py --purpose improvement
python -B Agent/consumer_needs.py --purpose competitor
```

两个命令都使用固定合成数据，无联网/密钥/Qwen 调用，分别创建独立运行目录并打印 Markdown 路径。
在 `outputs/test/pipeline/mock-*/` 内新增 `consumer_needs.json` 以及
`improvement_research_report.md` 或 `competitor_research_report.md`，旧流水线产物照常保留。
VS Code 打开报告，按 Command+Shift+V 预览。所有生成结果沿用 outputs 的 Git 忽略规则。
Web App 仅新增研究目的选择，真实分析按钮继续禁用；没有恢复正式界面的 Demo 功能。

## 跨视频汇总与公开部署前确认

本节于 2026-11-04 直接读取官方政策核对。API 数据可读、只读、内存存储、按视频折叠或本地使用，都不能自行推导用途合法合规。

官方 [Developer Policies](https://developers.google.com/youtube/terms/developer-policies) III.E.2 限制数据聚合，通常仅允许按其认可的共同内容所有者条件汇总并向该所有者展示。
III.E.4.h 限制新增派生数据；III.L 的修订适用于申请并获接受的分析用途。
当前程序会读取关键词下可能来自不同频道的视频，将去重评论总量和多个视频的评论放在同一会话展示；这触及需核实的聚合范围。
现有搜索字段也没有取得能证明共同内容所有者关系的授权信息，不能假定五个视频属于同一认可所有者。
即使每个视频分开显示，是否属于允许的原始多结果展示或受限聚合，也需要向 YouTube 提供界面和数据流确认；本项目不能据此宣布当前跨频道用法已经获准。

官方 [Additional policies for derived metrics and data storage](https://developers.google.com/youtube/terms/derived-metrics-policy)
提供申请渠道并列举 NLP 评论分析，但不是所有产品/品牌研究的自动许可。
应明确申请对跨无关频道获取/展示/去重总量、产品需求推断、品牌比较和第三方北京地域处理的具体适用范围。

公开部署前需确认：

1. 当前跨频道原始评论展示与读取数量汇总是否获准；是否需要限定内容所有者、移除汇总或完成额外用途审查。不得把本地运行解释为豁免。
2. Analytics & Reporting 申请对跨视频产品研究、需求字段、品牌比较和报告引用/下载/收费是否明确覆盖；配额获批不等于用途获批。
3. 百炼北京地域作为第三方处理者是否获接受；真实账号适用的训练、日志、保留、删除、子处理者和跨境条件需核实，不能承诺未核实的零留存。
4. 正式隐私政策/条款、YouTube 来源品牌与链接、Google 隐私链接、联系渠道、同意及删除请求流程。
5. 评论原文、来源证据、推断、检查点、含引文报告、缓存和供应商副本的保留/刷新/删除机制。政策中的较长统计保留期限不适用于原文；短期内存预览也不免除用途限制。
6. 审查方可验证的数据流、API 端点/配额、只读访问、安全与日志脱敏，以及仅用合成数据展示的未启用分析设计。

本轮只完成核对与提示，未申请或取得许可、未公开部署。当前多视频只读入口未因本任务被自动撤销，但不能将其仍可点击当成平台认可。
