# AI News 产品自验收

## 结论
2026-10-03（北京时间）：本地验收通过；尚未发布 GitHub Pages，不将远程部署列为通过。
产品：Signal · AI 日报；免费公共数据 + 静态网页 + Actions 定时更新。

## 执行结果
| 项目 | 结果 | 证据 |
|---|---|---|
| 锁文件安装 | npm ci 成功 | 本机实际执行 |
| 依赖审计 | npm audit 0 已知漏洞 | artifacts/audit.txt |
| 格式/类型/构建 | npm run check 通过 | artifacts/check-final.log |
| 数据测试 | 27/27 通过 | 同上 |
| 浏览器交互 | 30/30 通过 | artifacts/e2e-final.log |
| 深浅无障碍 | axe WCAG A/AA 自动检查零违规 | 两个浏览器项目各测两主题 |
| 手机适配 | 360/390/768/1440px 无横向溢出 | 浏览器测试 |
| Pages 子路径 | /AI-News/ 可访问，资源无 404 | 严格静态测试服务器 |
| 真实采集 | 89 条、4/7 来源成功 | public/data/feed.json |
| 视觉检查 | 桌面两主题、手机浅色通过 | artifacts 下三张 PNG |

## 真实来源状态
| 来源 | 状态 | 归属记录数（跨源去重后） |
|---|---|---|
| GitHub 项目 | 成功 | 29 |
| GitHub Skills | 成功 | 30 |
| GitHub Demos | 成功 | 20 |
| GitHub Blog | 成功 | 10 |
| HF Models / Spaces / Blog | 本机网络超时 | 0 |

记录可能同时属于多个分类。全部七类均有内容，但模型目前只有相关官方博客动态，不能视为 HF 模型采集通过。
界面显示 4/7 成功与 3 源失败；未使用付费代理绕过网络问题。

## 交互覆盖
搜索/分类/时间组合、清除筛选、热度说明、分页、收藏增删与持久化、主题持久化、
来源弹窗、键盘快捷键、加载失败重试、过期提示、部分故障、空数据、存储损坏、
恶意 HTML 与不安全 URL、减少动效、移动布局、外链安全属性、无运行时异常。

## 视觉记录
- artifacts/desktop-light.png：真实数据，1440px 浅色。
- artifacts/desktop-dark.png：真实数据，1440px 深色。
- artifacts/mobile-light.png：真实数据，390px 浅色。
- 微型装饰文字不承载核心功能；主要标题、卡片和筛选在手机保持可操作。

## 待上线验证
1. 用户创建公开仓库并自行提交/推送；当前目录尚不是 Git 仓库。
2. Settings → Pages 选择 GitHub Actions，启用工作流。
3. 手动运行 Daily update & deploy，验证真实域名、Actions 权限与 HF 连接。
4. 观察下一次计划任务：北京时间 08:23 / 14:23，确认快照日期推进。
5. 全源故障时应保持已有部署；关注过期状态与失败通知。

## 复现
~~~bash
npm ci
npm run check
npx playwright install chromium
npm run test:e2e
~~~
本机改用已安装 Chrome 的方法见 README；CI 使用 Playwright Chromium。
浏览器测试为 Chromium 桌面/手机模拟，未覆盖真实 Safari/Firefox。
