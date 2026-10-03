# GitHub 用户系统配置教程

> 账号代码已实现；以下是真实 OAuth 启用步骤，不是已经完成的线上操作记录。基础部署截图见 ../cloudflare/README.md。

## 1. 创建 GitHub OAuth App

在 GitHub → Settings → Developer settings → OAuth Apps → New OAuth App 创建应用。

| 字段 | 生产环境值 |
|---|---|
| Application name | Signal AI News |
| Homepage URL | https://signal-ai-news.stock-backend-wkl.workers.dev |
| Authorization callback URL | https://signal-ai-news.stock-backend-wkl.workers.dev/api/auth/callback |

记录 Client ID，生成 Client Secret。不要粘贴到聊天、仓库、截图或前端环境变量中。

## 2. 写入 Cloudflare Secrets

在项目目录执行，按交互提示输入对应值：

~~~bash
npm exec wrangler -- secret put GITHUB_CLIENT_ID
npm exec wrangler -- secret put GITHUB_CLIENT_SECRET
npm exec wrangler -- secret put SESSION_SECRET
~~~

SESSION_SECRET 使用密码管理器生成至少 32 字符的高熵随机值；不要使用示例密码。
wrangler.json 的 APP_ORIGIN 必须与实际访问域名完全一致；换域名时同时更新 OAuth callback。

## 3. 发布前后端

~~~bash
npm ci
npm run check
npm run test:runtime
npm run deploy:cloudflare
~~~

部署配置会创建 USERS SQLite-backed Durable Object 绑定；代码通过存储 API 读写，无需手工执行 SQL。
本项目不会自动购买服务；遇到升级付费提示先停止并检查计划。
GitHub push 只触发现有 Pages 工作流，不会自动部署 Cloudflare。

## 4. 本地开发

为本地单独创建 OAuth App，Homepage 为 http://127.0.0.1:8787，回调为 http://127.0.0.1:8787/api/auth/callback。
在仓库根目录新建已被 Git 忽略的 .dev.vars，填入自己的值：

~~~dotenv
APP_ORIGIN=http://127.0.0.1:8787
GITHUB_CLIENT_ID=填写本地应用的ID
GITHUB_CLIENT_SECRET=填写本地应用的密钥
SESSION_SECRET=填写至少32字符的随机密钥
~~~

~~~bash
npm run dev:cloudflare
~~~

以 package.json 中的脚本为准；本地存储与云端相互隔离，缺少 NEWS 快照时按基础教程初始化。
不要把 localhost 与 127.0.0.1 混用，否则 Origin 和 Cookie 不匹配。
未配置密钥时账号面板会明确显示未启用，资讯和访客收藏仍可使用。

## 5. 真实上线验收

- GitHub 登录成功返回本站；不索取邮箱/仓库权限。
- 修改昵称、收藏文章、关注标签后刷新仍存在。
- 另一台设备登录相同账号可读取数据；不同账号的数据相互隔离。
- 退出后旧会话不能写入；访客本地收藏恢复。
- 检查失败登录、密钥未配置和网络失败提示。
- 检查生产日志不记录 OAuth code、state 或令牌；配置已启用查询参数脱敏。
- 检查免费额度、自然定时更新以及公网连通性。

## 故障定位

| 现象 | 检查 |
|---|---|
| 未启用 | 三个 Secrets、USERS 绑定、APP_ORIGIN |
| 回调失败 | Client Secret、回调地址、GitHub 网络、Cookie 是否启用 |
| 写入 403 | Origin、CSRF、是否使用了其他域名打开 |
| 写入 401 | 会话过期或已退出，重新登录 |
| 429 | 等待一分钟；不要自动无限重试 |
| workers.dev 超时 | 网络可达性；不能当作登录成功或部署失败的唯一证据 |
