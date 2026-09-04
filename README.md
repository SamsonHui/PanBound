Flask + MySQL + Redis 的 A 股每日复盘/交易预案平台,后端 LLM 走 MiniMax-M3 (OpenAI 兼容端点),支持本地账号 + 图形验证码 + 通用 OIDC SSO。

## 快速开始

```bash
# 1. 安装依赖(建议 Python 3.11)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env,填入 MINIMAX_API_KEY

# 3. 初始化数据库 + 默认管理员
flask --app run.py init-db
flask --app run.py create-admin

# 4. 启动
python run.py
# 打开 http://127.0.0.1:5000,使用 admin/admin 登录
```

## 配置 SSO (企业微信 / 飞书 / 自建 OIDC 等)

进入 `/admin/sso`,新增一个 Provider:

- `name`: 内部识别名 (例:`feishu`)
- `display_name`: 登录页显示 (例:`飞书`)
- `provider_type`: `oidc` / `oauth2`
- `client_id` / `client_secret`: 应用凭证
- `authorize_url` / `token_url` / `userinfo_url`: 对应端点
- `scope`: 常用 `openid profile email`
- `username_field`: 从 userinfo 取哪个字段做本地用户名 (默认 `preferred_username` / `email`)
- `email_field` / `display_name_field`: 同上
- `auto_create_user`: 首次登录是否自动创建账号

填好后登录页会出现 `[飞书]` 按钮,点击走标准 OIDC 流程。

## 复盘报告生成

进入 `复盘预案 -> 新建报告`:

1. 选择交易日
2. 粘贴当日盘面笔记 (指数/成交/涨停家数/题材/连板/竞价观察 等自由文本)
3. 点击生成,后端把笔记 + 6 大模块的 JSON Schema 一起发给 MiniMax-M3
4. 解析后存库,详情页用与截图一致的金融风样式渲染

## 目录结构

```
PanBound/
|-- app/
|   |-- auth/        # 登录 / 退出 / 图形验证码
|   |-- sso/         # 通用 OIDC 连接器
|   |-- reports/     # 复盘报告 + 提示词
|   |-- llm/         # MiniMax-M3 OpenAI 兼容客户端
|   |-- admin/       # 后台:SSO / 用户管理
|   |-- models/      # SQLAlchemy 模型
|   |-- templates/   # Jinja 模板
|   \-- static/      # CSS / JS
|-- cli.py           # 命令行:init-db / create-admin / list-sso
|-- run.py           # 启动入口
\-- config.py        # 12-factor 配置
```
