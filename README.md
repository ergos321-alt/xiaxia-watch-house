# Xiaxia Watch House V2

私人双人 AI 共影空间。Watch House 保存影片时间轴、字幕证据、双方独立观看状态，以及真正值得留下或只想轻轻说过的观影痕迹。它不寻找或下载电影，不生产字幕，不伪装 Xiaxia 在后台持续观看，也不把 Render 当媒体仓库。

V2 是从已验收 V1.1 进行的增量升级：没有重写 Flask 架构、字幕 cue anchor、双方 progress 基础模型或既有 Thought / Reply 表。

## 1. V1.1 稳定能力全部保留

- 私人 Session 登录、CSRF 与独立 Action Bearer Token。
- 多影片库与详情页；本地视频只用浏览器 Object URL 播放。
- YouTube / Bilibili best-effort iframe；无法嵌入时使用原平台 + 静音同步。
- UTF-8 SRT / WebVTT 上传、解析、替换和稳定 cue UUID。
- seconds 统一时间单位；annotation / thought / reply 的稳定 ID 和 cue anchor。
- 用户 progress 与 Xiaxia viewing checkpoint 分表、分接口持久化。
- 防剧透 context、有界时间窗口、字幕 chunk 和 continuation。
- Web 创建内容固定 `actor=user`；Action 创建内容固定 `actor=xiaxia`。
- 12 秒增量轮询、稳定 ID 去重和 12 秒 progress 节流。
- 影片删除确认与 PostgreSQL 级联清理；高破坏性删除不暴露给 Action。
- V1.1 Reply 去重修复继续有效：annotation、thought、reply 使用不同命名空间 key。

## 2. V2 新增能力

### 两个人坐在同一场

页面用一盏轻量“座位灯”展示：

- `🐶` 用户当前位置；
- `🐱` Xiaxia checkpoint；
- `together`：相差不超过 15 秒；
- `user_ahead` / `xiaxia_ahead`：相差 15–120 秒；
- `far_apart`：相差超过 120 秒；
- `not_started`：双方都未开始。

这些状态由现有两套 progress 动态计算，不持久化成监控日志，也不会自动推进 Xiaxia checkpoint。

### 时间线小脚印

时间线不再默认铺满长文字卡片。annotation、permanent Thought、Reply、fleeting trace 分别显示克制的 marker；点击 marker 会：

1. 跳转播放器或静音同步时间线到记录的 `start_seconds`；
2. 在局部详情区展开对应内容；
3. 不刷新页面、不重载播放器、不改动评论输入框。

前端稳定 key：

```text
annotation:{annotation_id}
thought:{thought_id}
reply:{reply_id}
fleeting:{trace_id}
```

同一秒附近的 marker 自动分成最多三条视觉轨道，避免 Reply 覆盖父 annotation。移动端 marker 点击面积不小于 32–38 px。

### Fleeting / Casual Trace

短句进入独立 `fleeting_traces` 表，不修改 `xiaxia_thoughts`：

- 正文最多 160 字；
- actor 仍由服务器依据 Web / Action 入口固定；
- 默认保存 30 天；
- 所有读取自动过滤已过期记录；
- 每次新建 fleeting trace 时机会性删除数据库中已过期记录；
- 页面浮现最多三条、约 8 秒淡出，但本次页面 session 仍可通过 marker 再次打开。

旧 V1.1 `xiaxia_thoughts` 无需迁移，全部按 `trace_type=permanent` 返回。永久 Thought 与短句不会混在同一数据表。

### Shared Stop

Shared Stop 不建表。服务器在同一影片内，将用户痕迹与 Xiaxia 痕迹在 ±15 秒窗口内按最近距离配对，并返回：

- 稳定 `shared_stop_id`（由 `film_id + 两个来源稳定 ID` 生成 UUID v5）；
- `start_seconds` / `end_seconds` / `anchor_seconds`；
- `user_trace_ref` / `xiaxia_trace_ref`；
- 轻文案“我们都在这里停过”。

它只是共同经过某个时间点的事实，不自动赋予深刻含义。删除或过期来源痕迹后，动态结果自然消失，不产生 orphan 表记录。

### 暂停氛围与观看状态

- 播放器或静音同步暂停超过 8 秒，银幕角落轻显示“我们停在这里。”；恢复后自然消失。
- 状态继续以 progress 派生“未开始 / 观看中 / 已完成”。
- 新增轻量 `user_progress.watch_intent='rewatch'`；用户主动点“想重看”时归零自己的位置，开始播放后自动清除该 intent。它不影响 Xiaxia checkpoint。

### 影片封底

V2 本轮未实现持久化 back-cover。任务书将其列为工作量允许时的后半阶段；本轮优先保证生产迁移、时间线层次和防剧透边界。当前模型不会阻断后续新增独立封底表或派生页面，且没有用 mock 文案伪装双方已留下总结或评分。

## 3. 项目目录

```text
Xiaxia_Watch_House_V2/
├── xiaxia_watch_house/
│   ├── __init__.py
│   ├── app.py
│   ├── auth.py
│   ├── models.py
│   ├── routes_action.py
│   ├── routes_web.py
│   ├── services.py
│   ├── static/
│   │   ├── library.js
│   │   ├── style.css
│   │   ├── timeline_key.js
│   │   ├── timeline_marker.js
│   │   └── watch.js
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── watch_detail.html
│       └── watch_library.html
├── migrations/
│   └── v1_1_to_v2.sql
├── tests/
│   ├── conftest.py
│   ├── test_auth_and_identity.py
│   ├── test_schema_openapi_frontend.py
│   ├── test_subtitles_and_context.py
│   ├── test_timeline_crud_and_isolation.py
│   └── test_v2_incremental.py
├── .env.example
├── .gitignore
├── openapi.yaml
├── Procfile
├── README.md
├── render.yaml
├── requirements.txt
├── run.py
└── schema.sql
```

## 4. PostgreSQL、Storage 与媒体职责

| 内容 | 持久化位置 | 生命周期 |
| --- | --- | --- |
| 影片 metadata / 来源 URL / duration | PostgreSQL `films` | 影片存在期间永久 |
| SRT/VTT cue 文本 | PostgreSQL `subtitle_cues` | 删除影片时级联 |
| 用户进度 / rewatch intent | PostgreSQL `user_progress` | 每片一行 |
| Xiaxia checkpoint | PostgreSQL `xiaxia_viewing_state` | 独立于用户进度 |
| 用户 annotation | PostgreSQL `user_annotations` | 永久 |
| Xiaxia permanent Thought | PostgreSQL `xiaxia_thoughts` | 永久；旧数据兼容 |
| Xiaxia Reply | PostgreSQL `xiaxia_replies` | 永久；绑定 annotation |
| Fleeting trace | PostgreSQL `fleeting_traces` | 默认 30 天 |
| Shared Stop / 同场状态 | 查询时派生 | 不持久化 |
| 本地视频 | 浏览器临时 Object URL | 不上传 |
| 在线视频 | 原平台 | Watch House 仅保存 URL |
| Supabase Storage | 不使用 | 无 bucket / policy / object cleanup |
| Render 文件系统 | 不持久化 | 不作为媒体仓库 |

## 5. seconds 与 cue anchor

数据库、Python、JSON、JavaScript 和 OpenAPI 的影片时间全部使用 seconds，最多三位小数。浏览器的 `performance.now()` 毫秒只用于本地时钟差，写 API 前转换为 seconds。

```text
cue_id = UUIDv5(film_id, language:sequence:start_seconds:end_seconds)
```

字幕正文只负责展示，不是唯一定位依据。所有痕迹保存 `film_id + start_seconds`，可选 `end_seconds + cue_id`；服务器验证 cue 必须属于同一影片。

## 6. 长字幕与不可回退的防剧透边界

`GET /api/watch/videos/{film_id}/context` 的证据终点始终为：

```text
min(requested timestamp, saved user progress)
```

没有用户 progress 时才使用显式 requested timestamp。V2 加入 context 的 active fleeting traces 也使用同一 `evidence_start_seconds <= start_seconds <= spoiler_boundary_seconds` 过滤，因此未来短句不会越过边界。Shared Stop 只由 Web timeline 计算，不被偷偷聚合进 Action context。

长字幕继续使用 `start_seconds/end_seconds`、`chunk_index/chunk_size_cues`、`continuation` 或 `from_checkpoint=true`。单次最多 200 cues，时间范围最多 1800 秒；不存在返回整部字幕的 Action。

## 7. V1.1 → V2 生产迁移

已有 Supabase 生产数据不得运行 fresh-install `schema.sql` 覆盖。升级顺序：

1. 在 Supabase SQL Editor 备份或确认可恢复点。
2. 运行 `migrations/v1_1_to_v2.sql` 一次。
3. 确认 `user_progress.watch_intent` 和 `fleeting_traces` 已出现。
4. 推送 V2 代码到 GitHub，让 Render redeploy。
5. 验证 `/health`、一条旧 Thought、一条旧 Reply、一个新 fleeting trace 与防剧透 context。

迁移是 additive：只为 `user_progress` 增加 nullable 字段、创建新表/索引/trigger；不 `DROP TABLE`、`TRUNCATE`、`DELETE`、重写旧 Thought，也不要求清空任何历史数据。

全新 Supabase 项目才直接运行最新 `schema.sql`。

## 8. Custom GPT Action 变化

原有 Action 全部保留：影片列表/详情/当前 state、防剧透 context、字幕 chunk、annotation 读取、Thought、Reply、Xiaxia checkpoint。

V2 仅新增必要 surface：

```text
GET  /api/watch/videos/{film_id}/fleeting-traces
POST /api/watch/videos/{film_id}/fleeting-traces
```

POST 请求不能提交 actor / author；服务器固定 `actor=xiaxia`。`openapi.yaml` 同步增加 fleeting schema、Thought 的 `trace_type=permanent`、progress 的 nullable `watch_intent` 和 film 的派生 `copresence`。

因此升级 V2 后需要重新导入 `openapi.yaml`。已部署域名不变时，`servers[0].url` 仍只替换原来那一处；Bearer Token 无需更换。登录与影片删除仍未暴露给 Action。

## 9. Render 与环境变量

Render 仍使用现有 `render.yaml` / `Procfile`，迁移完成后只需 GitHub redeploy。没有新增环境变量，也不需要重新配置现有：

- `DATABASE_URL`
- `SESSION_SECRET`
- `WEB_PASSWORD_HASH`
- `ACTION_BEARER_TOKEN`
- `COOKIE_SECURE`
- `AUTO_CREATE_SCHEMA`

依赖继续固定：

```text
psycopg[binary,pool]==3.2.10
```

不要在生产启用 `AUTO_CREATE_SCHEMA` 代替迁移。

## 10. 影片删除生命周期

删除影片仍需 Web 输入完整标题确认。PostgreSQL 级联清理 subtitle cues、双方 progress、annotations、thoughts、replies 和 fleeting traces；`watch_state.current_film_id` 设为 null。Shared Stop 与同场状态没有实体，无需额外清理。Storage 未使用，响应继续诚实返回 `storage_objects_deleted: 0`。

## 11. 实际自动化测试

安装与运行：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

本交付实际结果：

```text
40 passed, 0 failed
```

覆盖 V1.1 全部回归，以及：旧 Thought permanent 兼容、fleeting/permanent 分离、Web/Action actor 边界、30 天 retention 过滤、多影片隔离、Shared Stop 稳定 ID/来源引用、双方 progress 同场状态、rewatch intent、footprint key/marker timestamp、marker 点击 seek 契约、未来 fleeting 防剧透、Reply 继续显示、migration additive 保留代表性旧行、polling 不写播放器 currentTime、删除影片级联 fleeting、OpenAPI/Flask route 一致性与 Action Schema 规则。

## 12. 需用户本人完成

### 已有 V1.1 部署升级

1. 先在真实 Supabase 运行 `migrations/v1_1_to_v2.sql`。
2. 把完整 V2 包提交到现有私人 GitHub 仓库。
3. 触发 Render redeploy。
4. 把最终 `openapi.yaml` 重新导入 Custom GPT Action；保持同一真实 server URL 和 Bearer Token。

不新增 key，不修改环境变量。项目没有假 key、假部署 URL 或 mock 平台成功状态。

## 13. 必须实机验收

自动化测试不能冒充以下真实环境结果：

- Android Chrome：播放器区域、脚印点击、展开卡片、输入框与软键盘、长片 seek。
- iOS Safari：`playsinline`、本地文件权限、pagehide 尽力保存、前后台切换。
- 真实播放中 12 秒 polling 不改变 `currentTime`、不暂停/重载、不清空输入。
- 同一秒多 marker 是否易点；Shared Stop 不造成横向滚动。
- 短时间写入多条 fleeting trace 时最多三条浮现、不形成弹幕墙。
- 暂停 8 秒氛围文案不遮挡原生 controls。
- YouTube / Bilibili / 目标平台在实际网络、账号、地区与具体视频上的 iframe 行为。
- 真实 Custom GPT Action 执行旧能力与新 fleeting GET/POST。
- 真实 Supabase migration 的权限、锁等待与数据行数核对。

## 14. 明确边界

V2 不包含视频上传仓库、自动下载、Whisper、自动字幕、平台字幕抓取、Screen Sense、截图、视觉 AI、Reality Server 耦合、实时 AI 陪看、WebSocket、直播弹幕、社交分享、推荐算法或第三方电影数据库。

电影在前面。我们俩在旁边。
