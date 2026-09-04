# PanBound 复盘与预案系统 — 交接文档

## 项目目标
基于 Flask + MySQL + Redis 的 A 股每日复盘/交易预案平台。LLM 走 MiniMax-M3 (OpenAI 兼容端点),支持中转站手动配置。用户登录需验证码,可接入其他公司 OIDC SSO。报告生成采用多角色辩论工作流 (TradingAgents 风格),平台可配置角色,内置角色不可删除。

## 已完成 (19 个文件,共约 1300 行)
路径统一在 `/Volumes/Samson/PythonProject/PanBound/` 下。

### 配置层
- `config.py` — 12-factor 配置,所有项从 env 读
- `.env.example` — 含 MySQL `172.16.205.22:9301/panbound (root/root@123)`、Redis `172.16.205.22:3311`、MiniMax-M3、中转站配置示例
- `requirements.txt` — Flask 3.0 + SQLAlchemy 2.0 + PyMySQL + redis + Pillow + authlib + requests
- `.gitignore`, `README.md`

### 入口
- `app/__init__.py` — 应用工厂,注册了 auth/sso/reports 三个蓝图,根路由 -> reports.dashboard
- `app/extensions.py` — db / login_manager / csrf / redis 单例

### 数据模型 (SQLAlchemy)
- `app/models/user.py` — `User`(username, password_hash, role, is_active, sso_links 反向)
- `app/models/report.py` — `Report`(trade_date, title, status, raw_context, payload JSON, prompt_used, model_used, error_message, duration_ms)
- `app/models/role.py` — `Role`(name, display_name, role_group, system_prompt, stance, is_builtin, enabled, sort_order, temperature, max_tokens, use_thinking) + `RoleRun`(每次跑报告时每个角色的输入/输出/耗时快照)
- `app/models/sso.py` — `SSOProvider`(通用 OIDC 配置) + `SSOLink`(用户<->外部 subject 多对一)
- `app/models/audit.py` — `AuditLog`(登录/管理审计)

### 鉴权
- `app/auth/captcha.py` — Pillow 生成 PNG,Redis 存原文 + TTL
- `app/auth/routes.py` — `/auth/login`(POST 校验 captcha+密码) + `/auth/logout`

### LLM
- `app/llm/minimax.py` — `MiniMaxClient`(OpenAI 兼容端点,自动带 `reasoning_split: true` + `thinking: adaptive`),返回 `LLMResult(text, reasoning, raw, duration_ms)`
- `app/llm/providers.py` — `LLMProvider` 模型 (支持中转站/官方,带 base_url/api_key/extra_headers/models_json/thinking_mode/timeout),`is_default=True` 的为默认

### 默认角色 (TradingAgents + hermes stock 启发)
- `app/reports/seed_roles.py` — 10 个内置角色,`is_builtin=True`,`name` 不可改:
  1. `data_validator` (input, sort=10) — 校验用户盘面笔记是否覆盖必填字段
  2. `market_observer` (analysis, sort=20) — 大盘指数/成交/涨跌家数强弱判断
  3. `theme_analyst` (analysis, sort=30) — 主线题材 + 龙头识别
  4. `sentiment_analyst` (analysis, sort=40) — 情绪周期 + 监管温度
  5. `technical_analyst` (analysis, sort=50) — 支撑压力/量能/形态
  6. `news_analyst` (analysis, sort=60) — 监管/产业/宏观新闻
  7. `bull_researcher` (debate, sort=70) — 多头论证 (stance=bull)
  8. `bear_researcher` (debate, sort=71) — 空头论证 (stance=bear,看多论点作为输入)
  9. `risk_manager` (risk, sort=80) — 仓位/止损/不做清单
  10. `head_trader` (trader, sort=200) — 综合输出 6 大模块最终 JSON
  - 每个 prompt 都追加了 IRON RULES:二元结论、点名具体标的、量化数字、不允许可能/或许/也许

## 待完成 (8 个任务)

### 1. `app/reports/orchestrator.py`
多角色编排引擎。核心函数:
```
def run_report(report: Report, llm_client, db_session) -> None
```
流程:
1. 加载所有 enabled=True 的 Role,按 sort_order 排序
2. 对每个 role 创建 RoleRun,input_payload=raw_context + 前置角色 output_payload 拼装
3. 顺序调用 `llm_client.chat(role.system_prompt, user_input)`
4. 多空辩论要相互看对方输出 (bear 拿到 bull 输出作为前置)
5. 解析 LLM 返回 JSON,写入 RoleRun.output_payload
6. head_trader 的输出作为 Report.payload
7. 异常时 RoleRun.status='failed',Report.status='failed'
8. 所有 LLM 调用都在 `flask_app.app_context()` 内 (数据库 session 需要)

### 3. `app/reports/service.py`
`create_report(user, trade_date, raw_context, title)` 创建并异步触发 orchestrator
`regenerate_report(report)` 重置 status + RoleRun 后再跑

### 4. `app/reports/routes.py`
蓝图 url_prefix='/reports':
- `GET /reports/` — 列表 (分页)
- `GET /reports/new` — 新建表单
- `POST /reports/new` — 创建并跳转详情
- `GET /reports/<id>` — 详情 (展示 6 大模块 + 每个 RoleRun 的审议过程,JSON pretty print)
- `POST /reports/<id>/regenerate` — 重新生成
- `GET /reports/<id>/status.json` — 状态轮询 API (返回 status + role_run 进度)

### 5. `app/sso/oidc.py` + `app/sso/routes.py`
通用 OIDC 客户端 (authlib 或自实现 Authorization Code Flow):
- 生成 state (存 Redis,TTL 10min)
- 跳到 authorize_url (含 client_id/redirect_uri/scope/state/response_type=code)
- 回调拿 code, 校验 state, 换 token, 拉 userinfo
- 按 SSOLink 查/创建 User,login_user
- 企业微信/飞书/钉钉只是预设了不同的 field mapping (username_field/email_field/subject_field)

### 6. `app/admin/routes.py`
蓝图 url_prefix='/admin',仅 admin 角色可访问:
- `/admin/roles` — 列表 + 新建/编辑/启停 (内置 name 不可改、不可删除)
- `/admin/roles/new`、`/admin/roles/<id>/edit` — 表单
- `/admin/sso` — SSO Provider CRUD
- `/admin/llm-providers` — LLM Provider CRUD (中转站 base_url/api_key/extra_headers)
- `/admin/users` — 用户列表/启停/重置密码

### 7. 模板 (`app/templates/`) + `app/static/css/style.css`
清单:
- `base.html` — 顶部导航 (我的报告/角色管理/SSO/LLM Provider/退出) + flash
- `auth/login.html` — 居中卡片,验证码图片嵌入 data: URI,SSO 按钮区
- `reports/index.html` — 报告列表 (日期/标题/状态/作者/操作)
- `reports/new.html` — 表单 (trade_date + title + raw_context 大文本框)
- `reports/detail.html` — 6 大模块渲染 (盘面快照卡片/表格/连板梯队/题材地图表格/操作计划),下方折叠 RoleRun 审议过程 (按 sort_order 列出,JSON 高亮)
- `admin/roles.html`、`admin/role_form.html`、`admin/sso.html`、`admin/sso_form.html`、`admin/llm_providers.html`、`admin/llm_provider_form.html`、`admin/users.html`
- `errors/{403,404,500}.html`

### 8. `cli.py` + `run.py`
- `cli.py` — Flask CLI 命令:
  - `init-db` — `db.create_all()`
  - `create-admin` — 读 config 里的 ADMIN_USERNAME/ADMIN_EMAIL/ADMIN_PASSWORD 建管理员
  - `seed-roles` — 遍历 `seed_roles.all_builtin_roles()`,upsert (按 name),`is_builtin=True`
  - `seed-default-llm-provider` — 从 env 读 MINIMAX_BASE_URL/MINIMAX_API_KEY/MINIMAX_MODEL 建一个默认 Provider
  - `list-sso` / `list-roles` / `list-providers` 调试用
- `run.py` — `app = create_app()`,注册 CLI,`if __name__ == '__main__': app.run(host='0.0.0.0', port=5000, debug=True)`

### 9. 测试
- `pip install -r requirements.txt`
- `cp .env.example .env` 并填 MINIMAX_API_KEY
- `flask --app run.py init-db`
- `flask --app run.py create-admin`
- `flask --app run.py seed-roles`
- `flask --app run.py seed-default-llm-provider`
- `python run.py`,浏览器打开 `http://127.0.0.1:5000`,admin/admin 登录,新建报告

## 关键设计决策

### 1. 多角色辩论工作流
- 顺序执行,但 bear 角色能拿到 bull 的输出 (辩论)
- 每个角色的输入 = raw_context + 之前所有 RoleRun 的 output_payload JSON 化
- head_trader 是最后一步,综合全部产出生成最终 6 大模块 JSON

### 2. 强约束不允许模糊措辞
所有角色 prompt 末尾追加 IRON RULES:
- 二元结论 (对/错、是/否、做/不做)
- 必须给具体数字 (仓位、止损、连板高度、晋级率)
- 点名 (标的名称+代码)
- 证据不足明说,不猜
- 输出严格 JSON,不要 markdown

### 3. 6 大模块输出 Schema (head_trader)
前端按这个 JSON 渲染,字段名固定:
```
{
  "trade_date", "summary",
  "snapshot": {"SSE":{value,label}, "ChiNext":..., "TotalVolume":..., "BoardHeight":..., "LimitUpDown":..., "AdvanceDecline":..., "EmotionTemp":..., "USOvernight":...},
  "overview": "...",
  "market_judgment": {"core_conflict", "today_tone", "support", "resistance", "volume", "conclusion"},
  "sentiment_judgment": {"cycle_tags", "current_state", "regulation", "today_variable", "inertia", "auction_observation", "risks", "iron_rule"},
  "limit_up_ladder": {"5":[{name,code,tags,note}], "4":..., "3":..., "2":..., "1": "count + first_board_rate + history_avg", "non_board":[...]},
  "theme_map": [{theme, strength, leaders[{name,code,status}], today_action}],
  "action_plan": {"offense", "defense", "tactics", "max_risk", "position_control"}
}
```

### 4. 中转站支持
用户最后说:LLM 大概率走中转站,需要可手工配置。已实现:
- `LLMProvider` 表存多个端点 (api_key/base_url/extra_headers/models_json)
- `is_default=True` 的为全局默认,Role 也可以按需指定 provider
- `MiniMaxClient` 自动带 `Authorization` + 任何自定义 header

### 5. SSO 支持
通用 OIDC:admin 在 `/admin/sso` 配多个企业 IdP (字段映射可配)。企业微信/飞书/钉钉本质都是 OAuth2,只是 userinfo 字段名不同,都走同一个 OIDC 客户端,只换字段映射。

## 注意事项
- 数据库要先 `CREATE DATABASE panbound;`(脚本不会自动建库)
- MySQL 驱动用 PyMySQL,URL 格式 `mysql+pymysql://root:root%40123@172.16.205.22:9301/panbound?charset=utf8mb4` (密码里的 @ 要 URL encode 成 %40)
- `app/__init__.py` 已经 `from .models import audit, report, sso, user` — 需要把 `role` 和 `llm.providers` 也加进去
- `app/models/report.py` 还需要补 `role_runs = relationship('RoleRun', back_populates='report', cascade='all, delete-orphan')`
