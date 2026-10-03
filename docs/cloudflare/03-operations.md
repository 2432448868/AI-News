# 03 · 每日更新、验收与维护

[返回目录](README.md)

## 1. 信息什么时候更新

| 阶段 | UTC | 北京时间 | 职责 |
|---|---|---|---|
| 现有 GitHub Actions | 每天 00:23、06:23 | 每天 08:23、14:23 | 采集免费来源、完整校验、发布 Pages |
| Cloudflare Cron | 00:15、06:15、12:15、18:15 | 08:15、14:15、20:15、次日 02:15 | 检查 Pages 快照并同步到 KV |

同步不是实时推送，两个定时器错开，更新最多通常等待下一轮同步；上游或调度异常会更久。
GitHub 定时任务可能延迟，公开仓库长期无活动也可能停用定时工作流，需定期看 Actions。
Cloudflare 不调用收费 LLM，不购买新闻接口，不抓取付费正文。

## 2. 后端接口

| 接口 | 用途 |
|---|---|
| GET /api/feed | 前端完整快照 |
| GET /api/items | 搜索、分类、标签、国内筛选、分页 |
| GET /api/sources | 来源状态 |
| GET /api/health | 快照时间、数量、同步状态 |

~~~bash
curl 'http://127.0.0.1:8787/api/items?chinaOnly=true&sort=latest&page=1&limit=12'
curl 'http://127.0.0.1:8787/api/items?q=ChatGPT&days=7'
curl 'http://127.0.0.1:8787/api/sources'
~~~

公网验收时把本地地址换成 Worker 域名。API 仅支持 GET/HEAD，不提供公开写入或管理入口。
limit 为 1–100，page 为 1–500，days 为 0–365；0 表示不限制日期。
参数错误返回 400，未初始化快照返回 503，未知 API 返回 404，不支持的方法返回 405。
快照超过 48 小时，health.status 为 stale；HTTP 200 不等于信息足够新。
首次 seed 后 sync 可能为 null，等第一次 Cron 写入同步状态后才有值。

## 3. 故障排查

| 现象 | 检查与处理 |
|---|---|
| 域名连接超时 | 先区分网络连通性和应用错误；换可访问网络检查，不重复创建 Worker |
| /api/feed 为 503 | 查 NEWS 绑定和 feed:latest 是否存在；首次部署才执行 seed |
| 页面无数据但接口正常 | 查是否 build:cloudflare，及前端控制台校验错误 |
| 日期长期不更新 | 依次看 GitHub Actions、Pages feed.json、Cron、health.sync |
| 部分来源失败 | 保留可用来源与旧快照；查看来源状态，不伪造新闻 |
| 同步失败 | Worker 保留旧快照，sync:status 记录错误；检查上游、大小与格式 |
| 授权过期 | 重新执行设备授权；不要复制旧 OAuth callback |

可在控制台 Observability 看日志，或本机执行 npm exec wrangler -- tail。
新增来源仍修改采集配置并走 GitHub Actions，不需要在 Worker 内重复写爬虫。

## 4. 免费额度边界

本次按免费方案设计；限额会变化，且与账号内其他项目共享，不能承诺无限流量或永久免费。
核对时官方文档显示 Workers 免费计划每日 100,000 请求、10ms CPU；KV 每日 100,000 读取、1,000 写入、1GB 存储。
每 6 小时同步一次通常每天最多 8 次 KV 写入（快照与状态各一次），API 流量另计。
健康接口读取两次 KV；分页与筛选仍会读取并解析完整快照，未完成生产压测。
Worker 启动耗时不等于请求 CPU 耗时，实际流量上线后应检查用量及超限错误。
本次没有购买套餐；超出免费容量时优先限制请求或保留静态 Pages 访问，不自动升级付费。

官方参考：
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/kv/platform/limits/
- https://developers.cloudflare.com/workers/static-assets/routing/worker-script/

## 5. 日后发版

~~~bash
npm ci
npm run check
npm run build:cloudflare
npm exec wrangler -- deploy --dry-run
npm run deploy:cloudflare
~~~

构建通过再发布。发布后看 deployments list、真实域名页面和 /api/health。
Cloudflare 发布不等于 Git 提交；本轮尚未 commit/push，需用户确认后执行。
GitHub Actions 仍只自动发布 Pages，当前没有配置 Cloudflare 的 Git 自动部署。
需要回退时在 Cloudflare 部署历史选择已知正常版本，并重新验收；代码回退不会自动恢复 KV 数据。

## 6. 本次验收记录

| 检查 | 状态 |
|---|---|
| Prettier、36 个 Node 测试、TypeScript、Vite | 通过 |
| 36 个串行浏览器用例（原 Pages 模式） | 通过 |
| Cloudflare 构建及 deploy dry-run | 通过 |
| 本地 workerd Cron 与 API | 通过，208 条，12/12 来源 |
| 本地 Cloudflare 页面及深浅主题 | 通过 |
| 远程 KV 初始化、Worker 版本、绑定、Cron 配置 | 控制台确认 |
| 公网前端与 API 响应 | 未通过：当前网络 workers.dev 连接超时 |
| 云端 Cron 首次自然运行 | 待观察 |
| 真实流量下 CPU、配额、长期稳定性 | 待验证 |

本次关键运行时修复：Workers 不支持 fetch 的 redirect:error，改用 manual，并拒绝非成功状态。
这也说明 Node 单测不能替代真实 Worker 运行时验收。
