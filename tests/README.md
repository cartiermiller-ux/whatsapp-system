# 测试脚本

所有脚本都用标准库 + \`requests\`，不需要 pytest。**请在仓库根目录执行**（脚本会 \`import main\`）。

\`\`\`powershell
pip install requests
\`\`\`

## 1. 发送逻辑自测（不需要联网、不需要起服务）

\`\`\`powershell
python tests/real_send_test.py
\`\`\`

用假 bot 替换 wasock，覆盖：目标解析（含 \`resource_group.id\` 与 \`number_pool.id\` 冲突的场景）、
文案变量渲染、重试、计数、TaskLog、五条失败与前置校验分支、\`USE_REAL_SEND\` 分流、
发送间隔取值、登录态判定。共 49 项断言。
临时库写在 \`tests/.tmp/\`，不会碰 \`whatsapp.db\`。

## 2. 接口回归（P2 模块，109 项断言）

先起一个隔离的后端，再跑脚本：

\`\`\`powershell
# 终端 A
$env:WHATSAPP_DATABASE_URL='sqlite:///./tests/.tmp/api_test.db'
python -m uvicorn main:app --host 127.0.0.1 --port 8099

# 终端 B
python tests/p2_api_test.py
\`\`\`

覆盖鉴权、广告文案/超链 CRUD、短链跳转计点击、余额与充值到账、个人中心与改密、
用户管理权限、系统参数校验等。

## 3. 群发任务 HTTP 链路（9 项断言）

复用上面 8099 的服务：

\`\`\`powershell
python tests/mass_send_http_test.py
\`\`\`

验证开关关闭时任务确实由 \`simulate_mass_send\` 跑完，且 \`target_type\` 正确落库与返回。

## 4. WhatsApp 网络诊断（排查连不上 / 不出二维码）

\`\`\`powershell
python tests/wa_net_diag.py
\`\`\`

会连续解析 \`web.whatsapp.com\`、逐个 IP 测 443 连通性，并检测本机代理端口
（常见的 10808/10809）。判定依据见 \`docs/TROUBLESHOOTING.md\`。
