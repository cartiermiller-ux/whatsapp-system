# 运行健康检查

`tools/check_runtime_health.py` 只读检查两个 systemd 服务、API OpenAPI 响应与 PostgreSQL `SELECT 1`，不会发送 WhatsApp 消息、采购资源或修改余额。全部通过退出 0，任一失败退出 1；日志只输出检查名称与结果，不输出连接字符串或异常正文。

当前告警方式为 systemd journal，不配置外部通知。该检查验证进程与数据库可达性，不代表 WhatsApp 账号已登录，也不检测供应商业务可用性。

在 cartier.us.cc 服务器部署以上脚本和两个 unit 文件后运行：

```sh
install -m 644 deploy/server/whatsapp-healthcheck.service /etc/systemd/system/
install -m 644 deploy/server/whatsapp-healthcheck.timer /etc/systemd/system/
systemctl daemon-reload
systemctl start whatsapp-healthcheck.service
systemctl enable --now whatsapp-healthcheck.timer
journalctl -u whatsapp-healthcheck.service -n 20 --no-pager
systemctl list-timers whatsapp-healthcheck.timer
```

模板使用 `/www/wwwroot/cartier.us.cc/.venv-linux/bin/python` 和 `/etc/whatsapp/database.env`，迁移到其他目录时同步修改。每次检查结束后间隔一分钟运行；失败保留在 journal 和 service 状态中，下一次仍继续检查。

## 下一阶段的范围

- 第三方资源：选定供应商后按公开 API 对接，覆盖超时、余额不足、重复提交与资源释放。
- 真实发送：账号就绪、指定接收号码和预算后开展小批量验证，当前保持真实发送关闭。
- 多租户：现有 tenant 主要用于用户管理。对外销售前，需要为账号、号码、代理、群、任务、会话、订单和账本补齐租户归属，并验证 API、后台执行器和回调均按租户处理。
- 计费：已有充值防重复入账；仍需完成租户钱包、扣费原子性、重试幂等、失败退款及并发余额测试。
