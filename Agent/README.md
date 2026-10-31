# Product Insight Agent

An AI-powered tool for consumer insights and competitive intelligence.

## Project Status
MVP Development

## Milestone 2.8：Consumer Feedback Qualification（合成数据最小版）

新增独立 `qualify_feedback.py`，以保守英文规则实际识别输入，不调用 AI，也不是按 review_id 查预设标签。
命令只读取新编写的合成 fixture；底层函数也要求每条 `is_synthetic=true`，拒绝真实或未标记的输入。
不读取 `.env`、不访问 YouTube、不保存评论、不修改现有 Qwen／洞察／报告流程。
DemoAqua、DemoPool 和型号均为虚构，例句自行编写，不来自真实 YouTube 评论。

在 Mac VS Code 的仓库根目录终端运行：

```sh
python3 -B Agent/qualify_feedback.py --summary-only
python3 -B Agent/qualify_feedback.py
python3 -B -m unittest discover -s Agent/tests -v
```

第一条只看数据质量摘要，第二条还显示每条反馈的判定、理由、原文证据和复核项，输出仅在终端。
20 条合成例子预期：可用产品反馈候选 8 条、其中使用体验候选 3 条、购买咨询 5 条、
视频内容反馈 2 条、无关/不明确互动 2 条；全部提示 `Insufficient Data`。
反馈类型可以重叠，不能把这些数字相加作为总数。

### 输出语义

| 字段 | 含义 |
|---|---|
| `primary_type` / `feedback_types` | 五类中的主类型／可重叠类型列表 |
| `product_sentiment` | 明确针对产品的 Positive、Negative、Mixed，或 Not Expressed / Unclear |
| `content_sentiment` | 针对视频、讲解或剪辑的情绪，独立保存，不混入产品情绪 |
| `usage_evidence` | 自述使用、无使用证据或转述歧义，保留支持句；`verified_purchase` 始终为 false |
| `feedback_scope` | 明确型号 `product`、仅品牌 `brand`、仅品类 `category` 或 `unknown` |
| `brand` / `product_model` | 仅在正文中匹配配置目录的明确名称，不使用视频标题或频道名猜测 |
| `qualification_status` | qualified / ambiguous / insufficient evidence |
| `evidence_strength` | strong / moderate / weak / insufficient evidence；是文字直接性规则，不是真实性概率 |
| `eligible_for_product_insights` | 有明确目标、实质产品陈述且无已识别歧义的候选；可能是意见或事实，不必是亲身体验 |
| `eligible_as_usage_review` | 上述候选中另外具有明确的第一人称使用／运行证据 |
| `reasons` / `ambiguities` / `evidence` | 判定理由、人工复核项和输入原文片段 |

五类为：Actual Usage Experience、Purchase Inquiry、Product Discussion、Content Feedback、Irrelevant/Unclear。
例如：

- `price?` 或 `Is DemoAqua R1 expensive?`：购买咨询、Not Expressed，不自动算价格差评。
- `DemoAqua R1 is overpriced.`：产品意见，可为负面，但没有使用或购买证据。
- `I bought DemoAqua R1 yesterday.`：只有购买陈述，不能当作使用体验或实质产品评价。
- `My DemoPool X2 gets stuck...`：有自述使用结果，仍不等于平台验证购买。
- `Great video. My DemoPool X2 broke...`：视频情绪正面、产品情绪负面，分别记录。
- 仅泛指品类的反馈保留 `brand=unknown`；多品牌、转述、引用、部分否定或不确定表达优先复核。
- 仅 `I used it...` 而无法识别目标时，保留使用陈述，但不自动送入有效商品评价池。

### 数据质量摘要与边界

摘要包含各类型数量、合格候选数、使用体验候选数、ambiguous / insufficient evidence 数量、
已知品牌候选样本量和未知品牌候选数。同一 review_id 只允许一次，重复 ID 直接报错。
20 条样本阈值仅沿用开发阶段提醒，达到阈值也不代表有市场代表性。
四条文字带使用陈述的例子中，一条目标不明，所以只有三条进入使用体验候选池。

这是有限英文模式的最小原型，不是通用语言理解或可靠的生产过滤器；
复杂反讽、长句、跨句指代、多语言及真实品牌目录都可能识别不足或出错，需后续人工标注评估。
规则能判定句子表达了什么，不能核实评论者实际拥有产品，也不能证明产品事实为真。
识别不到情绪使用 Not Expressed，不等于满意；无法识别模式时使用 Unclear/insufficient evidence。

### 未来衔接（本阶段未接入）

计划流程：数据源读取 → 资格筛选 → 分流与人工复核 → 产品属性分类 → 分池统计 → 报告。
未来适配器应保留原始来源、ID 和正文，并将 qualification 作为附加元数据，不覆盖原文和现有缓存指纹。

1. `eligible_as_usage_review` 可进入亲身体验候选池；其他合格产品意见与事实独立成池，报告分别注明。
2. Purchase Inquiry 用于购买信息需求，不直接作为痛点/负面情绪；Content Feedback 和无关互动不进入产品评价统计。
3. 有询问又有明确独立产品陈述时可以保留双标签，只分析有证据支持的陈述。
4. ambiguous / insufficient evidence 先复核或排除；未知品牌可进入品类研究，不进入品牌横向比较。
5. Qwen 应继续只提取有文字支持的属性，不把 Not Expressed 咨询补成 Negative，也不把自述使用标为 verified purchase。

新增 `tests/test_qualify_feedback.py` 与 `tests/fixtures/feedback_qualification_synthetic.json`，
覆盖五类、咨询无负面、使用与购买区别、目标归属、复合反馈、否定、多品牌、样本摘要和真实输入拒绝。
没有新增真实数据入口；未来启用真实评论前须单独完成用途授权、人工评估与适配开发。

## YouTube 评论连接诊断

原来的 `Connection failed or timed out` 合并了 `URLError`、`TimeoutError`、`OSError` 和
`HTTPException`，不能据此判断视频是否关闭评论。现在错误包含安全的分类、阶段与异常类型，
不输出原始异常消息、Key、完整请求地址、请求头或原始错误正文。

| category | 含义 |
|---|---|
| `dns` | DNS 解析失败，如 `URLError(gaierror)` |
| `open_timeout` | 打开响应超时，可能发生在连接、代理、TLS 或等待响应头期间 |
| `read_timeout` | 已进入正文读取阶段后超时；也可能发生在读取 HTTP 错误正文时 |
| `ssl_certificate` / `ssl` | TLS 证书校验失败／其他 SSL 错误，不禁用证书校验 |
| `connection_reset` / `connection_refused` | 连接被关闭、重置或拒绝 |
| `incomplete_read` / `http_protocol` | 正文未读完整／HTTP 传输协议错误 |
| `http` / `youtube_api` | 已收到 HTTP 错误响应；显示 403/404 等状态及已识别的 API 原因 |
| `invalid_json` / `network_other` / `unexpected` | 无效 JSON、其他网络错误或其他请求处理异常 |

阶段为 `open`（打开响应）、`read`（读取正文）、`close`（关闭响应）、`decode`（JSON 解码），
或 `http_response`（已收到 HTTP 错误）与 `read_error_body`（读取错误正文）。
`urllib.open()` 把连接和等待响应头封装在一起，所以 `open_timeout` 不能进一步证明是 TCP 连接超时；
程序明确保留这一不确定性，不把它误报为关闭评论或某个视频不可访问。

诊断示例（非真实测试结果）：

```text
[category=dns; stage=open; exception=URLError(gaierror)] ...
[category=read_timeout; stage=read; exception=TimeoutError] ...
[category=youtube_api; stage=http_response; http=403; reason=commentsDisabled; status=unavailable] ...
```

`commentsDisabled` 表示评论关闭；`videoNotFound` 表示视频不存在或该请求不可访问；
`quotaExceeded` 提示配额问题，`API_KEY_SERVICE_BLOCKED` 提示 Key 服务限制。
若 HTTP 错误正文也读取超时，仍保留已收到的 HTTP 状态，并追加错误正文的读取阶段诊断。
仅输出已识别的固定 API 原因／状态；未知字段显示 `unrecognized_or_unavailable`，不回显可能夹带敏感信息的原文。

先运行全部离线测试：

```sh
python3 -B -m unittest discover -s Agent/tests -v
```

之后在 Mac 终端自行逐条测试，不使用循环或重试脚本：

```sh
python3 -B Agent/youtube_comments.py --live "ecc6FsplkQo"
python3 -B Agent/youtube_comments.py --live "HyIXFKNTyf8"
python3 -B Agent/youtube_comments.py --live "aMdQpJ9ur5E"
python3 -B Agent/youtube_comments.py --live "KCOkaweKnu0"
```

第一条可作已知曾成功的对照，但不保证本次也成功。每条命令最多一次请求、十条顶层评论，
最多预览三条，不保存评论、不调用 Qwen、不自动重试。
可反馈 `category`、`stage`、`exception`、`http` 和 `reason` 帮助定位，无需提供密钥或评论正文。

## Milestone 2.7：按产品关键词发现 YouTube 视频

新增独立 `youtube_search.py`，默认 Mock。复用现有 YouTube Key 加载、错误脱敏、
重定向保护和终端文本清理，不修改 `youtube_comments.py` 或现有分析模块。
开发和测试只使用合成 fixtures 与假凭证，不读取实际 `.env`，不发送真实请求。

在 Mac VS Code 中打开 `AI-Marketing` 文件夹，选择「终端 → 新建终端」，先运行：

```sh
python3 -B -m unittest discover -s Agent/tests -v
python3 -B Agent/youtube_search.py "Robotic Pool Cleaner"
```

Mock 显示 `MOCK — SYNTHETIC DATA; no API request`，最多列出五个合成视频。
Mock 是固定示例，不是真的根据任意输入找到了对应产品；不要拿合成 ID 发起真实评论请求。
关键字须为 1–200 字符，含空格时放在双引号内。

### 你自己决定是否运行首次真实搜索

现有 `.env` 中的 `YOUTUBE_API_KEY` 无需更名。只有显式 `--live` 才由本机程序读取它。
运行：

```sh
python3 -B Agent/youtube_search.py --live "Robotic Pool Cleaner"
```

把双引号里的内容换成你自己的产品关键词即可。成功时应看到：

```text
LIVE — official YouTube search response
Returned N video(s), maximum 5; relevance order preserved. No pagination.
[1] 视频标题
channel=频道名称; published_at=发布日期
video_id=...
https://www.youtube.com/watch?v=...
```

`N` 可以为 0–5；少于五条不会自动补页，没有结果时会明确提示，不编造视频。
只发送一次官方 `search.list` 请求：`part=snippet`、`type=video`、`order=relevance`、`maxResults=5`。
使用 YouTube 默认的相关性顺序，不自行评分或重排。不会查询频道详情、播放视频、下载视频或获取评论。
结果只在终端展示，不写入文件。返回结构中的 `title`、`channel_title`、`published_at`、
`video_id`、`video_url` 可供后续候选筛选模块使用；当前没有自动选片或品牌归属推断。

### 手动选择视频，再读取评论

查看搜索结果并自行选定一个视频，把它的 `video_id` 替换进下面命令：

```sh
python3 -B Agent/youtube_comments.py --live "选定视频的11位ID"
```

上面是替换模板，不能原样运行；也可以粘贴该视频完整 URL，并保留双引号。
这是第二个独立的 API 请求，只有你运行该命令才会读取最多十条公开顶层评论、最多预览三条。
不会自动对全部搜索结果取评论；不保存真实评论正文，不调用 Qwen，不做情绪或竞品分析。
视频标题和频道名称不能证明评论者使用了某个品牌，评论品牌仍为 `unknown`。
有的视频关闭评论，读取失败时请自行选择另一个，不会自动转试其他视频。

### 搜索配额与错误处理

截至本次核对（2026-10-31），官方搜索文档说明：默认 **100 次 search.list 调用/日**，
每次消耗独立 **Search Queries** 配额桶的 **1 单位**。
它不等于“返回五个视频扣五次”，也不要继续按旧资料的每次 100 通用单位估算。
其他端点的默认共享配额为 10,000 单位/日；具体以你项目 Cloud Console 的实际配额为准。
再运行评论程序是另一次请求，不会重做视频搜索。重复执行搜索会再次消耗配额；错误请求也可能计入用量。
配额用完就停止，等待重置或按官方流程申请，不通过多项目规避。

参考：[search.list 官方参数与配额](https://developers.google.com/youtube/data/reference/rest/v3/search/list)、
[官方配额概览](https://developers.google.com/youtube/data/getting-started#quota)。

- 缺少关键词、空白或超长关键词：先在本地报错，不读 Key、不发请求。
- 400：核对关键词、Key 和项目配置。
- 403：检查 API 是否启用、Key 的 API／应用限制、Search Queries 的实际配额。
- 429、超时或网络错误：不自动重试，确认网络和配额后自行再运行。
- 空结果：改用更具体或不同的产品词；不是程序失败，也不构成市场不存在的证据。
- 错误不会输出 Key、带 Key 的请求地址或原始服务错误正文。不要把 Key 放进命令、截图或聊天。

退出码：0=成功（包括空结果），2=输入、配置、请求或响应错误。
新增 `tests/test_youtube_search.py` 和 `tests/fixtures/youtube_search_mock.json`；
覆盖离线默认、单次五条、顺序、配额相关参数、手动接续评论、错误脱敏和不写文件。
本阶段仅实现关键词发现，后续可在归一化结果上添加人工审核的候选筛选与数据源适配器；
不将搜索排名、视频标题或频道归属当作产品质量、真实消费者身份或品牌证据。

## Milestone 2.6：YouTube 公开评论只读预览

独立程序 `youtube_comments.py`，仅使用 Python 标准库，不改变 Qwen、洞察及报告模块。
默认 Mock 离线模式，不读取 `.env`，不联网；只有你显式加 `--live` 时才使用本机密钥。
本阶段开发不主动请求真实 YouTube API，也不把真实评论交给任何 AI 服务。

### Mac VS Code 操作

打开 `AI-Marketing` 文件夹，选择「终端 → 新建终端」，先运行：

```sh
python3 -B -m unittest discover -s Agent/tests -v
python3 -B Agent/youtube_comments.py
```

应看到 `OK`，以及 `MOCK — SYNTHETIC DATA; no API request`。
Mock fixture 有四条合成评论，只预览前三条；链接仅是使用合成 ID 构造的格式示例，不是真实来源。
测试中的 `--live` 也全部使用假凭证和 Mock 网络，不会读取你的实际 `.env`。

### 自己运行首次真实读取

你已经在 `Agent/.env` 中配置 `YOUTUBE_API_KEY`；不要把其值放入命令或聊天。
程序从脚本旁的 `.env` 读取这一个配置，不采用 Qwen Key、不执行文件命令、也不做环境变量展开。
支持 `YOUTUBE_API_KEY=值`、单/双引号以及 `export YOUTUBE_API_KEY=值`；重复定义会报错。
API restrictions 应仅允许 **YouTube Data API v3**，同时确认该服务已在密钥所属项目启用。

把下方引号中的内容替换成你自己选的视频完整链接，保留双引号和 `--live`：

```sh
python3 -B Agent/youtube_comments.py --live "https://www.youtube.com/watch?v=你的视频ID"
```

上面是替换模板，不能原样执行。也可以只传真实的 11 位 Video ID：

```sh
python3 -B Agent/youtube_comments.py --live "你的视频ID"
```

支持标准 watch 链接、youtu.be 短链接、shorts、embed、live 链接；不会下载视频。
URL 中可能含 `&`，务必加双引号。不带 `--live` 时始终只看合成样例，不能据此认定真实 API 成功。

### 成功时应该看到什么

终端出现 `LIVE — official API response`，随后：

```text
Retrieved N public top-level comment(s); previewing at most 3. No pagination.
[1] comment_id=...; brand=unknown
published_at=...; video_id=...; source_platform=youtube
评论正文预览
评论定位链接
```

`N` 在 0–10 之间，并非所有视频都有十条公开评论。请求成功但没有评论时会明确说明。
每条正文最多显示 240 字符，去除终端控制字符；模块在内存中保留本页最多十条完整正文，退出后不持久化。
字段为 `comment_id`、`review_text`、`published_at`、`video_id`、`source_url`、
`source_platform=youtube`、`brand=unknown`，另有 `is_synthetic` 区分 Mock 和真实返回。
ID 来自 `topLevelComment.id`，不是外层线程 ID。

### 请求边界

- 只访问官方 `commentThreads.list`，固定 `part=snippet`、`maxResults=10`、`textFormat=plainText`、`order=time`。
- 仅一次 GET，不自动翻页、不读回复、不查询视频标题、不自动重试；不保存真实评论到 CSV、JSON 或日志文件。
- 仅请求必要字段，不读取评论作者姓名、头像等信息。终端预览本身包含真实文本，请勿额外重定向到文件或上传终端截图。
- 按官方文档该接口一次调用消耗 1 个配额单位；这与 Qwen Token 无关，重复执行会再消耗 API 配额。
- 使用公共 `textDisplay`，不是声称取得作者专属的 `textOriginal`；即使纯文本也可能与用户最初提交的文本不同。
- `source_url` 由返回的视频 ID 和评论 ID 构造，不是 API 提供的永久链接字段；评论删除、隐藏后可能无法打开。
- 不推断品牌、真实使用经历、情绪或竞品关系。只读测试成功不等于获准将数据用于后续 AI 衍生分析；后续另行确认用途。
- 退出码 `0` 表示成功预览（包括零条），`2` 表示配置、参数、请求或响应错误。

参考：[commentThreads.list](https://developers.google.com/youtube/data/reference/rest/v3/commentThreads/list)、
[评论字段](https://developers.google.com/youtube/data/reference/rest/v3/comments)。

### 常见错误

| 提示/情况 | 处理 |
|---|---|
| 缺少或无法读取 YOUTUBE_API_KEY | 自行确认 `Agent/.env` 路径、变量名、UTF-8 编码及引号完整；不要发出密钥 |
| Invalid video | 使用实际的 11 位 ID 或支持的视频链接，不使用频道/播放列表链接 |
| commentsDisabled | 视频关闭了评论，换一个已开启评论的公开视频 |
| accessNotConfigured | 在密钥所属 Google Cloud 项目启用 YouTube Data API v3 |
| 400 / key rejected | 检查本地 Key 是否有效、是否粘贴完整、是否属于正确项目 |
| 403 / restrictions | 检查 API restrictions、配额和应用限制；终端调用不适用网页 HTTP referrer 限制，可配置匹配的出口 IP |
| quotaExceeded / dailyLimitExceeded | 查看 Cloud Console 的实际用量与重置时间，不要循环重试或另开项目绕过 |
| videoNotFound / 404 | 核对 ID；视频可能已删除、私有或对该请求不可用 |
| 超时、连接失败、429、服务错误 | 检查本机访问 Google APIs 的网络及服务状态，等待后自行重试；不要绕过服务地域限制 |

新增测试 `tests/test_youtube_comments.py`，fixture 在 `tests/fixtures/youtube_comments_mock.json`，
二者仅包含合成示例与假凭证。没有改动现有分析输出或添加真实评论文件。

## Milestone 2.5：离线 Markdown 市场调研报告

新增 `generate_report.py`。报告不调用 Qwen，不加载 `.env`，不改写分类或统计 JSON。
默认读取现有的三个输入：

- `outputs/test/insights_mock.json`
- `outputs/test/classification_mock.json`
- `data/sample_reviews.csv`

在 Mac VS Code 中打开 `AI-Marketing` 文件夹，选择「终端 → 新建终端」，运行：

```sh
python3 -m unittest discover -s Agent/tests -v
python3 Agent/generate_report.py
```

在左侧展开 `Agent → outputs → test`，打开 `market_research_report.md`。
按 **Command+Shift+V** 打开 Markdown Preview；也可在编辑器右上角选择「打开侧边预览」。
这份报告使用现有九条合成评论及 Mock 分类，标题附近显示 `DEMO — SYNTHETIC DATA`，
包含 Executive Summary、Consumer Pain Points、Consumer Sentiment、Competitive Intelligence、
Business Opportunities、Sources & Methodology 六部分。

报告生成前会重新汇总分类并与输入 insights 完整比对；不一致时停止，请先用匹配的分类重新生成统计。
还会核对 CSV 中的原始 ID、品牌、来源和已有内容指纹；找不到对应原文或内容变化时拒绝生成。
报告保存为 UTF-8 Markdown，成功生成后可以重复覆盖这份报告；不会覆盖输入 JSON 或 CSV。
没有输入文件、没有成功分类、格式错误或证据不匹配时返回退出码 2，旧报告保持不变；成功为 0。

当前合成数据也已有真实 Qwen 分类时，可选择以下**纯离线**命令生成报告：

```sh
python3 Agent/generate_report.py --insights Agent/outputs/test/insights_qwen.json --classifications Agent/outputs/test/classification_qwen_resume.json
```

这仍然是 synthetic demo，且会覆盖同一份 `market_research_report.md`；输入文件不变。
如果需离线重新生成匹配的 Qwen 统计，先运行：

```sh
python3 Agent/generate_insights.py --input Agent/outputs/test/classification_qwen_resume.json
```

报告规则：每条评论对同一属性、同一情绪只计一次；每品牌显示成功分类样本量。
少于 20 条标记 `Insufficient Data`；不排名，不把零提及当作满意，不填造缺失来源链接。
原文和分类反馈分列，保留全部支持 ID。痛点文字仅规范大小写和空白，不自动合并语义。
商业机会最多三项，至少需要两条独立负面属性评论支持，明确标为待验证假设；
不足时显示 `Insufficient Evidence`。合成样本不能支持真实市场商业建议。

未来真实数据要求显式指定全部输入，且不能包含 synthetic 或 Mock 分类：

```sh
python3 Agent/generate_report.py --dataset real --insights /path/to/insights_qwen.json --classifications /path/to/classifications.json --reviews /path/to/authorized_reviews.csv
```

未来输出为 `outputs/real/market_research_report.md`；本阶段不运行真实数据流程。
所有报告继续由现有 `outputs` 忽略规则排除，不自动 Commit 或 Push。
新测试 `tests/test_generate_report.py` 覆盖六部分结构、样本与品牌计数、证据、去重、
陈旧统计拒绝、缺失输入、数据隔离及输入文件不被改写。

## 输出目录隔离

```text
Agent/
  classify_reviews.py
  generate_insights.py
  tests/                       自动化测试及 fixtures，位置不变
  outputs/
    .gitignore
    test/                      合成评论结果，包括真实 Qwen 调用的测试结果
      .gitignore
      classification_mock.json
      classification_qwen_one.json
      classification_qwen_batch.json
      classification_qwen_resume.json
      insights_mock.json
      insights_qwen.json
    real/                      预留真实消费者评论结果
      .gitignore
```

默认 `--dataset test`，路径变更不影响命令的其他参数。数据来源决定归类，
使用真实 Qwen API 不会使合成评论成为真实市场数据。
未来真实数据需显式使用 `--dataset real`；分类输入不得含 `source_platform=synthetic`，
Mock 也不能输出到 real。混合真实与合成数据的 CSV 请先拆分，程序不会把它们混存。
统计程序也校验数据来源，并支持同名参数。真实数据示例（不在本次执行）：

```sh
python3 Agent/classify_reviews.py --dataset real --mode qwen --input /path/to/real_reviews.csv --limit 3
python3 Agent/generate_insights.py --dataset real --input Agent/outputs/real/classification_qwen_batch.json
```

当前续跑文件已有 9 条成功记录时，下面命令应显示跳过 9 条、选中 0 条，且不读取密钥：

```sh
python3 Agent/classify_reviews.py --mode qwen --resume --limit 6 --dry-run
```

无需重新做旧格式迁移，也不要删除已有续跑文件。若仅存旧根目录检查点，程序支持读取旧路径；
新旧同名结果内容不一致时会拒绝选择，不会擅自覆盖或重新调用 API。
运行结果、迁移校验清单及其备份全部忽略；仅三个必要的 `.gitignore` 占位文件可加入 Git。
本次迁移逐文件核对 SHA-256，并将原始字节另存到 test 下的迁移备份目录。

## Milestone 2.4：续跑与离线竞品统计（当前版本）

仅用 Python 3.10+ 标准库。网站和服务器不变，不自动提交/推送。
本阶段开发只运行离线测试和 Mock，不读取你的 `.env`，不主动调用真实 API。
以下命令都在 VS Code「终端 → 新建终端」中，从 `AI-Marketing` 仓库根目录逐行执行。

### 先测试与查看 Mock 统计

```sh
python3 -m unittest discover -s Agent/tests -v
python3 Agent/classify_reviews.py --mode mock
python3 Agent/generate_insights.py
```

打开 VS Code 左侧 `Agent → outputs → test → insights_mock.json`。
预期 9 条成功分类，Brand A/B/C 的 `sample_size` 各为 3。
例如 Brand A 的 Battery Life 负面计数为 1；Brand C 的 Maintenance 正面计数为 2。
终端同时显示八类属性的品牌对比表，单元格格式是「正面/负面/中性；n=品牌样本量」。
该结果是合成评论与人工 Mock 答案的技术测试，不能当作真实市场证据或品牌排名。

### 保留已有三条 Qwen 结果：首次离线迁移

原始 `classification_qwen_batch.json` 永远不作为续跑的写入目标。
旧 2.3 格式只有 ID，没有评论内容指纹：程序可以核对品牌、来源、模型和分类结构，
但不能自动证明当时发送的正文与当前 CSV 相同。
请先自行确认：**前三条对应的 ID、正文与品牌自真实分析后没有改动，且使用的模型是 qwen-plus。**
只有确认后，运行这一条离线命令：

```sh
python3 Agent/classify_reviews.py --mode qwen --adopt-legacy --confirm-legacy-input
```

这条命令不读取 `.env`、不联网、不消耗 Token。
它将三条结果原样保留，并附上当前规范化输入指纹和 `legacy_input_attested=true`，
保存为新的 `Agent/outputs/test/classification_qwen_resume.json`。
该标记表示你确认了旧输入对应关系，不是程序自动证明了历史输入。
原始三条的文件保持字节不变；迁移不会覆盖已存在的续跑文件。
如果旧输入已变化，请保留原结果，先恢复对应输入或另开新研究，不要作不实确认。

### 先预览，再由你决定是否真实分析剩余六条

```sh
python3 Agent/classify_reviews.py --mode qwen --resume --limit 6 --dry-run
```

应看到跳过 3 条、选中 6 条待处理记录。这是纯离线预览，不读取密钥、不改结果文件。
确认无误且愿意使用 API Token 后，才自行运行：

```sh
python3 Agent/classify_reviews.py --mode qwen --resume --limit 6
```

这时本机程序才读取 `.env`，仅请求未成功完成的 ID 4–9，最多六次；前三条不再调用。
`--limit` 在续跑模式下表示**本次最多尝试多少条尚未成功的记录**，真实模式上限仍为 20。
结果合并至 `classification_qwen_resume.json`，逐条原子保存；旧三条仍保留在原批量文件及合并文件中。
再次执行同一命令时，会跳过所有已经成功的记录；如果全部九条成功，不加载密钥，不再调用 API。
失败记录下次仍可重试，超时请求可能已经计费；没有自动重试。

续跑前校验全部缓存成功记录的：唯一 ID、规范化整行输入 SHA-256（包括正文、品牌等）、
模型、模式、分类字段与属性枚举、分类提示词签名和结构版本。
发现不兼容就停止，不覆盖缓存或悄悄重新收费分析。CSV 中已完成 ID 消失或品牌变化也会拒绝续跑。
请勿同时在多个终端启动相同续跑文件的分析；当前按单进程顺序运行。

### 合并结果和统计字段

- `skipped_records`：保留并跳过的历史成功数量。
- `new_success_records`：本次新增成功数量。
- `classified_records`：合并后的成功总数量。
- `attempted_records` / `failed_records`：本次已完成尝试数 / 本次失败数。
- `unprocessed_records`：本次选中但因提前停止而尚未处理的数量；终端另显示超出本次 limit 的数量。
- `failures`：本次失败；`failure_history`：之前失败的历史，不会混入成功结果。
- `usage`：已有缓存加本次的累计已知 Token；有用量缺失时仍可能低估，不代表未收费。

成功结果的原有 JSON 字段保持兼容，新增 `input_sha256` 用于续跑验证。
中断或 API 错误时保留之前成功结果；退出码仍是 0=本次无失败，1=本次逐条失败，2=配置/输入/缓存/保存错误。
非续跑真实模式遇到已存在的输出文件会拒绝覆盖，避免意外丢失旧成果。

### 对真实分类结果做离线统计（也不调用 API）

```sh
python3 Agent/generate_insights.py --input Agent/outputs/test/classification_qwen_resume.json
```

输出为 `Agent/outputs/test/insights_qwen.json`。即使分类由真实 API 完成，输入评论仍是 synthetic，
不能称为真实消费者研究。也可以对原来的三条批量文件做统计，但 Brand B/C 将显示零样本。

统计口径：

- 只统计成功分类；失败不填造情绪。重复 ID 视为错误，不会重复累计。
- 每品牌每属性每情绪统计独立评论数，同条评论重复提及只计一次；同一属性正负反馈可各计一次。
- `brands` 中保存样本量、`aspect_counts`、`top_negative_aspects` 与 `top_pain_points`。
- `top_negative_aspects` 按标准属性汇总负面评论，保留支持 ID 和反馈示例。
- `top_pain_points` 按痛点文字统计，仅规范大小写和空白；不自动合并语义相似但措辞不同的痛点。
- `comparison_table` 包含八类属性的 Brand A/B/C 对比，额外出现的已知品牌也保留；未知品牌单独列出，不参与比较。
- 样本量是该品牌成功分类评论数；不足 20 条标记 `Insufficient Data`，零提及不表示不存在问题。
- 所有计数仅描述当前收集样本，不代表市场发生率、份额或品牌排名。

本阶段修改 `classify_reviews.py`、`tests/test_classify_reviews.py` 和本说明；
新增 `generate_insights.py`、`tests/test_resume_and_insights.py`。
生成文件继续由现有 `outputs/.gitignore` 忽略。

## 本地里程碑：检查评论 CSV

需要 Python 3.10+，仅使用标准库，无需安装依赖或配置 API Key。
在 AI-Marketing 仓库根目录运行：

```sh
python3 Agent/validate_reviews.py
python3 Agent/validate_reviews.py /path/to/reviews.csv
python3 -m unittest discover -s Agent/tests -v
```

默认读取脚本旁的 `data/sample_reviews.csv`，与运行时所在目录无关。
输出 JSON 包含导入、有效、无效、重复、排除数量，以及有效评论的品牌统计。
无效和重复记录列出 CSV 物理行号（多行评论取结束行）及原因/首次出现行。
脚本只读取文件，不改写原始数据，不联网，不输出评论正文、ID 或来源链接。

### 本阶段规则

- 表头必须包含 `review_id,review_text,source_platform,source_url,brand`，允许额外字段。
- 兼容 UTF-8 BOM 和文件首尾/记录间的空行；纯空行不计作记录，带分隔符的空记录仍须校验。
- `review_id`、`review_text`、`source_platform` 的值不能为空；字段首尾空白会移除。
- 所有列的值相同视为完全重复，只保留第一条有效记录；相同 ID 的不同记录为无效记录。不同 ID 的相同正文暂不合并。
- 列数错误为无效记录。无效、重复、有效三类互斥；总数 = 有效 + 无效 + 重复，排除 = 无效 + 重复。
- 品牌为空或为 `unknown`（不区分大小写）时保留并警告，不进入品牌统计；其他品牌按去除首尾空白后的原名分别统计。
- 来源链接为空或不是基本可用的 HTTP(S) 地址时，仅可用于内部流程测试并警告。不会访问链接或确认来源真实性。
- `source_platform=synthetic` 明确标为合成数据，始终不计入证据候选数量。非合成且链接格式可用的记录仅是候选，仍需人工核验。
- 退出码：`0` = 无排除记录（仍可能有警告）；`1` = 有无效或重复记录；`2` = 文件、编码、CSV 格式或表头错误。

现有样例预期：总数 9、有效 9、排除 0；Brand A/B/C 各 3 条；
9 条均为合成测试数据，证据候选为 0。这个样本用于跑通流程，不支持市场结论。
本阶段只做结构校验，不判断无关内容、广告、表情、情绪或产品痛点；尚未完成整个 PRD 的预处理要求。

根目录 `.gitignore` 忽略 `.DS_Store`、本地环境、Python 缓存及常见密钥文件。
它不会保护已追踪文件，也不能代替提交前检查；请勿把密钥写进源码或数据。
提交时逐个选择本阶段文件，不使用 `git add .`；提交和推送需你确认。

## Milestone 2.3：Product Aspect Classification & Batch Analysis

继续使用 Python 3.10+ 标准库，无需安装第三方依赖。
新增分类脚本默认使用人工准备的模拟返回值，不联网、不加载 `.env`、不消耗 Token。
真实模式通过北京地域百炼的 Qwen 接口，按 CSV 顺序逐条发送所选有效评论的正文；
原始 `review_id` 由本地程序附回，防止模型改写 ID。

### 在 Mac 的 VS Code 中运行

1. 选择「文件 → 打开文件夹」，打开 `AI-Marketing` 文件夹（左侧应看到 `Agent` 和 `网站`）。
2. 选择「终端 → 新建终端」。以下命令都在这个终端执行，每次复制一行并按回车。
3. 先运行不消耗 Token 的测试：

```sh
python3 -m unittest discover -s Agent/tests -v
python3 Agent/classify_reviews.py
```

测试显示 `OK` 后，第二条命令应显示已分类 9 条。
在左侧文件列表展开 `Agent → outputs → test`，打开 `classification_mock.json`。
如果没出现新文件，刷新文件列表。模拟输出预期为 3 条 Positive、4 条 Negative、2 条 Mixed。
这些是预先写好的测试答案，不代表 Qwen 已经分析过。修改样例正文或 ID 后，模拟模式会拒绝套用旧答案。

### 只分析 1 条的真实 API 测试

你的 `Agent/.env` 只会在你执行下面的真实模式命令时，由本机程序加载。
本阶段开发和自动测试不访问你的密钥文件；测试中使用临时假凭证和模拟网络返回。
请在 VS Code 中自行确认变量名为 `DASHSCOPE_API_KEY`（也兼容 `QWEN_API_KEY`），
不要将密钥复制到终端命令、聊天、代码或截图中。
支持 `名称=值`、单/双引号以及 `export 名称=值`，不执行文件中的命令，也不展开变量。
同名进程环境变量优先于 `.env`。

```sh
python3 Agent/classify_reviews.py --mode qwen --limit 1
```

这条命令会消耗实际 API Token，最多调用一次、只分析第一条有效评论；不会自动重试。
运行成功后打开 `Agent/outputs/test/classification_qwen_one.json`。
其中 `mode` 应为 `qwen`、`classified_records` 应为 `1`，`results[0].review_id` 应为 `"1"`。
第一条评论表达电池在清洁完成前耗尽，合理预期为 Negative，痛点涉及电池续航；
具体描述由模型生成，需要你人工核对，不能把本地模拟答案当作模型正确率。
`usage` 保存服务返回的已知 Token 数量（如果服务提供），不保存密钥、请求头或原始 API 返回。
重复执行真实命令会再次调用并消耗 Token。

默认模型为 `qwen-plus`，可以用 `--model` 指定你账户已开通且支持 JSON 输出的 Qwen 模型。
默认北京地址为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
如你的业务空间要求专属域名，可在本机 `.env` 自行添加非密钥配置 `DASHSCOPE_BASE_URL`，值为
`https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。
只接受北京地域的这两类地址，不接受其他地域或第三方地址。
接口及 JSON 参数依据[阿里云接口文档](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
和[结构化输出文档](https://help.aliyun.com/zh/model-studio/qwen-structured-output)。

### 自行选择真实批量测试

建议先运行上面的 Mock 和单条测试。确认愿意消耗 API Token 后，才选择运行以下命令之一：

```sh
python3 Agent/classify_reviews.py --mode qwen --limit 3
python3 Agent/classify_reviews.py --mode qwen --limit 9
```

这两条是替代选项，不必都运行。`--limit 3` 最多进行 3 次请求；`--limit 9` 最多进行 9 次请求。
每条评论对应一次请求，串行处理。必须显式提供 `--limit`，真实模式硬上限为 20；
实际处理数量为限制值与有效评论数中的较小值，无效/重复记录在调用前排除。
自定义 CSV 可加 `--input /path/to/reviews.csv`；Mock 仅支持原样例 ID 和正文。
批量结果位于 `Agent/outputs/test/classification_qwen_batch.json`，单条命令保留原来的 `_one.json` 文件名。

每条成功结果均包含原始 `review_id`、`brand`、来源信息、`is_synthetic` 和分类结果。
品牌由 CSV 附回，不由模型生成；例如第 9 条结果属于 Brand C，虽然正文提到了 Brand A。
合成标记来自原始 `source_platform=synthetic`，使用真实 API 也不会让模拟评论变成真实市场证据。

新增 `product_aspects` 是对象数组，每个对象包含 `aspect`、`sentiment`、`feedback`。
`aspect` 只能使用以下八类：

| 类别 | 本阶段含义 |
|---|---|
| Battery Life | 电池续航 |
| Cleaning Performance | 清洁表现 |
| Ease of Use | 安装、设置及操作便利性 |
| Price | 购机价格及配件价格 |
| Maintenance | 滤网清理、拆卸及维护 |
| Reliability | 卡住、故障及运行可靠性 |
| Customer Support | 客服与售后支持 |
| Other | 评论明确提到、但不属于前七类的反馈 |

每个属性的情绪只能是 Positive、Negative 或 Neutral；同一属性同时有正负反馈时分两项记录。
保留原有 `sentiment`、`positive_aspects`、`pain_points` 字段及类型，属性情绪需与原有反馈列表一致。
例如清洁好但续航差的分类片段为：

```json
{
  "product_aspects": [
    {"aspect": "Cleaning Performance", "sentiment": "Positive", "feedback": "Great cleaning performance"},
    {"aspect": "Battery Life", "sentiment": "Negative", "feedback": "Battery dies too quickly"}
  ]
}
```

### 查看进度、失败及 Token

输出的 `results` 仅包含成功分类，`failures` 单独记录失败评论的 ID、品牌和安全错误说明，
失败项不填充虚构的情绪或属性。响应格式错误或结构校验失败时记录失败并继续下一条；
网络超时、连接中断、HTTP 错误（包含权限、限流和服务错误）会停止后续调用，不自动重试。
每处理一条就原子保存进度；无法保存时停止，不再发起下一次请求。

- `selected_records`：本次选中的有效评论数。
- `attempted_records`：已完成处理尝试数，等于成功数加失败数。
- `classified_records` / `failed_records` / `unprocessed_records`：成功、失败、尚未处理数量。
- `status`：`completed` 全部成功；`partial` 已处理完但存在失败；`stopped` 因网络/API/配置错误提前停止。
- `started_at`：本次运行的 UTC 开始时间；`schema_version` 为 `2.3`。
- `usage`：所有服务已返回的 Token 数之和，包括响应可解析但分类无效的请求。
- `usage_complete_records`：收到完整 Token 统计的请求数；`usage_unknown_records`：统计缺失或不完整的请求数。

超时或未返回用量不代表免费，也不计作已知 0 Token；有未知数量时总用量可能低估，请查看百炼控制台。
每条成功/失败记录另存自己的 `usage`。Mock 的 `usage` 为 `{}`，不联网、不读密钥。
中途按 Control+C 可停止；磁盘检查点保留已完成部分，`status` 可能仍是 `running`，
正在进行的请求可能已经计费。当前请使用上方 Milestone 2.4 的 `--resume` 避免重调已成功评论。

### 结果与边界

- `sentiment`：Positive / Negative / Neutral / Mixed。
- `positive_aspects`：评论明确支持的正面反馈，英文短句数组；没有则为 `[]`。
- `pain_points`：评论明确支持的问题，英文短句数组；没有则为 `[]`。
- `product_aspects`：标准属性、属性情绪及具体反馈的对象数组；允许一条评论涉及多个属性。
- 同时有正负反馈时为 Mixed；无法提取产品反馈时为 Neutral。结构校验失败记入 `failures`，不产生成功分类；结构校验不能替代人工核对语义。
- 复用上一阶段的全部校验规则；无效与重复记录排除，统计和警告保存在输出的 `validation` 中。未知品牌仍可做评论分类。
- 单条正文限制 12000 字符，输出最多 1000 Token，超时 60 秒。超时或响应不合规仍可能计费，重新运行前先查看控制台用量。
- 退出码 `0` 表示本次全部分类成功；`1` 表示有逐条失败，检查 `failures` 和未处理数量；`2` 表示参数、输入、设置文件或保存失败。HTTP 错误只显示状态码；401/403 检查地域密钥和权限，429 检查配额/限流。
- Mock 新运行会覆盖对应测试 JSON；真实模式不覆盖现有输出，请按 2.4 说明迁移并续跑。开始前的参数/输入/设置文件错误会保留旧文件，请结合终端状态和 `started_at` 检查。
- `outputs` 中的生成文件被 Git 忽略，密钥文件继续被原有规则忽略；程序不修改 CSV、网站或服务器，也不自动提交/推送。

### 本阶段文件

| 文件 | 作用 |
|---|---|
| `classify_reviews.py`（更新） | 标准属性校验、带上限的批量 Qwen 请求、逐条保存、错误和 Token 汇总 |
| `tests/fixtures/mock_classifications.json`（更新） | 对应原始 9 条样例的多属性人工模拟返回值 |
| `tests/test_classify_reviews.py`（更新） | 品牌归属、多属性、批量上限、失败、检查点及用量汇总等离线测试 |
| `outputs/.gitignore` | 忽略生成结果，避免意外提交 |
| `validate_reviews.py`（沿用） | `load_reviews` 返回有效记录及校验统计 |
| `README.md`（更新） | 本阶段运行、检查结果和排错说明 |
