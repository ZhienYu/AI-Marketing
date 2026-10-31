# YouTube Analytics & Reporting 用途申请准备材料

核实日期：2026-10-31。状态：**准备稿，未提交，未获准真实派生分析**。
下面明确区分当前功能、拟申请用途、政策事实与仍待确认的问题，不应当作已获得许可的声明。

## 申请渠道与权限边界

YouTube 开发者政策 III.L 将额外派生分析许可与审查/申请相联系。
官方派生指标说明指向审查表 Section 5 的 **Analytics & Reporting** 用途，并列有评论 NLP 示例；
这不是自动批准所有市场研究。跨视频/跨频道的产品反馈汇总、品牌比较和第三方传输，应在申请中逐项说明并请 YouTube 确认适用范围。
[开发者政策](https://developers.google.com/youtube/terms/developer-policies)、
[额外派生指标政策](https://developers.google.com/youtube/terms/derived-metrics-policy)。

使用 [YouTube API Services 审查与配额申请表](https://support.google.com/youtube/contact/yt_api_form)。
如实选 Independent Developer/Sole Proprietor（如果符合实际）、Brands and Advertisers / Marketing Agencies 等实际受众、Analytics & Reporting 用途，
补充说明产品研究，不伪称频道所有者工具。当前表单允许 No change / Default quota；许可申请不必虚报需要更高配额。
提交和接受修订条款须由项目维护者自行操作；勾选或提交不表示已获得批准。

**这里申请的是 YouTube Data API 数据的分析用途，不是开通 YouTube Analytics API/Reporting API。**
后两者面向获授权的频道/内容所有者数据，并非任意品牌评论的通用通道。
现有公开搜索/评论读取使用 API Key，不涉及 Google 账户 OAuth；API Key 可用不代表分析获准。
依据：[Analytics & Reporting APIs 概述](https://developers.google.com/youtube/analytics/index)。

## 产品与技术说明

- 产品：Product Insight Agent，AI-Marketing/Agent；面向更广泛的海外产品营销人员，非仅 Amazon 卖家。
- 当前实现：本机 Streamlit 界面，用户输入产品名称/品类，主动点击官方 `search.list`，最多五个视频；用户选择一个后读取 `commentThreads.list` 最多十条公开顶层评论，无翻页，仅三条短预览；没有抓取、音视频下载、隐藏端点、回复采集或写入 YouTube。
- 当前处理：结果位于会话内存；不保存真实评论、不运行资格/NLP/派生指标、不发送 Qwen、不生成真实报告；分析按钮和后端接口均关闭。真实分析未实现，不能在申请时宣称已上线。
- 拟议用途：在覆盖范围明确的许可下，将与产品相关的使用体验、购买咨询、一般讨论、视频内容反馈和无关互动分开；对明确产品反馈做属性/情绪分类；在保留证据和不确定性的前提下比较不同品牌的样本反馈，形成 Agent 独立研究报告。
- 跨视频范围：可能涉及无共同内容所有者的多个公开视频/频道。评论不一定来自购买者；不将视频标题视为评论的品牌归属证据。不建立评论者档案，不推断受保护属性，不做骚扰性创作者排名，也不把 YouTube 样本说成整个消费市场。
- 数据字段：关键词、视频 ID/标题/频道名/发布日期、评论 ID/正文/发布时间/来源链接、UTC 采集时间；后续元数据包括品牌证据、资格理由/强度、来源有效期、模型/版本、派生结果和输入指纹。不收集评论者账号资料或 OAuth token。
- 展示：YouTube 来源与可回溯链接；未来派生分类和研究结论明确为 Agent 独立生成，非 YouTube 官方指标。原始 API 数据与派生输出分开；不改写原始搜索结果冒充官方排序。

## 阿里云百炼：必须单独说明的第三方处理

拟使用阿里云百炼北京地域 `qwen-plus` 做推理，而非本机模型。现有 `classify_qwen` 用户消息只含 `review_text`，
但正文自身仍可能含个人信息，因此“没有发送用户名字段”不等于匿名化。未来应在获准范围内最小化和处理个人信息，
不发送 API Key、Google token、来源 URL、频道身份等模型无需的数据；本地保留关联证据。

申请时说明供应商实体/产品、北京处理地域、网络传输、提示词/响应、日志与保留、删除流程、子处理者、跨境/隐私适用性及禁止训练用途；
请 YouTube 明确是否接受该第三方推理。最终用户同意不能代替 YouTube 许可或第三方内容权利。

**尚未核实本账号北京地域的合同性保留/删除保障，不承诺零留存或立即删除。**
国际站官方 ZDR 文档限定了站点、地域、模型和开通条件，不能据此声称现有北京账号已具备 ZDR。
需向阿里云取得适用于实际账号/地域/模型的服务协议、数据处理条款和删除/日志说明；在不满足批准条件时继续关闭，必要时另选获准处理方案，不能自行切换供应商绕过审查。
参考：[阿里云国际站数据保留/ZDR 说明](https://www.alibabacloud.com/help/en/model-studio/data-retention-policy)。

## 保存、刷新和删除计划

当前实际：仅会话内存短预览；点击清除、改关键词或选片可移除相应结果，停止进程清除服务器会话内存。
不承诺浏览器关闭即同步完成服务端清理，不提供真实评论导出；现有测试文件均为合成数据。

拟申请并在启用前实现的生命周期：

| 数据 | 拟议最小保留/清理方案（未实现） |
| --- | --- |
| 原始评论、标题、频道名、模型输入副本、含原文引用的报告 | 默认七天，到期删除；若业务确需更久，必须执行适用的刷新/删除机制，不把 30 天当成任意用途许可 |
| 纯派生统计/标签 | 默认仍七天；如需延长另明确申请，不自动采用最长保留上限 |
| 来源/品牌证据与检查点 | 与原始证据关联到期；不能用指纹或缓存永久保留已失效证据 |
| 供应商处理副本及备份/日志 | 以核实的合同和批准条件为准，须能满足删除要求；无法控制则不启用 |
| 用户/相关数据主体删除请求 | 建立正式联系渠道和请求流程，尽快完成且遵守适用政策期限；删除关联原文、缓存、可识别派生记录与受控报告，必要时重算/撤回 |

政策事实：获准的统计/派生数据保留可能扩展到 36 个月；评论正文等仍受 30 天刷新/删除规则约束。
用户要求删除相关存储数据时，开发者政策要求尽快处理并在七个日历日内完成。
较长期限不适用于所有数据，报告里的原文不因放入报告而成为纯统计。
[额外派生指标政策：Data Storage](https://developers.google.com/youtube/terms/derived-metrics-policy)、
[开发者政策：III.E.4](https://developers.google.com/youtube/terms/developer-policies)。

计划按 `comment_id` / `review_id` 建立删除索引，刷新确认来源删除/私有化后使证据失效，删除或更新受控报告。
下载到用户电脑的报告不能远程保证删除；公开产品前必须确定导出范围、到期标识、接收方义务和删除通知安排，不能声称已有全链路撤回能力。

## 英文用途说明草稿（需按真实情况补齐后手动提交）

Product Insight Agent is a local prototype for product marketers and marketing agencies researching overseas consumer hardware. A user enters a product name or category, reviews official YouTube search results, and explicitly chooses a video. The current implementation retrieves at most five video results and at most ten public top-level comments from one selected video, without pagination. It retains only three shortened comment previews in session memory. It does not currently perform NLP, create derived insights, export real comments, or transmit comments to a model provider.

We request a determination on whether our proposed Analytics & Reporting use case is eligible: qualifying product-related feedback and producing independently generated product-aspect sentiment summaries and evidence-based reports across selected public videos, potentially from unrelated channels, with comparisons between explicitly identified product brands. These are product-feedback comparisons, not official YouTube metrics or claims of verified purchases, market share, sales, or representative market performance. Unknown brand attribution, insufficient evidence, and small samples will remain explicit. Questions, content feedback, and unrelated interactions will not be counted as product praise or complaints.

Subject to specific approval, we propose sending only the necessary comment text, after applicable privacy minimization, to Alibaba Cloud Model Studio's Qwen inference service in Beijing. We request confirmation that this third-party processing, its location, intended outputs and cross-channel aggregation are within the permitted scope. We do not propose model training, individual profiling, sensitive-attribute inference, scraping, or redistribution of a raw comment dataset. Provider retention and deletion safeguards for our actual account remain to be verified before activation; we are not claiming zero retention.

Our proposed default retention is seven days, with linked deletion of source evidence, checkpoints and controlled reports. Any longer retention, quotations in exports, and provider copies will follow the scope and conditions confirmed during review. We will distinguish our derived outputs from YouTube-sourced API data and provide source links, collection dates, sample limits and a deletion contact. Analysis remains disabled until the applicable authorization, provider safeguards and lifecycle controls are confirmed and implemented.

## 维护者下一步操作

1. 备齐实际 Google Cloud 项目号（不是 API Key）、维护者/技术联系人、实际业务类型及受众、当前原型说明。不要在申请附件放密钥、`.env` 或真实评论数据集。
2. 补齐可公开访问的隐私政策、服务条款、删除联系人和明确的 YouTube/Google 链接；当前本地说明不能冒充已发布正式政策。申请表要求 HTTPS 入口及政策地址，不能捏造 localhost 的公开访问能力；本轮不部署，访问/演示安排需如实向审查方说明并补齐。
3. 准备当前真实只读功能的截图/录屏，以及**仅用合成样例**展示的拟议分析流程，清楚标注后者未启用。没有 Demo UI 不妨碍在离线审查材料中展示合成结果。表单对不提供测试账号的内部工具要求端到端录屏；不要填写不存在的账号。
4. 手动打开申请表，选 Section 5 → Analytics & Reporting，说明原始 Data API 端点和新用途，完整披露跨频道、产品品牌比较及百炼处理；不替代成频道经营分析来提高通过率。仅在理解条件后自行接受相应条款和提交。
5. 核实当前 Console 配额再填申请量。本次限一页搜索＋一页评论，暂时故障最多各两次请求；不翻页、不自动跨视频。官方目前把 search.list 单独计额，默认 100 次/天；其他端点默认共用 10,000 单位/天，commentThreads.list 为 1 单位/次。重试也计额，以项目实际分配为准。[官方配额计算说明](https://developers.google.com/youtube/data/determine_quota_cost)。
6. 获取 YouTube 对具体范围的书面确认，及阿里云适用条款；按 [接入设计](REAL_DATA_PIPELINE.md) 实现审批校验、真实资格适配、数据生命周期和测试后，再以新的开发任务启用完整流程。

待 YouTube 明确回答：跨无关频道的产品研究是否属于可接受用途？跨品牌汇总是否被修订范围覆盖？评论正文能否发往上述供应商/北京地域？哪些文本/标签/报告可存储或下载、期限和删除条件是什么？未来面向公众/收费是否需另行审查？
任何一项未覆盖都不能靠 API 调用成功或用户勾选来推定。
