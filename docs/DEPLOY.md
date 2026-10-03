# 部署到服务器

面向：把整套系统装到一台 Linux 服务器（宝塔面板 / 阿里云 ECS）上，浏览器打开就能用。

---

## 0. 一句话结论

**这台服务器上目前什么都没装。** 具体情况见文末「排查记录」。

---

## 1. 需要什么

| 项目 | 要求 | 说明 |
|---|---|---|
| 系统 | CentOS 7+ / Alibaba Cloud Linux / Ubuntu 20.04+ | 宝塔支持的系统都行 |
| Python | **3.11 或更高** | 脚本会自动找/装 |
| 内存 | 1 GB 以上 | SQLite + FastAPI 很轻 |
| 磁盘 | 2 GB 以上 | 主要给 Python 依赖 |
| 端口 | 放行 **80** | 阿里云要在**安全组**里放行，不只是服务器防火墙 |
| Node.js | 不需要 | 前端在本机构建好再上传 |

> 服务器上不需要装 Node、不需要装 MySQL。数据库就是项目目录下的一个 `whatsapp.db` 文件。

---

## 2. 部署（三条路，选一条）

### 路线 A：SSH 进去一行命令（最快）

前提：你能 SSH 登录服务器。

```bash
# 1) 在本地打包
python deploy/package.py --build

# 2) 上传（把 <IP> 换成你的服务器地址）
scp dist-deploy/whatsapp-system-*.tar.gz root@<IP>:/tmp/

# 3) 登录服务器并安装
ssh root@<IP>
mkdir -p /www/wwwroot
tar -xzf /tmp/whatsapp-system-*.tar.gz -C /www/wwwroot/
cd /www/wwwroot/whatsapp-system-*/
bash deploy/server/install.sh
```

脚本跑完会打印访问地址和默认账号。

### 路线 B：宝塔面板上传

1. 本机执行 `python deploy/package.py --build`，得到 `dist-deploy/whatsapp-system-*.tar.gz`
2. 宝塔面板 → **文件** → 进入 `/www/wwwroot/` → **上传** → 选中那个 tar.gz
3. 右键压缩包 → **解压**
4. 宝塔面板 → **终端** → 执行：
   ```bash
   cd /www/wwwroot/whatsapp-system-*
   bash deploy/server/install.sh
   ```
5. 如果脚本提示找不到 Python 3.11：宝塔 → **软件商店** → 搜「Python项目管理器」装上，再重跑第 4 步

### 路线 C：直接在服务器上从 GitHub 拉

仓库是私有的，需要先配好部署密钥（Deploy Key）。配好后：

```bash
cd /www/wwwroot
git clone git@github.com:cartiermiller-ux/whatsapp-system.git
cd whatsapp-system
npm --prefix frontend ci && npm --prefix frontend run build   # 需要服务器有 Node
bash deploy/server/install.sh
```

> 服务器在国内的话 Node 装依赖会很慢，**推荐路线 A/B**（本地构建好再传）。

---

## 3. 装完之后

| 地址 | 说明 |
|---|---|
| `http://<IP>/` | 管理后台 |
| `http://<IP>/login` | 登录页 |
| `http://<IP>/docs` | 接口文档（Swagger） |
| 账号 | `admin` / `admin123` —— **登录后立刻改密码** |

常用运维命令：

```bash
systemctl status whatsapp-api      # 看后端状态
systemctl restart whatsapp-api     # 重启后端
tail -f /www/wwwroot/whatsapp-system-*/logs/api.log   # 看日志
```

---

## 4. 让扫码能出二维码（重要）

国内服务器**直连 `web.whatsapp.com` 会被黑洞**，表现为二维码一直转圈。必须给后端配一个能出海的代理：

1. 在服务器上跑一个代理客户端（或者局域网里有一台能出海的机器）
2. 编辑项目目录下的 `.env`：
   ```ini
   WA_PROXY_URL=socks5://127.0.0.1:10808
   ```
   HTTP 代理写成 `http://127.0.0.1:7890` 也一样。
   SOCKS5 需要额外装包：`npm i -g socks-proxy-agent`（HTTP 代理不需要）。
3. 重启后端：`systemctl restart whatsapp-api`
4. 先体检再扫码：
   ```bash
   cd /www/wwwroot/whatsapp-system-*
   python tools/check_network.py --proxy socks5://127.0.0.1:10808 --scan
   ```
   看到 `[OK] HTTP/1.1 101` 就说明链路通了。

---

## 5. 更新版本

```bash
# 本地重新打包上传
python deploy/package.py --build
scp dist-deploy/whatsapp-system-*.tar.gz root@<IP>:/tmp/

# 服务器上覆盖安装（install.sh 幂等，不会动你的 .env 和数据库）
cd /www/wwwroot
tar -xzf /tmp/whatsapp-system-*.tar.gz -C /www/wwwroot/
cd whatsapp-system-新目录
cp 上一版的/.env .            # 如果想保留旧配置
cp 上一版的/whatsapp.db .     # 如果想保留旧数据
bash deploy/server/install.sh
```

`install.sh` 只做三件事：装依赖、写 systemd 单元、写 nginx 配置。**不会删数据、不会覆盖已有的 `.env`。**

---

## 6. 出问题了怎么查

按顺序自测，能定位到是哪一层坏了：

```bash
# 1) 后端活着吗
systemctl status whatsapp-api
curl -s http://127.0.0.1:8000/api/v1/auth/login -X POST \
     -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"admin123"}'
# 期望：{"code":0,"data":{"token":"..."}}

# 2) nginx 转发正常吗
curl -I http://127.0.0.1/
curl -s http://127.0.0.1/api/v1/dashboard/overview -o /dev/null -w '%{http_code}\n'

# 3) 从外面能通吗（在本地电脑上跑）
curl -I http://<IP>/
```

| 现象 | 原因 | 处理 |
|---|---|---|
| 浏览器 404 | nginx 站点没配好 / 前端产物没上传 | 看 `nginx -t`、确认 `frontend/dist/index.html` 存在 |
| 显示「没有找到站点」 | 宝塔里没有站点绑定 80 | 重跑 `install.sh`，或宝塔里手动加站点指向 `frontend/dist` |
| 打不开、超时 | 阿里云**安全组**没放行 80 | 阿里云控制台 → 安全组 → 入方向 → 放行 80 |
| 502 Bad Gateway | 后端没起来 | `systemctl status whatsapp-api`、看 `logs/api.log` |
| 页面能开、接口全 401 | 登录态失效 | 重新登录；确认系统时间正确 |
| 扫码一直转圈 | 到 WhatsApp 的网络不通 | 见上面第 4 节，配 `WA_PROXY_URL` |

---

## 7. 排查记录（2026-10-03）

针对 `120.24.175.80` 的实测结论：

| 检查项 | 结果 |
|---|---|
| `http://120.24.175.80/` | **200**，内容是宝塔的「没有找到站点」→ **没有站点绑定 80** |
| `http://120.24.175.80/login` | **404** → 与你看到的现象一致 |
| `http://120.24.175.80/api/v1/health` | **404** → 后端不存在 |
| `https://120.24.175.80:33416/` | **200**，宝塔「安全入口校验失败」→ 面板活着，但入口地址 `a6fe4385` 已失效 |
| SSH `root@120.24.175.80` | 端口 22 通，提示 `Permission denied (publickey,password)` → **密码登录是开的**，但本机密钥未授权 |
| 到 WhatsApp 的连通性 | IPv4 / IPv6 的 TCP 443 **全部挂起** → 需要代理，见第 4 节 |

**结论：这台机器上从未部署过本系统。** 桌面上的 `暗夜社区.txt` 里那行「WhatsApp超链群发 / 后台 `http://120.24.175.80/login`」是计划记录，不是已完成的部署。

要拿到宝塔面板入口，在服务器上执行：

```bash
bt 14        # 查看面板地址和安全入口
bt default   # 查看面板默认信息
```
