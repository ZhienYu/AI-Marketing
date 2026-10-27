# Product Insight Agent

An AI-powered tool for consumer insights and competitive intelligence.

## Project Status
MVP Development

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
