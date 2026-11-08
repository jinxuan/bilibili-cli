---
name: bilibili-creator-overview
description: Give a quick overview of a Bilibili (B站) creator / UP主 from a space link (space.bilibili.com/<uid>), UID, or name — who they are, what they make, how often they post, their top and recommended videos — using only 2 bili-cli calls and never downloading their whole catalog, while avoiding 412/429/-352 risk control. Use when the user shares a space.bilibili.com link or asks about an UP主 / 博主 / 空间 / 频道 (这个博主做什么的, 值不值得关注, 有哪些代表作).
author: jackwener
version: "0.1.0"
tags:
  - bilibili
  - b站
  - creator
  - up主
  - overview
---

# bilibili-creator-overview

Overview one creator from metadata only: profile + latest videos list. Never fetch every video,
subtitle, or comment — that is slow and the fastest way to get the account/IP risk-controlled.
Requires `bilibili-cli` (`uv tool install bilibili-cli`); the command is `bili`.

## Workflow

### 1. Get the UID

- `https://space.bilibili.com/13030183?spm_id_from=...` → UID is the number after the domain: `13030183`.
  Drop query strings.
- Plain number → use as-is.
- Only a name → `bili user "<name>"` resolves via search (one extra request; matches the first
  result, so confirm the name in the output is the one the user meant).

### 2. Check login (once per session)

```bash
bili status --yaml
```

The space video list is heavily risk-controlled: anonymous requests often fail with 412 on the
very first call. If `data.authenticated` is false, suggest `bili login` before continuing.

### 3. Fetch — exactly 2 calls, serial, with a gap

```bash
bili user <uid> --yaml
sleep 3
bili user-videos <uid> --max 20 --yaml
```

- `bili user` → `data.user.name`, `data.user.sign` (bio), `data.user.level`,
  `data.relation.follower` (fans). Ignore the `vip` block.
- `bili user-videos` → list of videos, each with `title`, `bvid`, `url`, `duration`,
  `published_date`, `stats.view`.
- `--max 20` is the default depth. Go up to `--max 50` only if the user wants a longer history.

### 4. Write the overview

Answer in the user's language. Base everything on the data above; don't guess beyond it.

```
**<name>**（UID <uid>）· 粉丝 <follower> · Lv<level>
<space url>
简介：<sign, one line>

定位：<one sentence: what they make and for whom>

内容方向：
- <topic A>（n 条）：<example title>
- <topic B>（n 条）：...
（group the titles into 2–4 topics）

更新节奏：最近 <N> 条覆盖 <first date> ~ <last date>，约 <x> 天一更

播放最高：
1. <title> — <view> 播放 · <date> · <url>
2. ...（top 3）

推荐先看：<2–3 videos and why — representative of their main topic, or unusually popular>
```

Then offer, don't do: "要看哪条的速览？" — and use the `bilibili-video-brief` skill for the
one(s) the user picks, one at a time.

## Avoiding rate limits (412 / 429 / -352)

1. **Metadata only.** 2 calls per creator. No per-video subtitle/AI/comment calls unless the user
   picks specific videos.
2. **Serial, never parallel**, with `sleep 3` (3–5 s) between calls. Comparing several creators:
   finish one creator, then wait ~10 s before the next.
3. **Recognize throttling**: `error.code: rate_limited` (covers HTTP 412/429 and API -412/-352).
4. **Back off, then stop.** The space endpoints need a longer cool-down: wait 30 s → 60 s → 120 s.
   After 3 failures stop and tell the user to try later. Don't hammer.
5. **Stay logged in.** `bili user` / `bili user-videos` send your login cookies, which makes 412
   much less likely.
6. **Never** loop over `--max 50` pages or download every video "to be thorough".

## Other errors

| `error.code` | Meaning | What to do |
|---|---|---|
| `not_found` | No such user, or name search found nothing | Ask for the space link |
| `not_authenticated` | Login expired | Suggest `bili login` |
| `network_error` | Connection issue | Retry once after a few seconds |
