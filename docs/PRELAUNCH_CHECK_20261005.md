# 2026-10-05 上线检查与修复记录

部署目标：`https://cartier.us.cc`，Linux 服务器 `103.42.182.238`。依据用户清单执行，数据库迁移已由用户确认在本次一并完成。

## 安全与配置

| 清单项 | 核实与结果 |
| --- | --- |
| 自动开户 | 默认关闭，生产 `AUTO_PROVISION_USERS=false`；未知用户名登录返回 401，不创建用户 |
| JWT 密钥 | 当前没有 JWT，使用 `secrets.token_urlsafe(24)` 签发进程内随机会话 token；没有添加硬编码开发签名密钥 |
| 鉴权绕过 | 删除旧 `mock-token-用户名` 兼容分支；冒充管理员返回 401 |
| 调试与 CORS | `debug=False`，生产启动无 `--reload`；白名单为 `https://cartier.us.cc`，拒绝通配符配置 |
| 真实发送 | 环境文件与持久化服务配置均保持 `USE_REAL_SEND=false` |
| 密码散列 | 现有 PBKDF2-HMAC-SHA256、独立随机盐、120000 次迭代、恒定时间比较，满足清单所列最低次数；保留现有用户密码与散列 |
| 敏感接口 | 109 个业务接口方法匿名访问均为 401；登录开放，两个供应商回调分别保留专用凭据/HMAC 校验 |
| 管理员权限 | 普通用户访问用户管理为 403；代理管理员仅能管理本租户运营用户，不能创建或修改管理员，也不能跨租户操作 |
| SQL 注入 | 业务查询使用 ORM；DDL 拼接的表名、字段名、类型来自固定迁移定义，没有拼入用户输入；异常用户名登录测试被拒绝 |
| 前端登录态 | 刷新保留有效登录；退出调用后端登出、清除存储、跳转登录页；原 token 再请求返回 401 |
| 操作审计 | 隔离测试验证登录/退出、改密码、创建/删除用户、系统设置保存、充值订单创建的审计记录 |

随机会话 token 的生成方式参考 [OWASP 会话管理指南](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。会话仍存进程内存：服务重启后需要重新登录，多副本部署前需要共享会话存储。内置管理员密码本次保留，应在个人中心更换默认密码。

## 数据库与运维

生产库已从 SQLite 切换为 PostgreSQL 16，驱动为 psycopg。`WHATSAPP_DATABASE_URL` 优先，兼容 `DATABASE_URL`。数据库密码保存在服务器 `/etc/whatsapp/database.env`，文件权限 600，未放进源码、命令参数或报告。

- 演练及正式迁移均核对 22 张表、106 条记录的逐表内容 SHA256；全部一致。该数字是切换快照的数据，后续正常登录会新增审计记录。
- 验证自增序列可继续插入；目标库非空时迁移工具拒绝覆盖。
- PostgreSQL 仅监听 `127.0.0.1:5432`；应用数据库角色没有超级用户、建库或创建角色权限。
- SQLite 回退副本和正式迁移报告保存在 `/root/whatsapp-backups/postgres-cutover-20261005/`；切换前完整应用备份保存在 `/root/whatsapp-backups/security-20261005/`。
- 新增 `backup.py`：SQLite 使用在线备份 API；PostgreSQL 使用 `pg_dump` 自定义格式，检查归档目录可读，备份失败不留下半成品，备份文件权限 600。
- PostgreSQL 备份已在隔离库实际恢复，并逐表核对内容指纹。`pg_dump` 的一致性备份行为参考 [PostgreSQL 16 文档](https://www.postgresql.org/docs/16/app-pgdump.html)。
- `whatsapp-db-backup.timer` 每日北京时间 03:00 执行，已开启开机恢复调度；首份生产备份已成功生成，目录 `/root/whatsapp-backups/daily/`。
- 当前服务器使用 systemd 常驻服务，替代清单的 Windows nssm。API 与通道均开机自启，分别监听 localhost 8000、5000。
- 前端完成类型检查与构建，由 Nginx 提供静态资源并反代 API；HTTPS 验证通过。

## 验证

SQLite 隔离测试：安全 5 项（包括 109 个业务接口方法）、备份 2 项、运营 20 项、资源管理 4 项，均通过。专用 PostgreSQL 测试库的运营 20 项也全部通过，未向真实 WhatsApp 发送消息或执行真实支付。

生产浏览器验证 11 个页面、扫码登录弹窗、登录后刷新、退出后刷新及旧 token 撤销；没有 JavaScript 运行错误或 HTTP 5xx。

## 运维入口

```bash
systemctl status whatsapp-api whatsapp-wasock
systemctl list-timers whatsapp-db-backup.timer
systemctl start whatsapp-db-backup.service
journalctl -u whatsapp-db-backup.service -n 10 --no-pager
```

恢复与迁移工具只操作明确指定的数据库。生产切回旧 SQLite 前需要评估切换后新增数据，不能在继续写入 PostgreSQL 后直接丢弃这些变更。
