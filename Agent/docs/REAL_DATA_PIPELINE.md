# Real Data → Qwen → Report：接入设计（尚未启用）

更新：2026-10-31。目标用户为海外市场营销人员；主输入为产品名称或品类，CSV 仅为备用适配方式。

## 本次最小改动

Web App 移除 Demo 入口，直接使用现有 YouTube 搜索、选片和评论预览接口。
`orchestrator.preview_live_video` 仅增加成功读取后的 UTC `collected_at`，不改变原有评论内容或请求次数。
`real_pipeline.build_read_only_preview` 只复制来源元数据、截断前三条展示文本并添加未评估占位字段，
不执行 NLP。`run_real_analysis(records, *, model="qwen-plus", max_reviews=10)` 在访问输入前始终抛出
`AnalysisNotAuthorized`；没有 `.env` 开关、前端勾选或伪造审批 JSON 可以启用它。

原有 Mock 命令、合成 fixtures、分类、反馈筛选、洞察和报告模块均保留。
这些旧命令不是任意真实 YouTube 数据的授权入口；本次也没有对旧 CLI 作全局权限改造。
当前接口明确拒绝真实分析，真正的端到端协调实现留待许可范围和数据处理条件确认之后。

## 接口与现有代码复用

| 阶段 | 已有接口 | 获准后的最小接入工作 |
| --- | --- | --- |
| 发现视频 | `orchestrator.discover_live_videos(query, live=True)` | 原样复用；保持最多五条、默认相关性、无翻页；当前不增加自动选片或跨视频读取 |
| 读取评论 | `orchestrator.preview_live_video(discovery, video_id, live=True)` | 复用官方单页读取及重试；将完整响应交给受控协调层，另生成 UI 短预览，不能把截断预览作为分析原文 |
| 输入校验 | `validate_reviews.load_reviews(path)` | 可选 CSV 兼容适配；正式用户无需上传 CSV。需要内存校验时提取纯校验逻辑，保留现有 CSV 接口 |
| 反馈资格 | `qualify_feedback.qualify_feedback` / `qualify_batch` | **目前只接受 `is_synthetic=True`，且词表和 Demo 品牌目录很窄。不能直接用于真实评论，也不能把真实评论改标为 synthetic 绕过限制。** 获准后抽取共同纯规则，新增受控真实适配、明确品牌目录和多语言/歧义回归测试，保留合成保护 |
| Qwen | `classify_reviews.classify_qwen(review, settings, model)` | 复用北京地域、JSON 结构校验、Token 统计、错误处理；当前只将 `review_text` 放入用户消息。以后先审查、最小化并按获准范围处理第三方发送内容 |
| 批处理与断点 | `analyze_batch` / `load_checkpoint` / `review_fingerprint` | 复用检查点合并与模型/输入兼容校验；注意 `analyze_batch` **会立即写文件**，仅在获准持久化和生命周期管理已实现后接入；不得直接从当前 Live 预览调用 |
| 洞察 | `generate_insights.generate_insights(classified)` | 复用同评论/同属性/同情绪去重；unknown 不进入品牌比较；资格类别另表展示，咨询不当作差评 |
| 报告 | `generate_report.render_report(insights, classified, reviews, dataset="real")` | 复用配对校验、原文证据和真实/合成隔离；传入完整且匹配的原始记录；补充采集窗口、筛选范围、样本偏差和派生内容标识 |

## 数据契约

当前只在内存保留三条短预览：

| 字段 | 当前来源／含义 |
| --- | --- |
| `review_id` | `youtube:<comment_id>`，跨视频运行也以评论 ID 去重 |
| `comment_id`, `video_id` | 官方评论 ID、用户所选搜索结果 ID |
| `review_text`, `text_is_preview` | 最多 240 字符的安全展示文本；`text_is_preview=True`，不能用作模型输入或证据原文存档 |
| `published_at` | API 提供的评论发布时间 |
| `collected_at` | 本机成功读取这一页后的 UTC 时间，和发布时间分开；不是评论更新时间或 YouTube 的认证时间 |
| `source_platform`, `source_url` | `youtube` 与现有模块提供的评论深链接，不合成外部引用或新 URL |
| `brand` | `unknown`；不根据标题、频道、关键词或选片顺序推断 |
| `brand_attribution` | `{status: unverified, method: none, evidence: []}`，只是未归属状态 |
| `evidence_quality` | `{status: not_assessed, usage_evidence: null, verified_purchase: false}`；false 表示未验证，不表示认定没有购买 |
| `feedback_type`, `analysis_status` | `null`, `not_analyzed`，不生成分类、情绪或品牌统计 |
| `is_synthetic` | 传递输入标记；测试响应依然标为 synthetic，不能包装成真实研究证据 |

获准后建立完整记录和按 `review_id` 索引的 provenance sidecar：保留以上来源字段，使用完整原文，
增加 `run_id`、采集查询、所选视频、`last_refreshed_at`、`expires_at`、审批范围/版本、原文指纹、
品牌明确引文与人工核验记录、反馈分类理由/歧义、适配器和提示词版本、模型和 Token 用量。
来源元数据不能因旧分类 JSON 只保留部分字段而丢失；sidecar 随检查点和报告共同校验及删除。
同一评论若涉及多个品牌且归属不明确，不强塞进单一品牌；保留 unknown/人工复核。

## 获准后的控制流程（设计，不是可执行开关）

1. 开发者核对书面审查结果与实际项目/用途：跨频道视频、评论 NLP、产品/品牌比较、第三方北京地域处理、输出和保留方式必须分别被覆盖；范围不明继续关闭。
2. 实现服务端维护的审批记录和逐阶段校验，包含有效期、用途、可处理数据、供应商、地域、保留周期和输出限制。用户不能通过网页或输入记录自授许可，审批失效立即停止。
3. 用户明确发起搜索并选片；先仅一个视频十条评论。多视频自动筛选和汇总另作受限增量，不能把“最多五个搜索结果”误作当前已收集五个视频的评论。
4. 在获准的内存／存储边界内校验原文、来源、重复 ID。先资格筛选和人工复核；保留购买咨询、一般讨论、使用体验、内容反馈和无关类别，未知/歧义不晋升为体验证据。
5. 仅对符合条件、处理范围内的评论按显式数量/预算上限调用 Qwen；用户能看到将发送什么和供应商地域。去除不必要的个人标识；不得用于训练、个人画像或受保护属性推断。
6. 检查点兼容不仅检查 review_id、文本、模型/分类结构，还应检查资格版本、品牌证据、来源有效性和审批范围；旧缓存失效不能静默复用，也不能未经用户操作自动重试付费调用。
7. 合并成功结果后复用洞察与报告。统计只来自成功分类且证据合格的记录；失败保留原因、不编造。unknown 不纳入品牌结论；小样本标 Insufficient Data，未提及不等于满意。
8. 输出写入独立 `outputs/real/<run_id>/`（前提是该存储和输出已获准），标明 Agent 独立分析、非 YouTube 指标；附采集时间、评论来源和范围限制。下载正文、引用和分发方式也要在审批范围内。
9. 上线前先实现按 comment_id/review_id 关联的到期清理、来源刷新/删除检测、供应商删除处理和报告撤回/重算。对包含评论原文的报告不能只按统计数据的较长期限保留。

当前没有实现这些真实分析步骤；不要用删一行 raise 或改布尔值代替它们。

## 验证范围

原有离线全流程测试仍验证合成输入 → 资格 → 分类 → 洞察 → 报告。
新的界面测试使用自编合成响应验证真实读取的界面边界；新的接口测试验证拒绝分析发生在任何数据访问、密钥读取、文件写入和模型调用之前。
没有对真实消费者评论运行资格判定、NLP、派生统计或模型分析。

许可申请材料与外部依赖待办见 [YOUTUBE_ANALYTICS_APPLICATION.md](YOUTUBE_ANALYTICS_APPLICATION.md)。
