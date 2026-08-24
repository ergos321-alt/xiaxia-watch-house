# Xiaxia Watch House V1.1

私人双人 AI 共影 Web App。Watch House 保存影片时间轴、字幕证据、双方独立观看状态和观影痕迹；Custom GPT 中的林知夏通过 Action 按需读取有界上下文，并写回自己的 thought / reply / checkpoint。它不伪造后台持续自主观影，也不把 Render 当媒体仓库。

## 1. 已实现的稳定能力

- `/watch` 私人影片库：来源、字幕状态、用户进度、Xiaxia 进度、最后活动。
- `/watch/{film_id}` 共影页：本地视频浏览器播放、在线 iframe、不可嵌入时的外链 + 静音同步时间线。
- UTF-8 SRT / WebVTT 上传、解析、替换；每条 cue 有稳定 UUID、顺序号和 seconds 时间范围。
- 防剧透 current-context：默认证据终点不会越过用户已保存的观看位置。
- 有界 transcript：按 `start_seconds/end_seconds`、`chunk_index`、`from_checkpoint` 或 `continuation` 读取；单次最多 200 cues，时间范围模式最多 1800 秒。
- 用户 progress 与 Xiaxia viewing state 分表、分接口持久化。
- `user_annotation`、`xiaxia_thought`、`xiaxia_reply` 三种明确对象与稳定 ID。
- Web 创建内容时服务器固定 `actor=user`；Action 写入时服务器固定 `actor=xiaxia`。请求体出现 `actor/author/owner` 会被拒绝。
- Web 私人密码 Session + CSRF；Action 使用独立 Bearer Token。登录接口不在 Action Schema 中。
- 前端每 12 秒短轮询增量内容，按稳定 ID 去重；不刷新页面、不重载播放器、不清空正在输入的文字。
- 播放进度每 12 秒节流保存，并在 pause、seek、pagehide、beforeunload 时尽力写回。
- 多影片隔离；Web 删除影片需要输入完整标题二次确认，且不暴露给 Action。

### V1.1 增量升级

- 修复 Xiaxia Reply 因复用父 `annotation_id` 而被前端去重跳过的问题。前端现在分别使用 `annotation:{annotation_id}`、`thought:{thought_id}`、`reply:{reply_id}`。
- 时间线明确展示“👤 我的痕迹”“💭 Xiaxia Thought”“💬 Xiaxia 回复”，Reply 保留父 annotation 关联但不再显示生硬的数据库 ID。
- 影片详情增加来源、字幕语言、总时长、用户进度、Xiaxia 进度和“未开始/观看中/已完成”展示状态。
- 影片库调整为 Xiaxia Cinema，并按“正在观看 / 想看的影片 / 已经看完”分区。
- 本轮没有修改数据库表、持久化模型、Web API、Action API、OpenAPI 或字幕边界。

## 2. 项目目录

```text
xiaxia-watch-house/
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
│   │   └── watch.js
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── watch_detail.html
│       └── watch_library.html
├── tests/
│   ├── conftest.py
│   ├── test_auth_and_identity.py
│   ├── test_schema_openapi_frontend.py
│   ├── test_subtitles_and_context.py
│   └── test_timeline_crud_and_isolation.py
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

## 3. PostgreSQL、Storage 与媒体职责

| 内容 | 持久化位置 | 说明 |
| --- | --- | --- |
| 影片 metadata / 来源 URL / duration | PostgreSQL `films` | 不保存完整视频二进制 |
| SRT/VTT 解析结果 | PostgreSQL `subtitle_cues` | 小型文本证据，按 `film_id` 隔离 |
| 用户播放进度 | PostgreSQL `user_progress` | 一片一行，`actor=user` |
| Xiaxia checkpoint | PostgreSQL `xiaxia_viewing_state` | 与用户进度完全独立 |
| 用户批注 | PostgreSQL `user_annotations` | `annotation_id`、时间点/范围、可选 cue anchor |
| Xiaxia 想法 | PostgreSQL `xiaxia_thoughts` | 独立 thought，不依赖用户批注 |
| Xiaxia 回复 | PostgreSQL `xiaxia_replies` | FK 指向用户 annotation |
| 本地视频本体 | 用户浏览器临时 Object URL | 刷新后需要重新选择本地文件，视频从不上传服务器 |
| 在线视频 | 原平台 | Watch House 只保存 URL / ID / 时间线状态 |
| Supabase Storage | V1 不使用 | 因而没有 bucket、policy 或 object cleanup 的伪实现 |
| Render 磁盘 | 不持久化 | 仅运行应用，不作为媒体仓库 |

如果未来加入海报，可新增 private Storage bucket 和影片专属 object manifest；在那之前不应为“看似完整”创建没有真实用途的 Storage 架构。

## 4. 时间单位与稳定 anchor

整个项目只使用 `seconds`：SQL 列、Python 字段、JavaScript payload 和 OpenAPI 参数均为 seconds，最多保留三位小数。浏览器内部 `performance.now()` 的毫秒只用于计算本地时钟差，写入 API 前必定转换成 seconds。

字幕上传后按影片、语言、cue 顺序、`start_seconds`、`end_seconds` 生成 UUID v5：

```text
cue_id = UUIDv5(film_id, language:sequence:start_seconds:end_seconds)
```

因此同一影片重复上传内容与时间轴相同的字幕会得到相同 cue ID；字幕文本不参与定位，修改展示文本不会被当成唯一 anchor。所有观影痕迹至少保存 `film_id + start_seconds`，可选 `end_seconds + cue_id`。服务器会校验 cue 必须属于同一影片。

## 5. 双方独立 progress

用户播放器只写 `user_progress.current_seconds`；Action 只写 `xiaxia_viewing_state.last_timestamp_seconds`。影片详情和 Action 响应同时返回两套状态，但任何一套都不会推导或覆盖另一套。

Xiaxia 的 checkpoint 还可保存：

- `last_subtitle_cue_id`
- `chunk_checkpoint`
- `completed`

Custom GPT 连续读取字幕后，应显式调用 `POST /api/watch/xiaxia/progress`；服务器不会根据用户播放位置假装 Xiaxia 已经看过。

## 6. 长字幕与防剧透读取

### 当前场景

`GET /api/watch/videos/{film_id}/context` 返回：

- `evidence_start_seconds`
- `evidence_end_seconds`
- `spoiler_boundary_seconds`
- 该窗口内最多 200 条 subtitle cues
- 该窗口内三类观影痕迹
- 双方独立 progress

若指定的 `timestamp_seconds` 超过用户已保存进度，服务器会把边界收紧到用户进度。没有用户进度时，显式 timestamp 自身就是边界。

### 长距离读取

`GET /api/watch/videos/{film_id}/transcript` 支持：

- `start_seconds` + `end_seconds`：时间范围最长 1800 秒。
- `chunk_index` + `chunk_size_cues`：默认 80 cues，最多 200 cues。
- `continuation`：把上一响应的 opaque token 原样传入。
- `from_checkpoint=true`：未给显式范围时，直接从 Xiaxia 保存的 timestamp 开始。

响应提供 `has_previous`、`has_next`、`previous_chunk_index`、`next_chunk_index` 和 `continuation`。长影片应使用 `chunk 0 → 1 → 2` 或 continuation 连续读取；没有单次返回完整长 transcript 的接口。

`transcript` 是明确的导航/分段阅读能力；“宝宝看看刚才这里”应使用独立的防剧透 `context`，不要混用。

## 7. 三类观影痕迹与 CRUD

| 对象 | 稳定 ID | 创建身份 | 关系与删除 |
| --- | --- | --- | --- |
| `user_annotation` | `annotation_id` | Web 服务端固定 user | Web list/create/update/delete；删除时级联其 replies |
| `xiaxia_thought` | `thought_id` | Action 服务端固定 xiaxia | Action list/create；Web 私人管理 update/delete |
| `xiaxia_reply` | `reply_id` | Action 服务端固定 xiaxia | 绑定 `annotation_id`；Web 私人管理 update/delete；删 reply 不删 annotation |

三种记录均有 `film_id`、`actor`、`content_type`、`start_seconds`、可选 `end_seconds/cue_id`、正文和时间戳。它们没有被压成一个模糊的 `comment` 表。

## 8. 删除影片的完整生命周期

Web 删除请求必须携带与影片标题完全一致的 `confirm_title`。数据库 FK 执行：

1. 删除 `films` 主记录。
2. `ON DELETE CASCADE` 清理 subtitle cues、用户 progress、Xiaxia viewing state、annotations、thoughts、replies。
3. `watch_state.current_film_id` 使用 `ON DELETE SET NULL`。
4. V1 没有 Storage object，因此响应明确为 `storage_objects_deleted: 0`，不存在 orphan object。

高破坏性删除路由 `/api/web/films/{film_id}` 不包含在 `openapi.yaml`，Custom GPT 无法通过默认 Action 调用。

## 9. 本地与在线播放的诚实降级

- 本地视频：使用 `<input type=file>` + 浏览器 Object URL + 原生 `<video controls playsinline>`。服务器只保存进度；页面刷新后用户需重新选择文件。
- YouTube：能解析标准视频 ID 时使用 `youtube-nocookie.com` iframe；平台策略、地区、年龄或版权限制仍可能阻止播放。
- Bilibili：能解析 BV/av ID 时 best-effort 嵌入；平台可能拒绝跨站播放。
- 其他 iframe：按用户提供 URL 尝试嵌入，站点可通过 CSP/X-Frame-Options 阻止。
- 所有在线来源：始终显示“在原平台打开”，并提供独立的开始/暂停、±10 秒和手动校准静音同步时间线。

V1 不自动抓取平台字幕，也不声称能稳定读取 iframe 内的真实 `currentTime`。当平台字幕不可用时，上传外挂 SRT/VTT 即可继续共影。

## 10. Supabase fresh install

1. 创建一个新的 Supabase project。
2. 打开 SQL Editor，把本项目根目录的 `schema.sql` 完整运行一次。
3. 确认八张表存在：`films`、`subtitle_cues`、`user_progress`、`xiaxia_viewing_state`、`user_annotations`、`xiaxia_thoughts`、`xiaxia_replies`、`watch_state`。
4. 在 Supabase 的 Database connection settings 获取 PostgreSQL 连接串。Render 通常优先使用 pooler URL，并保留 `sslmode=require`。
5. 如果密码含 `@`、`:`、`/` 等字符，必须在连接 URL 中进行 percent-encoding。

项目继续使用 fresh-install `schema.sql`，没有制造不必要的 migration。V1.1 没有数据库变化，已部署的 V1 Supabase 无需再次执行 SQL。应用默认 `AUTO_CREATE_SCHEMA=false`，不会在生产环境偷偷改表。

## 11. GitHub 与 Render 部署

1. 把整个项目提交到一个私人 GitHub repository。
2. 在 Render 创建 Blueprint，选择仓库中的 `render.yaml`。
3. 配置：
   - `DATABASE_URL`：真实 Supabase PostgreSQL URL。
   - `WEB_PASSWORD_HASH`：Werkzeug 密码哈希，不能填明文密码。
   - `SESSION_SECRET`：Render Blueprint 可自动生成。
   - `ACTION_BEARER_TOKEN`：Render Blueprint 可自动生成；部署后复制到 Custom GPT Action Authentication。
4. 等待部署完成，访问 `https://你的域名/health`，应返回 `{"service":"xiaxia-watch-house","status":"ok"}`。
5. 打开 `/login`，用哈希对应的原始密码登录，再添加影片和字幕。

生成 Web 密码哈希：

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('你的私人密码'))"
```

依赖已固定在 `requirements.txt`，其中 Render 已知问题版本没有被使用：

```text
psycopg[binary,pool]==3.2.10
```

Gunicorn 启动命令已同时写入 `Procfile` 与 `render.yaml`。

## 12. Custom GPT Action 配置

1. 部署成功后，只修改 `openapi.yaml` 的这一处：

```yaml
servers:
  - url: https://你的真实-render-域名.onrender.com
```

2. 把修改后的 OpenAPI 3.1 Schema 导入 Custom GPT Action。
3. Authentication 选择 API Key / Bearer，并填写与 Render `ACTION_BEARER_TOKEN` 完全相同的真实 token。
4. 不要把 token 写进 `openapi.yaml`、Custom GPT Instructions、HTML 或 JavaScript。
5. 每套独立 Xiaxia 服务使用不同的高熵 Action token。

Action 可导航：列影片、读 metadata/duration/字幕范围、读用户位置、读 Xiaxia checkpoint、从开头/任意 timestamp/checkpoint 开始分段读取。所有 `operationId` 唯一；path parameters 直接定义在 operation 下；object schema 均声明 properties；description 均短于 300 字符；没有 server variables、Web 登录或影片删除 Action。

建议在 Custom GPT Instructions 中说明：

- “问这一幕”先调用 `getCurrentWatchHouseState`，再用 `getSpoilerSafeFilmContext`。
- 长距离阅读调用 `readFilmTranscriptChunk`，按 `has_next/continuation` 继续，不要求单次整片字幕。
- 读到可靠位置后调用 `updateXiaxiaViewingCheckpoint`。
- 只有林知夏本人决定想留下内容时，才调用 thought/reply 写入；不要把服务器当自动评论生成器。

## 13. 本地运行与自动化测试

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# 把 .env 中的占位值替换为真实本地配置
.venv/bin/python run.py
```

本次交付实际运行：

```bash
.venv/bin/python -m pytest -q
```

结果：`30 passed, 0 failed`。

测试覆盖：认证与 CSRF、Web/Action 身份边界、fresh schema 结构、multi-film isolation、annotation CRUD、Xiaxia thought/reply、annotation + reply 同时出现在 timeline、三类前端去重 key 独立、双方独立 progress、SRT/VTT、seconds 与稳定 cue anchor、防剧透边界、时间窗口/chunk/continuation、长字幕不会单次返回完整内容、前端 polling 契约、进度节流、V1.1 影院分区与影片信息展示、影片删除 cascade、OpenAPI/Flask 路由一致性、operationId 唯一、object properties、description 长度、Action request body 身份字段、前端秘密泄漏、Render 依赖版本。

Storage 测试不适用：本 V1 明确没有创建或使用 Storage bucket。

## 14. V1.1 升级部署

对于已经通过验收的 V1：

1. 用本包覆盖仓库中的同名文件并提交。
2. 推送 GitHub；已连接仓库的 Render 会按原配置自动重新部署。
3. 部署完成后检查 `/health`、影片库、影片详情页和一条真实 Xiaxia Reply。

无需重新执行 `schema.sql`，无需新增或修改环境变量，无需替换 `openapi.yaml` URL，也无需重新导入 Custom GPT Action。若是全新环境，才按第 10–12 节完成 Supabase、Render 和 Action 首次配置。

## 15. 必须进行的实机验收

自动化测试不能冒充以下真实设备结果：

- Android Chrome：登录 Session、横竖屏、原生 controls、本地文件选择、长片 seek、软键盘不遮挡评论输入。
- iOS Safari：`playsinline`、本地文件权限、pagehide 尽力保存、后台/前台切换后的进度。
- 点击 annotation 后跳转到正确秒数，播放器/静音同步时间线状态正确。
- 播放中 12 秒 polling 不改变 `currentTime`、不暂停/重载视频、不清空输入框、不重复渲染。
- YouTube/Bilibili/目标平台在你的网络、账号、地区和具体视频上的 iframe 行为。
- Render 免费实例冷启动后的登录、Action 超时与恢复体验。
- 真实 Custom GPT Action 连续执行 `list → detail/state → context/transcript chunks → thought/reply/progress`。

## 16. V1.1 边界

本项目未加入视觉截帧识别、短视频感官分析、直播陪看、Android 屏幕/系统音频捕获、常驻 Whisper/ASR、自动整片摘要、陪看停顿点、后台主动弹幕、万能平台下载器、Obsidian 沉淀或完整影片长期存储。这些都不属于 V1.1。
