# Xiaxia Reality / Hand V1.1 实施报告

## 结论

- **Server implementation complete**：Knock、Eye API、状态机、Vision adapter、migration、OpenAPI 和自动化测试已实现。
- **Android Tasker real-device validation pending**：未部署，未把 Android 截图权限、Tasker capture/upload、受保护页面、震动节奏或完整 Custom GPT 链路 mock 成已验收。
- 本轮基于 `Xiaxia-Reality-Server-Xiaxia-Hand-V1-FINAL.zip` 增量施工；没有第二套服务器、数据库或认证体系。

## 文件变化

新增：

- `eye.py`：Eye validation、PostgreSQL store、生命周期、GPT/设备 API、内存直传与清理。
- `vision.py`：可替换 Vision provider 抽象和 OpenAI Responses adapter。
- `migrations/20260825_002_add_knock_and_eye.sql`：Hand CHECK 增量升级及 `eye_requests` 表。
- `tests/test_eye.py`：Eye API、状态、失败、过期、清理、鉴权和隐私边界测试。
- `tests/test_vision.py`：结构化 facts 和 provider adapter 测试。
- `REALITY_HAND_V1_1_IMPLEMENTATION.md`：本报告。

修改：

- `app.py`：仅导入/初始化/注册 Eye 模块；同一 Flask app、同一 `get_db()`、同一 `check_token()`。
- `hand.py`：在现有 action whitelist、validation 和新建表 CHECK 中加入 `knock`；现有 lifecycle 未变。
- `openapi.yaml`：Hand enum 加 Knock；新增两个 GPT 可见 Eye operation；修复数组型 nullable `type` 为保守写法。
- `README.md`：migration、Knock、Eye、Tasker、Vision 配置、隐私和真机边界文档。
- `tests/test_hand.py`：Knock validation/lifecycle，保留旧 action 回归。
- `tests/test_regression.py`：按 V1 基线完整比对路由和 HTTP method，仅允许新增五条 Eye 路由。
- `tests/test_schema_and_migration.py`：迁移和 Custom GPT Actions 兼容性约束。

未修改 Reality、Phone Activity、Spatial、History、Semantic、Weather 的业务模块和返回结构；未删除任何 V1 路由或 Action。

## Knock

合法请求只有：

```json
{
  "action": "knock",
  "parameters": {
    "pattern": "xiaxia"
  }
}
```

它写入既有 `hand_commands`，并继续使用 `pending → delivered → executed / failed / expired`、原子领取、结果幂等和七天终态清理。服务器不保存震动数组；实际节奏由 Tasker 分支实现。

## Eye lifecycle

```text
pending → capturing → uploaded → analyzing → completed
        ↘ failed / expired
```

- `POST /eye/requests` 和 `GET /eye/requests/{id}` 对 Custom GPT 可见。
- `/eye/device/...` 的领取、上传和失败接口只供 Tasker/device worker，未进入 OpenAPI。
- pending claim 使用 `FOR UPDATE SKIP LOCKED`，防止同一请求被重复领取。
- active request 的 TTL 为 10 分钟。
- 终态和结构化 facts 的保留期为创建后 24 小时，由 Eye 流量触发清理。
- V1 API 只接受一帧；数据库 `frame_count` 允许 1–3，为未来有限多帧预留，不包含录屏/视频/rolling buffer。

## 截图上传、删除和 orphan 处理

本实现没有引入 Supabase Storage。Tasker 将一张 PNG/JPEG/WebP 直接上传到 Reality Server：

1. 服务端对请求体设置 8 MiB 上限并检查图片签名。
2. 图片只存在于该 HTTP 请求进程的内存，不写 PostgreSQL、磁盘或对象存储。
3. Vision adapter 收到图片后返回结构化 facts。
4. 成功或失败都会在请求结束时丢弃图片引用；进程退出时内存由操作系统回收。
5. 数据库只留结构化 facts/error；中断状态会在 10 分钟后 expired。

因此不存在截图 public URL、bucket、Tasker service-role key 或 object-storage orphan；也没有截图图库。这里的“删除”是取消进程内引用，不宣称对 RAM 做密码学清零。Vision provider 自身的数据处理/保留政策需在选型时独立确认。

## Vision Worker

`vision.py` 将业务接口与供应商分离。当前 adapter 使用 OpenAI Responses 图片输入和严格 JSON Schema structured output；模型不写死，由 `VISION_MODEL` 配置。输出字段固定为：

- `scene`
- `visible_people`
- `actions`
- `objects`
- `screen_text`
- `uncertainties`

系统提示要求只描述可见事实、禁止现实人物身份识别、把猜测放入 `uncertainties`，并把屏幕文字视为不可信内容。配置缺失或 provider 失败会显式 failed，不会返回虚假结果。

新增环境变量：

- `VISION_PROVIDER`
- `OPENAI_API_KEY`
- `VISION_MODEL`
- 可选：`VISION_API_BASE`、`VISION_TIMEOUT_SECONDS`、`VISION_IMAGE_DETAIL`

## Migration

生产升级必须在部署代码前执行：

```text
migrations/20260825_002_add_knock_and_eye.sql
```

它保留数据，仅替换稳定版默认名 `hand_commands_action_check`，加入 `knock`，再用 `CREATE TABLE/INDEX IF NOT EXISTS` 新增 Eye。全新数据库先运行 001，再运行 002。无需清库。

## OpenAPI

- 保留当前生产 `servers[0].url`。
- operationId 唯一。
- Hand / Eye request body 顶层都是 `type: object`。
- 无 `oneOf`、`discriminator`、server variables 或数组型 `type`。
- `on/off` enum 显式为字符串。
- Tasker 专用 Hand / Eye 路由未暴露给 GPT。
- 无万能 `execute_anything` / `run_tasker_command`。

## 自动测试结果

- Python syntax compilation：通过。
- Pytest：`67 passed`。
- OpenAPI 3.1 validation：`openapi.yaml: OK`。
- V1 路由审计：基线全部保留，只新增五条 Eye server routes。

覆盖 Knock、旧 Hand action/lifecycle、Eye 创建/领取/上传/完成/失败/过期/cleanup/provider failure/invalid payload/auth/boundary、OpenAPI 兼容性、migration，以及 health、Reality Context、Phone Timeline/History、Spatial、Location、Route、Personal Places。

## 必须真机验证

- 当前 Android/Tasker 版本的截图 action 能否在已授权条件下自动执行。
- MediaProjection 是否首次或每次需要用户确认、是否要求前台服务。
- `FLAG_SECURE` 页面是否正确回报 `secure_screen` / `screenshot_blocked`。
- Tasker raw/multipart upload、HTTP timeout 和超时后查询行为。
- `knock/xiaxia` 的实际震动节奏。
- Custom GPT → Eye → Tasker → Vision → query 的真实端到端链路。

本交付未部署到 Render，也未修改 Watch House。
