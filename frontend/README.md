# WhatsApp 运营系统 · 前端

基于清单实现的运营后台前端。技术栈：**Vue 3 + TypeScript + Vite + Element Plus + Pinia + Axios + ECharts**。

## 快速开始

```bash
cd frontend
npm install
npm run dev      # 开发：http://127.0.0.1:5173
npm run build    # 生产构建（含 vue-tsc 类型检查）
npm run preview  # 预览构建产物
```

后端 FastAPI 默认地址 `http://127.0.0.1:8000`，已在 `vite.config.ts` 中配置 `/api` 代理，
前端请求 `/api/v1/*`，无需后端改动 CORS。改后端地址设置环境变量 `VITE_BACKEND_ORIGIN`。

## 页面与接口对应关系

| 页面 | 路由 | 对接情况 |
|------|------|----------|
| 登录 | `/login` | ✅ 真实：`POST /auth/login` |
| 数据看板 | `/dashboard` | ✅ 真实：`GET /dashboard/today`、`GET /accounts` |
| 号码池管理 | `/numbers` | ✅ 真实：列表(分页/状态/来源/搜索) `GET /numbers` + 导入 `POST /numbers/import`；删除/导出待接入 |
| 注册管理 | `/register` | ✅ 真实：`POST /register/batch`、`GET /register/status`；失败归因待接入 |
| 账号管理 | `/accounts` | ✅ 真实：`GET /accounts`、`GET /accounts/{id}`、`POST /accounts/{id}/pause|resume`；养号明细待接入 |
| 资源群管理 | `/groups` | ✅ 真实：`GET /groups`（营销价值分排序）；群链接获取/导入导出/删除待接入 |
| 群发任务 | `/mass-send` | ✅ 真实：`GET/POST /mass-send/tasks`、`GET /mass-send/tasks/{id}`；策略/定时/点击待接入 |
| 拉群任务 | `/pull-group` | ✅ 真实：`POST /invite/tasks`、`GET /invite/tasks` |
| 广告消息管理 | `/ads` | ⛔ 占位（文案 / 超链 / 效果统计，后端未提供） |
| 余额与计费 | `/billing` | ✅ 真实：`GET /balance`、`GET /balance/transactions`；充值/计费规则待接入 |
| 个人中心 | `/profile` | 部分真实（登录态）；改密 / 操作日志待接入 |
| 系统设置 | `/settings` | ✅ 全局参数真实：`GET /settings`（只读）；用户/租户/权限待接入 |

## 待接入接口清单

- 号码池：`DELETE /api/v1/numbers`（批量删除）、导出
- 注册：`GET /register/status` 的 `failure_reason`（失败归因）
- 账号：`GET /accounts/{id}/nurture`（养号明细）
- 资源群：批量获取群链接、导入 / 导出、批量删除；更多筛选维度（JID/链接/账号/号段/管理员）
- 群发：`click` 点击数、发送策略 / 定时发送参数
- 拉群：任务进度与成功率、失败原因分类
- 广告：`/api/v1/ads/*`
- 计费：`POST /balance/recharge`、`GET /balance/rules`（国家收费规则）
- 系统设置：`PUT /settings`、`/api/v1/admin/*`（用户 / 租户 / 权限）
- 个人中心：`GET /me`、`POST /me/password`、`GET /me/logs`

## 目录结构

```
src/
  api/          request.ts（统一解包 { code, data }）+ index.ts（全部接口封装）
  components/   EChart 封装、PlaceholderPanel（待接入占位组件）
  layouts/      后台主框架（侧边菜单 / 顶栏 / 租户切换）
  router/       路由与登录守卫
  stores/       Pinia：auth（登录态）
  types/        与后端一致的接口类型
  utils/        格式化与解析工具
  views/        12 个业务页面
```
