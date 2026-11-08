---
name: bilibili-video-brief
description: Quickly brief a Bilibili (B站) video from its BV ID or URL — fetch the description and transcript (subtitles) with one bili-cli call, fall back to B站 AI summary when there are no subtitles, and write a short video intro without triggering rate limits (412/429/-352). Use when the user shares a bilibili.com / b23.tv link or BV号 and asks what the video is about, for a summary, 速览, 简介, 文字稿, or 讲了什么.
author: jackwener
version: "0.1.0"
tags:
  - bilibili
  - b站
  - video
  - summary
  - transcript
---

# bilibili-video-brief

Turn one Bilibili video into a quick, trustworthy intro: description + transcript → brief.
Requires `bilibili-cli` (`uv tool install bilibili-cli`); the command is `bili`.

## Workflow

### 1. Check login (once per session)

```bash
bili status --yaml
```

Subtitles need login. If `data.authenticated` is false, tell the user and suggest `bili login`
(QR code); you can still brief from the description and AI summary.

### 2. Fetch description + transcript in ONE call

```bash
bili video <BV_OR_URL> --subtitle --yaml
```

This single call returns everything needed. Do not fetch the same video twice.

- `data.video` — `title`, `description`, `duration`, `owner.name`, `stats.view/like/coin/favorite`, `url`
- `data.subtitle.available` — whether a transcript exists
- `data.subtitle.text` — the full transcript (primary source)
- `data.subtitle.items` — `from`/`to`/`content` lines, use them to timestamp key points
- `data.warnings` — `subtitle_unavailable` means no transcript (or not logged in)

### 3. Fallback when there is no transcript

Only if `data.subtitle.available` is false:

```bash
bili video <BV_OR_URL> --ai --yaml
```

Use `data.ai_summary`. If that is also empty, brief from title + description only and say so
clearly. Do not run audio extraction / ASR unless the user asks for it.

### 4. Write the brief

Answer in the user's language. Keep it short:

```
**<title>** — <owner> · <duration> · <view> 播放
<url>

一句话：<what the video is about and its main conclusion>

要点：
- [mm:ss] <key point>
- [mm:ss] <key point>
- ... (3–5 points; drop timestamps if they came from description/AI summary)

来源：字幕 | B站 AI 总结 | 仅简介
```

Rules:
- Base points on the transcript; use the description for context (links, chapters, credits).
- Always state the source line so the user knows how much to trust it.
- Don't paste the transcript unless asked; offer it ("需要完整文字稿吗？").

## Avoiding rate limits (412 / 429 / -352)

Bilibili throttles bursts and flags scraping. The CLI does not retry API calls by itself, so pace
calls yourself:

1. **One call per video.** `--subtitle` already includes the video info; add `--ai` only as a fallback.
2. **Serial, never parallel.** For multiple videos, run them one by one with `sleep 3` (3–5 s) between calls.
3. **Recognize throttling.** `error.code: rate_limited` covers HTTP 412/429 and API -412/-352.
   (On older bili-cli versions these may show up as `network_error` / `upstream_error` whose
   message contains `412`, `429`, or `-352` — treat those the same.)
4. **Back off, then stop.** Wait 10 s → 30 s → 60 s between retries; after 3 failures stop and
   tell the user to try later. Don't keep hammering.
5. **Stay logged in.** Requests with valid cookies (`bili status`) are throttled far less than
   anonymous ones.
6. **Batches.** For more than ~10 videos, confirm with the user first, and keep `--max` small when
   listing a creator's videos (`bili user-videos <uid> --max 5 --yaml`).

## Other errors

| `error.code` | Meaning | What to do |
|---|---|---|
| `invalid_input` | Not a valid BV ID / URL | Ask for the correct link (b23.tv short links: open to get the BV ID) |
| `not_found` | Video deleted or private | Tell the user |
| `not_authenticated` | Login expired | Suggest `bili login` |
