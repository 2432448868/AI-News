# Signal · AI 日报

少一点噪声，多一点新知。一个使用免费数据源、每日更新的 AI 资讯发现站，支持 GitHub Pages 静态部署和 Cloudflare 前后端部署。

**在线访问：https://2432448868.github.io/AI-News/**

代码仓库：https://github.com/2432448868/AI-News

2026-10-03 首次 Actions 部署通过，7/7 免费来源同步成功，首发线上快照 164 条。

## 功能
- AI 动态、开源项目、Agent Skills、模型动态、实用技巧、趣味应用和开发实践。
- 关键词搜索、分类/时间组合筛选、最新/热度排序、分批加载。
- 深浅主题、响应式布局、减少动效偏好、键盘导航、浏览器本地收藏。
- 来源状态、真实时间、过期快照提示、部分失败降级、原文可追溯。
- 原文标题与描述不强制翻译，不需要付费 LLM、搜索或翻译 API。

## 本地运行
要求 Node.js 24 与 npm。

~~~bash
npm ci
npm run dev
~~~

仓库自带真实采集快照，无需连通第三方源即可预览。

~~~bash
npm run collect         # 采集免费 API/RSS，刷新 public/data/feed.json
npm run check           # 格式检查 + 数据测试 + 类型检查 + 生产构建
npx playwright install chromium
npm run test:e2e         # 桌面/移动、无障碍与 Pages 子路径验收
npm run preview         # 预览 dist；先运行 npm run build
~~~

## 发布到 GitHub Pages
1. 创建 **公开仓库**，将本项目提交到默认分支 main 或 master。本仓库已在用户授权后完成首次提交与推送；以下供重新部署或 fork 使用。
2. 在仓库 Settings → Pages → Build and deployment 中选择 **GitHub Actions**。
3. 在 Actions 中允许工作流运行；进入 **Daily update & deploy**，手动 Run workflow。
4. 首次运行保持 use_snapshot 不勾选。成功后的 deploy environment 显示站点地址。
5. 不需要手动创建 secrets；工作流自动使用只读 GITHUB_TOKEN 获取 GitHub 公共信息。
6. 若默认分支不是 main/master，修改 deploy.yml 的 push 分支设置，并确认 Pages environment 允许该分支。

Vite 使用相对 base，兼容项目路径（例如 /AI-News/）与用户主页域名；无客户端路由深链接问题。
前端不会直接调用 GitHub/Hugging Face API，不会把 token 发给访客。

## 更新与免费边界
| 项目 | 约定 |
|---|---|
| 每日计划 | 北京时间 08:23 与 14:23，第二次用于增加成功机会 |
| 收费服务 | 无；无付费 API、LLM、代理、翻译、数据库或服务端 |
| 托管前提 | 公开仓库、GitHub 标准托管 runner、默认 Pages 域名 |
| 数据历史 | 近 30 天文章；最近项目榜单快照；不提供永久归档 |
| 单源故障 | 标记失败，保留该源上次快照；其他源正常更新 |
| 全源故障 | 工作流失败，不写新快照、不覆盖上次线上站点 |
| 快照过期 | 超过 36 小时在页面显式提醒 |
| 数据持久化 | Actions cache；无需工作流 commit/push；缓存失效回退仓库种子快照 |

GitHub 的免费调度不是强 SLA：任务可能延迟或丢弃；公开仓库连续 60 天没有活动时可能自动停用计划任务。
管理员应关注 Actions 失败通知、来源状态以及长时间未更新提示，并在停用后重新启用 workflow。
日调度依赖仓库默认分支上的工作流；fork 后通常需要自行启用 Actions。
政策和免费额度以 GitHub 官方说明为准；不要改成付费 runner 或额外付费服务。

## 数据来源
| 来源 | 免费方式 | 说明 |
|---|---|---|
| GitHub | Repository Search API | 近 30 天活跃 LLM 仓库，累计 stars 排序 |
| GitHub Demos | Repository Search API | 近 30 天活跃的 Gradio demo 项目，排除框架本体 |
| GitHub Skills | Repository Search API | agent-skills topic，非通用编程技能榜 |
| GitHub Demos | Repository Search API | 活跃 Gradio 应用项目，补充趣味案例 |
| Hugging Face Models | Hub 公共 API | 来源热门模型榜；创建/修改时间不等于正式发布日期 |
| Hugging Face Spaces | Hub 公共 API | 来源热门 AI demo；可用性取决于作者 |
| Hugging Face Blog | 官方 RSS | 新闻、教程、模型动态 |
| GitHub Blog | 官方 AI & ML RSS | AI 编码与实践 |

采集限制：每源至多 30 条，总量至多 500 条；响应体至多 2MB；15 秒超时与最多 3 次尝试。
响应限流时尊重短 Retry-After，长等待留到下次调度；不绕过验证码、登录、付费墙或限流。
“热度参考”是各来源排名的归一化，不是跨站真实热度或今日新增 stars。
只展示短摘要/仓库描述、署名与原文，不转载正文，不安装或执行任何远端项目/Skills。
外部项目是否收费、是否安全，需要读者在原站确认。

## 故障排查与回滚
- 某分类为空：打开“关于与来源”，查看对应源是否采集失败；不使用假新闻补位。
- HF 本机不通：初次开发环境已观察到直连超时；GitHub 来源正常。按来源隔离失败，交由 runner 实测网络。
- 采集限流：本机可选设置自有 GITHUB_TOKEN 环境变量，仅需要公共只读访问；绝不提交 token。
- 所有源失败：查看 Actions 日志；恢复网络后手动运行；原部署保持不变。
- 需要回退代码：由维护者恢复已知正常版本后运行工作流；不做自动 Git 写入。
- 急需发布已有快照：手动运行并勾选 use_snapshot；页面仍显示快照真实旧时间。
- 本地缓存：.cache/feed.json 可删除以回退仓库快照；不得删除 public/data/feed.json 后直接离线发布。

## 工程结构
~~~text
src/                    界面、主题与共享数据规则
backend/                Python Worker（API、采集、OAuth，Cloudflare 端）
migrations/             D1 数据库建表语句
scripts/                免费采集器与 D1 首灌脚本
public/data/feed.json   真实数据种子快照
.github/workflows/      定时更新/部署与 PR 验证
tests/                  数据边界、Python 后端与浏览器验收
docs/requirements/ai-news/ 需求、选型、评审、实现与验收记录
~~~

## 依据
- https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/rest/search/search#search-repositories
- https://huggingface.co/docs/hub/api

当前仓库已完成首次远程构建、浏览器验收与 Pages 发布；尚未观察到后续 schedule 触发，需持续关注 Actions 运行记录。

> 故障保留例外：失败来源沿用上次成功快照，文章可能超过 30 天；保留原始日期并标记来源失败，不伪装成新内容。

本机已安装 Chrome 时，可在 Git Bash 使用：
~~~bash
PLAYWRIGHT_EXECUTABLE_PATH='C:/Program Files/Google/Chrome/Application/chrome.exe' npm run test:e2e
~~~
测试脚本基于 Chromium 手机尺寸模拟，并非真实 iOS Safari 验证。

## Cloudflare 前后端部署

[完整实战教程（含实际截图）](docs/cloudflare/README.md)覆盖本地运行、设备授权、发布和日常维护。

2026-10-04 后端已重写为 Python Worker：采集（12 源）、文章数据与用户系统全部落在 Cloudflare D1，由 Worker Cron 每 2 小时滚动更新（每次 1 源，12 源每 24 小时各轮一次，适配免费版 CPU 限额）；手动触发走 `POST /api/sync`。
现有 GitHub Pages 工作流继续保留，作为免费静态镜像。

## 用户系统

新增 GitHub OAuth 登录、个人昵称、云端收藏和标签关注；Pages 保持本地模式，Cloudflare 端存 D1。
[用户系统说明与配置教程](docs/accounts/README.md)。2026-10-04 已配置 OAuth 密钥并完成真实 GitHub 登录验收，账号系统上线。
