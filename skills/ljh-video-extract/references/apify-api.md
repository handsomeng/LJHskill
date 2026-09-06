# Apify API 参考（抖音）

仅在排错、维护 Apify 客户端或确认 Actor 行为时读取。

## 账号与凭证

- API 域名：`https://api.apify.com/v2`
- 鉴权：URL 查询参数 `token=apify_api_xxx`（只读 API，不在 Header 中）
- 月度硬额度：超了报 `403 platform-feature-disabled`，去 https://console.apify.com/billing 充值或调高上限
- 内存上限：账号默认 8GB，并发 5-8 个 run 比较稳，超出报 `402 actor-memory-limit-exceeded`

## Actor 1：easyapi~douyin-video-downloader

下载服务器：`https://api.apify.com/v2/acts/easyapi~douyin-video-downloader/runs?token={TOKEN}`

输入（**字段名必须是 `links`**，数组，不是 `videoUrls` / `startUrls` / `videoUrl`）：

```json
{"links": ["https://www.douyin.com/video/XXXXXXXXXXXXXXX"]}
```

轮询：

```text
GET /v2/actor-runs/{runId}?token={TOKEN}
```

- `data.status`：`SUCCEEDED` / `FAILED` / `TIMED-OUT` / `ABORTED`
- 成功后取 `data.defaultDatasetId`

取结果：

```text
GET /v2/datasets/{datasetId}/items?clean=true&token={TOKEN}
```

条目结构（`items[0].result`）：

```json
{
  "duration": 12345,
  "desc": "作品标题",
  "medias": [
    {"type": "video", "quality": "no_watermark", "url": "https://..."},
    {"type": "audio", "url": "https://..."}
  ]
}
```

- 无水印视频质量名：`no_watermark`（首选） / `hd_no_watermark`
- 音频 `type` 为 `audio`
- 视频被下架：返回 `{"error": true, "message": "No medias found"}`，脚本按失败处理，记录 `NO_MEDIAS`
- 计费：每条约 ¥0.1-0.3

## Actor 2：apple_yang~douyin-transcripts-scraper（云端口播，备选）

输入：

```json
{"videoUrl": "https://www.douyin.com/video/XXXXXXXXXXXXXXX"}
```

- 单次只支持 1 个 URL，多 URL 要并发多个 run
- 计费：$0.005 / 条
- 返回条目：`transcript` / `videoTitle` / `videoUrl` 等
- 注意：该系列 transcript actor 曾有「no audio url found」失效记录，若调用失败请改用
  easyapi 下载 mp3 + 本地 whisper（脚本默认路径），此 actor 仅作兜底

## 脚本的 token 发现顺序

1. 环境变量 `APIFY_TOKEN`
2. 环境变量 `APIFY_KEYS_FILE` 指定的文件（正则 `apify_api_\w+`）
3. `~/.config/ljhskill/API_Keys.md` 的 `## Apify API` 段落（`- **Token**: apify_api_xxx`）
4. macOS 钥匙串服务 `ljh-apify-token`
5. `~/vibecoding/.credentials.md`（本机个人凭证文件，正则 `apify_api_\w+`）

## 转写通道

默认 `--transcriptor auto`：

1. easyapi 下载 mp3（已付费的媒体下载）后，本地 faster-whisper 转写（免费）
2. 本地失败的兜底：apple_yang 云端口播 actor

本地 whisper 的 venv python 发现顺序：

1. 环境变量 `LJH_WHISPER_PYTHON`
2. `~/.workbuddy/skills/douyin-video-teardown/.venv/bin/python`
3. `~/.claude/skills/douyin-video-teardown/.venv/bin/python`
4. `~/.codex/skills/douyin-video-teardown/.venv/bin/python`

模型缓存：`~/.cache/douyin-teardown/whisper`（small 已下载）；模型参数 `--whisper-model`，
默认 `small`，要更准用 `medium` / `large-v3`（慢 3-5 倍）。
