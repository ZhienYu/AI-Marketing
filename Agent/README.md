# Product Insight Agent

An AI-powered tool for consumer insights and competitive intelligence.

## Project Status
MVP Development

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
