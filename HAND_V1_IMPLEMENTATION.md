# Xiaxia Hand V1 修改说明

> 本文件保留为稳定版 V1 历史验收记录。V1.1 当前实施情况见
> `REALITY_HAND_V1_1_IMPLEMENTATION.md`。

## Scope

本轮是对 Xiaxia Reality Server 稳定版的增量升级。未重写 `app.py` 主结构，未修改任何既有 Reality / Phone Activity / Spatial 返回格式，未删除既有路由，未创建第二套服务器或认证体系。

## New files

- `hand.py`：Hand V1 白名单验证、PostgreSQL 存储、原子领取、结果状态机、四个 Flask API。
- `migrations/20260824_001_create_hand_commands.sql`：Supabase PostgreSQL migration。
- `openapi.yaml`：Reality、Phone、Spatial 与 Hand 的 Custom GPT Action Schema。
- `tests/test_hand.py`：Hand V1 API、参数与状态测试。
- `tests/test_regression.py`：稳定版关键路由隔离回归测试。
- `requirements-dev.txt`：测试依赖。
- `pyproject.toml`：pytest 项目路径与测试目录配置。
- `HAND_V1_IMPLEMENTATION.md`：本修改说明。

## Modified files

- `app.py`
  - 导入 `ensure_hand_schema` 与 `register_hand_routes`。
  - 在既有 `get_db()` 中增量初始化 Hand 表。
  - 在同一 Flask app 上注册 Hand 路由。
- `README.md`
  - 扩展为完整部署、Hand API、Tasker 接入、状态机和 Action Schema 说明。

## Database changes

新增 `hand_commands` 表：

- `id UUID PRIMARY KEY`
- `action TEXT`，数据库 CHECK 限制 8 个动作
- `parameters JSONB`
- `status TEXT`，数据库 CHECK 限制 `pending / delivered / executed / failed / expired`
- `created_at / delivered_at / executed_at / expires_at`
- `result JSONB`
- `error TEXT`

新增 pending 队列和 status/created_at 两个索引。既有表未修改。

## API changes

- `POST /hand/commands`
- `GET /hand/commands/next`
- `POST /hand/commands/{command_id}/result`
- `GET /hand/commands/{command_id}`

四个接口全部复用现有 `SENSE_TOKEN` Bearer 鉴权。

## Delivery and duplicate-execution protection

- 领取顺序：`created_at ASC, id ASC`。
- 并发控制：`FOR UPDATE SKIP LOCKED`。
- 状态变更与领取在同一条 `UPDATE ... RETURNING` 中完成。
- 只有 `pending` 可以被领取；领取后立刻成为 `delivered`，不会重复发放。
- 只有 `delivered` 可以写入 `executed / failed`。
- 同终态重复回传返回幂等成功；冲突终态返回 `409`。
- 未完成命令 24 小时后标记为 `expired`。

## Final verification

- Python 语法编译：通过。
- OpenAPI 3.1 标准校验：`openapi.yaml: OK`。
- 自动化测试：`33 passed`。
- 原稳定版业务路由：无删除、无方法变更。
- Hand V1 新增路由：4 条。
- 真实 Supabase、Render 与 Android Tasker 未在离线工程环境中代替用户执行；部署后需按 README 做生产连接与真机验收。

## Final production cleanup

- Temporary `/debug/hand-routes` deployment diagnostic endpoint removed.
- `hand_commands` final rows (`executed`, `failed`, `expired`) are retained for 7 days, then deleted automatically.
- Hand cleanup is throttled to at most once per 10 minutes per server worker and is driven by normal Hand traffic/polling. Empty `/hand/commands/next` polls do not insert database rows.
- `openapi.yaml` is synchronized with the Custom GPT Actions-compatible schema used in production.
