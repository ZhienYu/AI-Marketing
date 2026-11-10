# Product Insight Agent 本地版本

| 版本 | 本地目录 | Git 引用 | 本地入口 |
| --- | --- | --- | --- |
| Comment Only v1.0 | `<项目父目录>/AI-Marketing` | `main`，冻结标签 `comment-only-v1.0` | http://127.0.0.1:8514 |
| Video Enhanced | `<项目父目录>/AI-Marketing-Video-Enhanced` | `feature/video-enhanced`，从 `comment-only-v1.0` 创建 | http://127.0.0.1:8520 |

Comment Only v1.0 包含官方 YouTube API 评论发现和采集、内存 JSON、来源和证据校验、经许可的 Qwen 分析、费用预留、会话到期清除，以及 Phase K Dashboard。包含标准、Phase H 和 Phase K 三种评论规模。Phase J 是离线可测的评测工具，正式研究页不依赖任何评测样本清单。Video Enhanced 初始采用相同代码，视频分析和多 Agent 功能留待后续开发。

冻结版本的精确提交由 `git rev-parse 'comment-only-v1.0^{commit}'` 给出。该提交是 Video Enhanced 的起点。首次分支创建后，视频分支可以前进，稳定标签继续指向同一提交。

## 分别启动

在各自目录中使用该目录的 Python 环境。新建目录首次运行以下命令。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r Agent/requirements.txt
.venv/bin/python -B -m unittest discover -s Agent/tests
```

在 `AI-Marketing` 根目录启动 Comment Only。

```sh
.venv/bin/python -B -m streamlit run Agent/web_app.py --server.address 127.0.0.1 --server.port 8514 --server.headless true --browser.gatherUsageStats false
```

在 `AI-Marketing-Video-Enhanced` 根目录启动开发版。

```sh
.venv/bin/python -B -m streamlit run Agent/web_app.py --server.address 127.0.0.1 --server.port 8520 --server.headless true --browser.gatherUsageStats false
```

需要无外部请求的演示时，用相同启动命令将 `Agent/web_app.py` 改为 `Agent/business_research_preview.py`，并选一个空闲端口，例如 8521。选择合成示例。

## 环境隔离

- 直接在各自根目录打开 VS Code，并选择该目录的 `.venv/bin/python`。开发视频功能前用 `git branch --show-current` 确认当前分支是 `feature/video-enhanced`。
- 两个服务分别监听本机端口，运行会话在各自进程内。工作目录各自管理 `Agent/.env`、`Agent/config/research_access.json` 和 `Agent/.runtime/`。不要建立跨工作目录的链接或复制运行记录。
- Comment Only 保留现有本机配置。新开发目录默认无真实服务凭据和已批准配置。确需开启真实开发运行时，按已有本机安全流程分别配置，并为共享服务账号另行控制总额度。两个独立账本各自只统计本目录的预留，不能替代账号级额度。
- 视频开发分支不自动合入 `main`。Phase J 的本机实验配置及清单不属于稳定发布。实验清单如需保留，只放在 Git 忽略的私有位置。

## 恢复工作目录

从现有 GitHub 仓库重新获取时，在项目父目录运行以下命令。若目录已存在，先检查并备份本机配置和未提交改动，再决定是否重建。

```sh
git clone https://github.com/ZhienYu/AI-Marketing.git AI-Marketing
cd AI-Marketing
git fetch origin --tags
git worktree add ../AI-Marketing-Video-Enhanced feature/video-enhanced
```

如果本地尚无视频分支且 Git 未自动建立跟踪关系，改用 `git worktree add --track -b feature/video-enhanced ../AI-Marketing-Video-Enhanced origin/feature/video-enhanced`。仅需恢复冻结代码作离线检查时，可另建一个分离 HEAD 的目录，运行 `git worktree add --detach ../AI-Marketing-Comment-Only-Restore comment-only-v1.0`。环境和私有配置须在重建目录中分别恢复。
