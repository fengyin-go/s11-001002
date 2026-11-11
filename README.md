# 智能采集调度平台

面向多源网页采集、增量抓取、自动化流程编排、采集结果校验与失败重试的智能数据采集调度平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集引擎 | `collector` | 采集任务 | 任务编号、目标网址、HTTP方法 |
| 页面抽取规则 | `crawlrule` | 抽取规则 | 规则编号、入口地址、列表选择器 |
| 内容解析器 | `parser` | 解析模板 | 模板编号、目标字段名、XPath表达式 |
| 增量采集 | `increment` | 增量游标 | 游标编号、来源标识、增量字段 |
| 限速调度 | `ratelimit` | 限速策略 | 策略编号、目标域名、并发上限 |
| 失败重试 | `retry` | 重试策略 | 策略编号、失败类型、最大重试次数 |
| 自动化流程 | `rpaflow` | 流程编排 | 流程编号、入口URL、页面定位器 |
| 验证码识别 | `captcha` | 识别方案 | 方案编号、验证码类型、识别服务地址 |
| 代理池管理 | `proxy` | 代理节点 | 节点编号、代理地址、代理协议 |
| 会话状态 | `session` | 会话配置 | 配置编号、登录网址、Cookie策略 |
| 链路分发 | `router` | 分发规则 | 规则编号、来源URL模式、目标引擎 |
| 采集校验 | `validate` | 校验规则 | 规则编号、校验目标字段、校验表达式 |
| 去重过滤 | `dedup` | 去重策略 | 策略编号、业务键列、相似度算法 |
| 格式归一 | `format` | 转换规则 | 规则编号、输入字段、输出字段 |
| 采集流水线 | `pipeline` | 流水线编排 | 流水线编号、阶段顺序、阶段名称 |
| 采集存储 | `storage` | 存储配置 | 配置编号、存储类型、连接地址 |
| 采集监控 | `monitor` | 监控指标 | 指标编号、监控目标、采集频率 |
| 定时调度 | `scheduler` | 调度计划 | 计划编号、Cron表达式、关联任务 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

### 动作接口协议（采集引擎 / 定时调度）

- 动作放在请求体顶层 `action`，幂等令牌放在顶层 `token`；同时兼容旧协议
  `values.action`。两处都传且取值不一致时返回 `ok=false` 并说明「动作冲突」，
  不会任选一个执行。
- 判定成败以响应体的 `ok` 为准，不能只看 HTTP 状态：业务拒绝也是 HTTP 200、
  `ok=false`，`message` 里是后端给出的可读原因，前端需原样展示且不本地改行数据。
- 带 `token` 的请求按「模块 + 记录 + 令牌」幂等：同一令牌的重复或并发提交只执行
  一次，后续请求回传同一份最终结果（`duplicate=true`）；同令牌换动作返回 409。
- 状态机由后端统一校验。采集引擎：暂停仅允许 `运行中→已停用`、恢复仅允许
  `已停用→运行中`，`已完成` 为终态、不得恢复；定时调度：草稿必须先 `提交校验`
  才能 `启用计划`，禁止跳级。

### 测试

```bash
# 后端单元 + 接口回归（TestClient，含旧协议、冲突、重复/并发、非法动作、终态保护）
python3 -m pytest backend/tests -m "not e2e"

# 真实浏览器端到端（Playwright 驱动 Chromium，起真实 uvicorn + vite）
ENABLE_BROWSER_E2E=1 BROWSER_LIB_ROOT=<浏览器本地依赖前缀> \
  python3 -m pytest backend/tests -m e2e
```

端到端用例通过 `POST /api/testing/reset` 重置内存数据，该钩子仅在后端设置
环境变量 `ENABLE_TEST_RESET=1` 时可用，默认关闭。

领域：数据工程
子方向：数据采集、爬虫与RPA
