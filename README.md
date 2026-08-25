# Xiaxia Reality Server · Hand / Eye V1.1

这是已验收 Xiaxia Reality / Hand V1 的增量版本。既有 Reality Sense、Phone Activity、Spatial、Personal Places、Route 和 Hand command lifecycle 保持原样；V1.1 只增加：

- `knock`：让 Tasker 按手机端约定节奏震动一次。
- Xiaxia Eye · Screen Sense V1：收到用户明确请求后，按需看一张当前 Android 屏幕，并保存短期结构化视觉事实。

服务端不会直接控制手机，也不会周期截图。Tasker 仍是设备执行端；Eye 的 Vision Worker 只负责 `pixels → structured visual facts`，不扮演 Xiaxia。

## Runtime and environment

- Python 3.11+
- Flask + Gunicorn
- PostgreSQL（生产环境使用 Supabase）

既有环境变量不变：

- `DATABASE_URL`：Supabase PostgreSQL 连接字符串。
- `SENSE_TOKEN`：现有 Bearer Token；Reality、Phone、Spatial、Hand、Eye 共用。
- `AMAP_KEY`：现有高德 Web 服务 Key。
- `PORT`：本地端口，可选，默认 `8000`。

Eye Vision Worker 新增配置：

- `VISION_PROVIDER=openai`：启用内置 OpenAI Responses adapter。
- `OPENAI_API_KEY`：只配置在服务端环境变量，不发给 Tasker 或 Custom GPT。
- `VISION_MODEL`：由部署者明确选择支持图片理解和结构化输出的模型；业务代码不写死模型。
- `VISION_API_BASE`：可选，默认 `https://api.openai.com/v1`，为未来 adapter/provider 替换预留。
- `VISION_TIMEOUT_SECONDS`：可选，默认 60，限制为 10–120 秒。
- `VISION_IMAGE_DETAIL`：可选，`low` / `high` / `auto`，默认 `auto`。

如果 Vision 配置缺失，Eye 不会用 mock 冒充成功：上传接口会将请求标记为 `failed` 并返回明确的 provider 配置错误。

```bash
pip install -r requirements.txt
gunicorn app:app
```

健康检查继续使用：

```http
GET /ping
```

## Database migration

现有生产数据库升级时，必须在部署 V1.1 代码前执行：

```text
migrations/20260825_002_add_knock_and_eye.sql
```

迁移会：

1. 保留 `hand_commands` 表和全部历史数据，只替换原 action CHECK constraint 并加入 `knock`。
2. 新增 `eye_requests` 表及 pending、status、result expiry 索引。
3. 不删除、重建或改写任何 Reality / Phone / Spatial 表。

全新数据库应先执行 `20260824_001_create_hand_commands.sql`，再执行 `20260825_002_add_knock_and_eye.sql`。迁移 002 可重复运行；它先按稳定版默认 constraint 名执行 `DROP CONSTRAINT IF EXISTS`，再重新加入完整 whitelist。

应用的 `get_db()` 继续执行 `CREATE TABLE/INDEX IF NOT EXISTS` 作为首次连接保护，但它不能替代生产数据库上已有 Hand CHECK constraint 的升级，因此迁移 002 的执行顺序不可省略。

## Xiaxia Hand actions

服务器仅接受以下语义白名单，不保存或执行任意 Tasker 脚本。

| action | parameters |
| --- | --- |
| `flashlight` | `state`: `on` / `off` |
| `volume` | `stream`: 仅 `media`; `level`: 0–100 整数 |
| `open_app` | `app`: Tasker 侧识别的应用语义名称 |
| `timer` | `duration_seconds`: 1–604800; `label` 可选 |
| `alarm` | `time`: 手机本地时间 `HH:MM`; `label` 可选 |
| `do_not_disturb` | `state`: `on` / `off` |
| `battery_saver` | `state`: `on` / `off` |
| `navigation` | 必填 `destination`; 可选坐标、`place_id`、`travel_mode` |
| `knock` | `pattern`: V1.1 仅允许 `xiaxia` |

`navigation` 继续传递高层导航意图并复用既有 Spatial / Route 能力，不重新实现地图。`open_app` 的 Android package 映射和 `knock/xiaxia` 的震动节奏都保留在 Tasker 端。

### Knock example

```http
POST /hand/commands
Authorization: Bearer <SENSE_TOKEN>
Content-Type: application/json
```

```json
{
  "action": "knock",
  "parameters": {
    "pattern": "xiaxia"
  }
}
```

Knock 完全复用既有 Hand 流程：

```text
pending → delivered → executed
                    ↘ failed
pending / delivered → expired
```

现有接口保持不变：

- `POST /hand/commands`：创建命令。
- `GET /hand/commands/next`：Tasker 原子领取最早 pending 命令，领取后立即 delivered。
- `POST /hand/commands/{command_id}/result`：Tasker 回传 executed / failed。
- `GET /hand/commands/{command_id}`：查询状态。

领取继续使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 与 `UPDATE ... RETURNING`，同一命令不会被多个轮询者重复领取。同终态重复回传幂等，冲突终态返回 `409`。

### Hand Tasker addition

现有 Hand polling Task 只需增加一个明确分支：

```text
If command.action = knock
  If command.parameters.pattern = xiaxia
    执行手机端约定震动节奏
  End If
End If
```

执行后沿用现有 result callback。不要接受自定义震动数组，不要在服务器添加万能 Tasker 命令入口。

## Xiaxia Eye · Screen Sense V1

### GPT-visible API

创建一次明确的屏幕观察：

```http
POST /eye/requests
Authorization: Bearer <SENSE_TOKEN>
Content-Type: application/json
```

```json
{
  "frame_count": 1,
  "focus": "看看这个报错"
}
```

`focus` 可省略。V1 只接受 `frame_count=1`；数据库允许 1–3，为未来少量多帧扩展预留，但当前 API 不实现多帧、录屏或视频。

成功返回：

```json
{
  "request_id": "3d7f4444-d063-48e9-9d25-339860866c1a",
  "status": "pending",
  "expires_at": "2026-08-25T12:10:00+00:00"
}
```

查询请求：

```http
GET /eye/requests/{request_id}
Authorization: Bearer <SENSE_TOKEN>
```

完成后 `visual_facts` 形如：

```json
{
  "scene": "Android 设置页面",
  "visible_people": [],
  "actions": [],
  "objects": ["设置列表", "返回按钮"],
  "screen_text": ["设置", "网络和互联网"],
  "uncertainties": ["状态栏中一个小图标无法确认"]
}
```

结果只陈述可观察事实；无法确认的内容必须进入 `uncertainties`，不做现实人物身份识别，也不输出 Xiaxia 人格化回复。

### Device-only API

这些接口供 Tasker/device worker 调用，复用同一 `SENSE_TOKEN`，但故意不写入 `openapi.yaml`，因此不会成为 Custom GPT Actions：

- `GET /eye/device/requests/next`
- `POST /eye/device/requests/{request_id}/screen`
- `POST /eye/device/requests/{request_id}/failure`

领取无任务时：

```json
{
  "status": "empty",
  "request": null
}
```

有任务时，服务器原子把最早 pending request 改为 `capturing`。Tasker 只在这时截一张当前屏幕。

截图上传支持两种形式：

```http
POST /eye/device/requests/{request_id}/screen
Authorization: Bearer <SENSE_TOKEN>
Content-Type: image/png

<raw PNG bytes>
```

或 `multipart/form-data`，文件字段必须名为 `screen`。支持 PNG、JPEG、WebP，最大 8 MiB。接口同步等待 Vision Worker；Tasker HTTP timeout 应大于 `VISION_TIMEOUT_SECONDS`。如果网络超时，不要重新截图或盲目重传，先查询 `GET /eye/requests/{request_id}`。

设备无法截图时应明确回报：

```http
POST /eye/device/requests/{request_id}/failure
Authorization: Bearer <SENSE_TOKEN>
Content-Type: application/json
```

```json
{
  "error_code": "secure_screen",
  "message": "The foreground app blocks screenshots."
}
```

支持的设备错误码：`screenshot_permission_denied`、`screenshot_blocked`、`secure_screen`、`capture_failed`、`device_error`。

### Eye lifecycle

```text
pending → capturing → uploaded → analyzing → completed
        ↘ failed / expired
```

- Request 从创建起 10 分钟内未完成会转为 `expired`。
- `completed`、`failed`、`expired` 及结构化 facts 从创建起保留 24 小时，之后由正常 Eye 请求/轮询触发清理。
- 所有状态都可经 GPT 查询接口观察；失败包含稳定 error code 和不含 secret 的说明。

### Screenshot privacy and cleanup

本实现不需要 Supabase Storage：

1. Tasker 只在领取一个 Eye request 后截图。
2. 图片直接上传到当前 Reality Server，最多 8 MiB，只存在于该 HTTP 请求的进程内存。
3. 服务端将图片直接交给配置的 Vision adapter。
4. 无论成功或失败，处理结束时立即丢弃图片变量；图片不会写入 PostgreSQL、文件系统或对象存储。
5. PostgreSQL 只保存短期结构化 facts 和错误信息。

因此没有永久 URL、bucket、service-role key、截图相册或 object-storage orphan。若进程异常退出，进程内存由操作系统回收；数据库中停留在 `capturing/uploaded/analyzing` 的请求会在 10 分钟 TTL 后过期。该设计不承诺对 RAM 做密码学清零；所选 Vision provider 对输入数据的处理/保留政策仍需由部署者单独确认。

### Android / Tasker real-device boundary

服务器实现不会绕过 Android 安全机制：

- Tasker 使用的截图动作、MediaProjection 授权、系统确认、前台服务要求取决于 Android 版本、Tasker 版本和已授予权限，必须真机验证。
- Android 14 及以后对 MediaProjection 会话和用户同意有更严格要求；不能把服务器测试当作设备端自动截图已经成功。
- 前台 App 使用 `FLAG_SECURE` 等保护时，Tasker 应回报 `secure_screen` 或 `screenshot_blocked`，不得尝试绕过。

推荐轮询：把 Eye poll 加入现有 Tasker 定时流程，但 Eye 没有 pending request 时绝不触发截图。后台轮询频率需结合 Android 电池限制实测。本项目不生成复杂 Tasker XML。

## Custom GPT Action schema

`openapi.yaml` 保留原 Reality、Phone、Spatial、Personal Places、Route、Hand Actions，并只新增两个 GPT 可见 Eye operation：

- `createEyeScreenRequest`
- `getEyeScreenRequest`

Hand / Eye request body 顶层保持 `type: object`；没有顶层 `oneOf`、`discriminator`、server variables 或数组型 `type`。`on/off` enum 均显式加引号。所有 operationId 唯一，服务器 URL 保持当前生产值。

Tasker 的 Hand claim/result 和 Eye device endpoints 都不会暴露给 Custom GPT。Schema 中不存在 `execute_anything` 或 `run_tasker_command`。

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
python -m openapi_spec_validator openapi.yaml
```

自动化覆盖 Knock whitelist/lifecycle/migration、Eye 创建/原子领取/上传/完成/失败/过期/清理/provider failure/鉴权/接口边界、OpenAPI Actions 兼容性，以及既有 Hand、Reality、Phone Activity、Spatial 路由回归。

服务器自动化通过只代表 `Server implementation complete`。Android 截图权限、Tasker capture/upload、`FLAG_SECURE` 行为、Knock 震动节奏和完整 Custom GPT 真机链路仍属于 `Android Tasker real-device validation pending`。
