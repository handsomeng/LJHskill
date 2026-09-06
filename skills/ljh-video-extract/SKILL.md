---
name: ljh-video-extract
displayName: ljh-video-extract
slug: ljh-video-extract
version: 1.1.0
description: |
  短视频提取与分析工具。接收抖音、小红书、微信视频号等短视频链接或分享文案，提取口播文稿、作品数据和无水印媒体（mp4/mp3），按作者和标题归档 Markdown；批量输入并发后生成分析报告（词频、重复话术、开场钩子、促销词、时长/字数、样本概览）。抖音默认走 Apify（数据+口播+媒体），小红书与视频号走 TikHub 数据 + 轻抖文稿。
  触发方式：/ljh-video-extract、「帮我提取这条视频的脚本」「把这条抖音的视频和文案都导出来」「给我分析一下这几个视频」「帮我扒一下这些视频的文案」
  Douyin/Xiaohongshu/WeChat Channels video extractor: transcripts, stats, and watermark-free media from a link or share text; batch extraction plus a multi-dimension stats report.
  Trigger: /ljh-video-extract, "extract the script from this video", "download this douyin video and its transcript", "analyze these videos", "pull the copy from these videos"
  纯图片笔记、直播回放、只做文字稿审改或逐帧分镜拆解时不自动触发；开品、选品、价值、定位等商品判断类咨询不要触发本工具。
---

更新检查：业务交付完成后，环境允许执行时运行本 Skill 目录下的 `scripts/check_update.py`；脚本有输出时，把提醒原样放在本次业务交付末尾；无输出不提；不得自动更新。

# ljh-video-extract：短视频提取与分析

目标：一个入口处理同一条短视频分享文案。抖音用 Apify 拿到作品数据、无水印媒体和口播文稿；TikHub 提供小红书和微信视频号的结构化数据，轻抖提供语音文字稿。批量给链接时，提取完成后可生成分析报告。采集到的素材与文稿不进 `ljh-档案`（业务结论档案由主入口 `/ljh` 统一管理），本工具只产出素材、文稿和统计报告。

## 开场协议（每次触发必做，用户明确要继续上次任务除外）

用户触发本 skill 后，**第一步先运行**：

```bash
python3 scripts/extract_video.py --intro
```

然后按返回的 JSON 向用户做一次自然语言介绍（不贴 JSON，不念参数表），只说三件事：

1. **这个 skill 能干什么**：能力菜单四样，用户给一条链接或分享文案就能干前两样，给一批链接干后两样：
   - 单条导出视频：无水印 mp4 + 原声 mp3 + 作者/标题/时长
   - 单条导出脚本：同一链接出口播文稿（本地转写，免费），Markdown 按作者/标题归档
   - 批量提取：links.txt 每行一条，并发拿脚本 + 视频 + 数据
   - 分析报告：批量后出统计数据（词频、跨视频重复话术、开场钩子、促销信号词、时长/字数、样本概览）
2. **当前凭证状态**：`credential_state` 是哪种（抖音能不能完整用），缺什么怎么接。缺 TikHub / 轻抖
   时引用 [references/api-setup.md](references/api-setup.md) 的购买配置教程；缺 Apify 时引用
   [references/apify-api.md](references/apify-api.md) 的 token 配置段。
3. **给下一步**：请用户提供一条链接 / 一段完整分享文案 / 一个链接清单文件路径，或选择只要
   脚本、只要视频、还是批量加报告。

介绍完等用户输入，不切换其他任务。用户只发了链接或分享文案时，默认按「单条导出视频 +
脚本」执行，不要反问你想要什么。用户发了多个链接或链接清单文件时，默认按「批量提取 +
生成分析报告」执行。

## 平台与通道

| 平台 | 数据 | 口播文稿 | 媒体下载 | 需要凭证 |
| --- | --- | --- | --- | --- |
| 抖音 | Apify（easyapi） | 本地 whisper（免费）＞Apify 云端兜底 | Apify 无水印 mp4/mp3 | 仅 Apify token |
| 小红书 | TikHub MCP | 轻抖 API | 无 | TikHub + 轻抖 |
| 微信视频号 | TikHub MCP | 轻抖 API（视平台支持） | 无 | TikHub + 轻抖 |

抖音在 Apify 可用时优先走 Apify；没有 Apify token 时回落 TikHub 数据 + 轻抖文稿。
没有 TikHub / 轻抖时，小红书与视频号会提示缺少凭证，不影响抖音提取。

## 先检查使用凭证

任何提取任务开始前，先运行只读预检：

```bash
python3 scripts/extract_video.py --check-keys
```

根据 `credential_state` 处理：

| 状态 | 能力 | 必须告知用户 |
| --- | --- | --- |
| `complete` | 全平台数据与文稿可用 | 可以直接执行 |
| `apify_ready` / `apify_only` | 只有 Apify：抖音完整提取可用 | 抖音可执行；小红书与视频号需 TikHub / 轻抖 |
| `data_only` | 只有 TikHub 数据 | 只能查数据，无法生成文字稿 |
| `transcript_only` | 只有轻抖文稿 | 只能提取文稿，无法查数据 |
| `unavailable` | 无可用凭证 | 解释使用凭证，再引导购买和配置 |

Apify token 的存放与发现顺序见 [references/apify-api.md](references/apify-api.md)；配置命令：

```bash
python3 scripts/configure_api_key.py apify
```

已有 Apify token 的用户跳过凭证引导，直接执行提取。TikHub / 轻抖的缺失引导、法律
提示、购买步骤仍按 [references/api-setup.md](references/api-setup.md) 处理，仅面向
小红书与视频号场景或用户明确要求。

## 默认执行

优先使用标准输入，避免分享文案中的特殊字符被 Shell 解释：

```bash
python3 scripts/extract_video.py \
  --output-dir "/绝对路径/短视频文字稿" \
  --stdin
```

默认流程（抖音）：

1. 从完整分享文案中提取链接；
2. Apify `easyapi~douyin-video-downloader` 一次 run 取作品数据与无水印 mp4 直链；
3. mp4 保存到 `{输出目录}/media/`，用 imageio-ffmpeg 从 mp4 抽取原声音轨
   （easyapi 的 audio 直链实测不可靠，可能返回错误内容，不采用）；
4. 口播转写：本地 faster-whisper（复用 douyin-video-teardown 的 .venv）；失败时回落
   Apify 云端 `apple_yang~douyin-transcripts-scraper`；
5. 按 `{输出目录}/{作者}/{标题}.md` 保存文稿（作者缺失时归入 `_未识别作者`）；
6. 结果合并进 `{输出目录}/_index.json`（按链接去重），供报告脚本使用。

小红书 / 视频号：TikHub 查数据（MCP），轻抖提取文稿，其余不变。

TikHub 或轻抖任一侧失败时继续完成另一侧，并在汇总中标记 `partial_success`。已经取得
的结果不能因单侧失败而丢弃。Apify 单侧失败时如实标记，不谎报成功。

## 可选模式

只有用户明确只需要一侧结果时才切换：

```bash
python3 scripts/extract_video.py --mode data --stdin
python3 scripts/extract_video.py --mode transcript --stdin
```

- `data`：只查询作品数据（抖音走 Apify，其他平台走 TikHub）；
- `transcript`：只提取口播文稿（抖音走 whisper / Apify 云端，其他平台走轻抖）；
- `both`：默认，同时两侧。

其他常用参数：

- `--transcriptor auto|whisper|apify`：转写通道选择，默认 auto；
- `--whisper-model small`：本地 whisper 模型，要更准用 `medium` / `large-v3`；
- `--input-file list.txt`：批量提取，每个非空行一条链接或分享文案；
- `--concurrency 2`：批量并发数（1-6），默认 2；
- `--overwrite`：覆盖同一来源的已有文稿（默认跳过，保护用户编辑）；
- `--raw-data`：需要 TikHub 完整响应时使用。

媒体（mp4/mp3）默认下载保存到 `{输出目录}/media/`（转写需要音轨，下载不计额外
Apify 费用）；不需要媒体文件时删除该目录即可。

批量使用示例：

```bash
python3 scripts/extract_video.py \
  --input-file links.txt \
  --output-dir "/绝对路径/短视频文字稿"
```

## 批量分析报告

提取完成后生成统计报告（不重新联网，数据来自 `_index.json`）：

```bash
python3 scripts/build_report.py "/绝对路径/短视频文字稿"
```

输出 `{输出目录}/分析报告.md`，包含：样本概览、时长与文稿长度分布、口播词频、
跨视频重复话术、每条开场前 40 字钩子、促销信号词统计。词频与重复话术是简单统计，
不作为结论；需要逐帧 / 逐句深度拆解或说服链诊断时改用脚本评审工具（`/ljh-jiaoben`）。

## 密钥与费用

脚本按以下顺序读取 Key：

1. 环境变量：`APIFY_TOKEN`、`TIKHUB_API_KEY`、`QINGDOU_API_KEY`；
2. 用户指定的本地文件：`APIFY_KEYS_FILE`、`TIKHUB_API_KEYS_FILE`、`QINGDOU_API_KEYS_FILE`；
3. `~/.config/ljhskill/API_Keys.md`；
4. macOS 钥匙串：`ljh-apify-token`、`ljh-tikhub-api-key`、`ljh-qingdou-api-key`；
5. Apify token 还会读取 `~/vibecoding/.credentials.md`（本机个人凭证文件）。

禁止把 Key 写入 Skill、命令参数、Markdown、Git 或日志。Apify 下载、TikHub 查询和轻抖
转写都可能计费；执行前告知用户，用户已经明确要求提取时无需重复确认。

## 数据边界

- Apify 负责抖音的作品数据、媒体直链与（云端口播转写备选）；本地 whisper 负责转写。
- TikHub 负责小红书 / 视频号的作品、账号资料、统计；抖音作品优先 App V3，无有效数据
  时只回退 1 次 Web。
- 轻抖负责文字稿（兼容平台）。正文忠实保存 API 返回内容，不补写、润色或修订口误。
- 当前 Apify 通道只支持抖音；TikHub 数据解析支持抖音、小红书和微信视频号；轻抖可识别
  的其他平台仍可只执行文字稿提取。
- 公开、删除、私密、版权和可见范围限制以接口返回为准，不尝试绕过。
- `NO_MEDIAS`（视频已下架）如实标记，不补位。
- 不自动发布内容、提交 Git 或推送。

Apify 调用细节见 [references/apify-api.md](references/apify-api.md)；TikHub 调用细节见
[references/tikhub-api.md](references/tikhub-api.md)；轻抖状态码和兼容逻辑见
[references/qingdou-api.md](references/qingdou-api.md)。只在排错或维护对应部分时读取。

## 交付

完成后简洁报告：

- 当前配置了哪些凭证，以及可用能力范围（抖音是否可完整提取）；
- 数据查询是否成功、使用的通道（Apify / TikHub MCP）、是否发生回退；
- 关键作品数据；
- 文稿是否成功、转写通道（本地 whisper / 云端）、生成或跳过的 Markdown 绝对路径；
- 媒体是否下载（mp4/mp3 路径）；
- 批量时给成功 / 失败统计与 `_index.json` 路径；
- 单侧缺少凭证或执行失败的具体原因；
- 接口是否明确返回已计费。

不要在回复中展示 API Key、`batchId` 或无必要的内部请求标识。

完成当前任务后直接结束。只有用户明确询问下一步，且当前环境已经安装 `/ljh` 时，
简短提示：「下一步不确定时，可以输入 `/ljh`。」
