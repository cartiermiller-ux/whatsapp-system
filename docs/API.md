# 接口文档

后端共 **53 个接口**，全部挂在 \`/api/v1\` 下（短链跳转 \`GET /s/{code}\` 例外）。

- 运行时交互文档（可直接调试）：<http://127.0.0.1:8000/docs>
- 服务地址默认 <http://127.0.0.1:8000>

---

## 通用约定

### 响应结构

成功统一返回 \`code: 0\`，业务数据在 \`data\` 里：

\`\`\`json
{ "code": 0, "data": { "total": 1, "page": 1, "size": 20, "list": [] } }
\`\`\`

出错时返回对应 HTTP 状态码（400 / 401 / 403 / 404），并统一包装：

\`\`\`json
{ "code": 400, "message": "单笔充值不能低于 10" }
\`\`\`

### 鉴权

除登录外，所有 \`/api/v1\` 接口都需要携带 token：

\`\`\`http
Authorization: Bearer <token>
\`\`\`

- 登录：\`POST /auth/login\` → \`data.token\`
- token 有效期 72 小时（\`TOKEN_TTL_HOURS\`），存在进程内存中，重启后失效
- 兼容历史格式 \`mock-token-<username>\`
- 修改密码 / 管理员重置密码会**吊销该用户全部 token**
- 角色：\`super_admin\` / \`agent_admin\` / \`operator\`；标注"管理员"的接口要求前两者

### 分页

\`page\`（默认 1）、\`size\`（默认 20，上限 200），返回：

\`\`\`json
{ "total": 100, "page": 1, "size": 20, "list": [ ] }
\`\`\`

---

## 鉴权与个人中心

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | \`/auth/login\` | 登录，返回 token / username / role / tenant；未知用户名在 \`AUTO_PROVISION_USERS=True\` 时自动开户 | 公开 |
| POST | \`/auth/logout\` | 退出并吊销当前 token | 登录 |
| GET | \`/me\` | 当前用户信息（不含密码字段） | 登录 |
| PUT | \`/me\` | 修改昵称 / 邮箱 / 手机号 | 登录 |
| POST | \`/me/password\` | 修改密码 \`{old_password, new_password}\`，成功后全部 token 失效 | 登录 |
| GET | \`/me/logs\` | 操作日志分页，支持 \`action\` \`result\` 筛选 | 登录 |

登录示例：

\`\`\`bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'
\`\`\`

---

## 号码池 / 注册 / 账号

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | \`/numbers/import\` | 批量导入，body 为数组 \`[{phone, source_type, source_channel}]\`，返回 \`{imported, failed}\` |
| GET | \`/numbers\` | 分页列表，支持 \`status\` \`source_type\` \`keyword\` |
| DELETE | \`/numbers\` | 批量删除，body \`{ids: []}\` |
| GET | \`/numbers/export\` | 全量导出（前端转 CSV） |
| POST | \`/register/batch\` | 批量注册（**模拟**），body \`{number_ids: []}\` |
| GET | \`/register/status\` | 注册状态汇总 + 明细 |
| GET | \`/register/analysis\` | 注册失败归因 |
| GET | \`/accounts\` | 账号列表 |
| GET | \`/accounts/{account_id}\` | 账号详情（含号码、设备指纹、IP） |
| POST | \`/accounts/{account_id}/pause\` | 暂停账号 |
| POST | \`/accounts/{account_id}/resume\` | 恢复账号 |

\`source_type\` 取值：\`physical\` 实体卡 / \`virtual\` 虚拟号 / \`sms_platform\` 接码平台（兼容历史中文值）。

---

## 资源群与任务

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | \`/groups\` | 资源群分页，支持 \`keyword\` \`status\`，按营销分倒序 |
| POST | \`/groups/fetch-links\` | 批量获取群链接（**占位**，待 wasock 接入） |
| POST | \`/invite/tasks\` | 创建拉群任务（**仅建单**，无执行器） |
| GET | \`/invite/tasks\` | 拉群任务分页 |
| GET | \`/invite/tasks/{task_id}\` | 拉群任务详情 |
| POST | \`/mass-send/tasks\` | 创建群发任务 |
| GET | \`/mass-send/tasks\` | 群发任务分页 |
| GET | \`/mass-send/tasks/{task_id}\` | 群发进度（status / sent / delivered / read） |
| GET | \`/dashboard/today\` | 看板汇总 |

创建群发任务：

\`\`\`json
POST /api/v1/mass-send/tasks
{
  "task_name": "10月促销第一波",
  "target_type": "group",
  "target_ids": [1, 2, 3],
  "account_ids": [1],
  "message_content": "Hi {name}，看这里 {link}",
  "link_url": "https://example.com/promo"
}
\`\`\`

\`target_type\` 决定 \`target_ids\` 的含义，**必填且不能猜**：

| 取值 | \`target_ids\` 含义 | 解析结果 |
|---|---|---|
| \`group\`（默认） | \`resource_group.id\` | 群的 \`group_jid\` |
| \`contact\` | \`number_pool.id\`，取不到则当手填手机号 | \`<号码>@s.whatsapp.net\` |

> 两张表主键都从 1 开始，只按 ID 猜会把消息发到错误的会话。
> 任务创建后会提交到 FastAPI BackgroundTasks 异步执行，实际走模拟还是真实发送由 \`USE_REAL_SEND\` 决定。

---

## 广告消息

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | \`/ads/copies\` | 文案分页，支持 \`language\` \`status\` \`keyword\`（标题+内容） |
| POST | \`/ads/copies\` | 新建文案，自动提取 \`{name}\` \`{link}\` 等变量 |
| GET | \`/ads/copies/{copy_id}\` | 文案详情 |
| PUT | \`/ads/copies/{copy_id}\` | 局部更新（只传要改的字段） |
| DELETE | \`/ads/copies/{copy_id}\` | 删除单条 |
| DELETE | \`/ads/copies\` | 批量删除，body \`{ids: []}\` |
| GET | \`/ads/copies/{copy_id}/stats\` | 单条文案效果 |
| GET | \`/ads/stats\` | 全量效果汇总 + 逐条列表 |
| GET | \`/ads/links\` | 超链分页，返回里带 \`default_domain\` |
| POST | \`/ads/links\` | 创建超链，自动生成 \`short_code\` |
| PUT | \`/ads/links/{link_id}\` | 更新超链 |
| DELETE | \`/ads/links/{link_id}\` | 删除超链 |
| GET | \`/s/{short_code}\` | **短链跳转**（302，累计点击量，无需鉴权） |

状态取值：文案 \`active\` / \`paused\` / \`draft\`；语言 \`zh\` / \`en\` / \`es\` / \`pt\`。

效果口径是漏斗：\`delivery_rate = 送达/发送\`，\`read_rate = 阅读/送达\`，\`click_rate = 点击/阅读\`，均为 0-100 的百分数。

追踪参数支持 \`{click_id}\` 占位符，跳转时替换为随机串。

---

## 余额与计费

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | \`/balance\` | 余额 / 累计充值 / 累计消费 / 待支付订单 | 登录 |
| GET | \`/balance/transactions\` | 流水分页，支持 \`type\` \`country\` \`keyword\` | 登录 |
| POST | \`/balance/transactions\` | 管理员手工调账 | 管理员 |
| POST | \`/balance/recharge\` | 创建充值订单 \`{amount, chain?}\` | 登录 |
| GET | \`/balance/recharge/orders\` | 订单分页 + 收款地址/链/币种/最低金额；顺手把超时订单置为过期 | 登录 |
| POST | \`/balance/recharge/{order_id}/confirm\` | **模拟到账**（链上回调接入前的过渡接口） | 管理员 |
| POST | \`/balance/recharge/{order_id}/cancel\` | 取消待支付订单 | 登录 |
| GET | \`/balance/rules\` | 国家计费规则（内置常量） | 登录 |

要点：

- **余额 = 全部流水 \`amount\` 之和**，不额外维护余额字段，避免对不上
- 流水 \`type\`：\`recharge\` 充值 / \`consume\` 消费（负数）/ \`refund\` 退款 / \`adjust\` 调账
- 创建充值订单要求 \`recharge_address\` 已配置，金额不低于 \`min_recharge_amount\`
- 订单状态：\`pending\` / \`paid\` / \`cancelled\` / \`expired\`（超时惰性清理）

---

## 系统设置

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | \`/settings\` | 全部参数，**扁平结构** \`{key: value}\` | 登录 |
| GET | \`/settings/schema\` | 参数定义：分组 / 类型 / 取值范围 / 标签 / 当前值 | 登录 |
| PUT | \`/settings\` | 保存参数（局部更新） | 管理员 |

\`PUT\` 只传要改的键：

\`\`\`json
{ "daily_send_limit": 80, "recharge_address": "TXk...", "new_device_cooldown_hours": 0 }
\`\`\`

校验规则：

- 未知键 → 400 \`未知参数：xxx\`
- 类型不符 / 超范围 → 400，例如 \`单账号每日发送上限 不能大于 1000\`
- 跨字段：\`send_interval_min\` 不能大于 \`send_interval_max\`
- 校验失败**不会部分写入**

全部参数含义见 [README 的系统设置项](../README.md#系统设置项)。

---

## 用户管理（管理员）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | \`/admin/users\` | 用户分页，支持 \`keyword\` \`role\` \`status\` |
| POST | \`/admin/users\` | 新建用户（用户名 2-64 位，密码 ≥ 6 位） |
| PUT | \`/admin/users/{user_id}\` | 更新资料 / 角色 / 状态；传 \`password\` 即重置密码 |
| DELETE | \`/admin/users/{user_id}\` | 删除用户 |

保护规则：不能修改自己的角色、不能禁用/删除自己、内置 \`admin\` 不可删除。所有响应都不返回密码字段。
