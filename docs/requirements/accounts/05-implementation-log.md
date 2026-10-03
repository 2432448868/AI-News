# 实现日志：用户系统

## 元数据
- 日期：2026-10-03
- 负责人：用户 2432448868
- 范围：GitHub OAuth、个人资料、云端收藏、标签关注；用户授权完成后提交推送。

## 任务清单

| 任务 | 状态 | 文件 | 验证 | 未验证项 |
|---|---|---|---|---|
| OAuth 与会话 | 完成 | worker/auth.mjs | 模拟 GitHub 单元测试和 workerd 集成通过 | 真实 OAuth App |
| 用户持久化 | 完成 | worker/accounts.mjs | SQLite-backed DO 并发、隔离、退出通过 | 云端账号部署 |
| 账号界面 | 完成 | src/account.ts、account.css、main.ts、shell.html | 12 个桌面/移动账号用例通过 | 真实多设备 |
| CI 与部署配置 | 完成 | verify.yml、wrangler.json | 类型构建、dry-run 通过 | 远程流水线结果 |
| 教程 | 完成 | docs/accounts/ | 配置、边界和验收步骤齐全 | 用户填入 Secrets |

## 验证结果

- npm run check：格式通过，45 个 Node 测试通过，TypeScript 和 Pages 构建通过。
- npm run test:e2e：36 个现有 Pages 浏览器用例通过。
- npm run test:accounts：12 个账号浏览器用例通过；API 使用模拟响应。
- npm run test:runtime：真实 workerd + SQLite DO，模拟 GitHub 回调、并发收藏、退出撤销通过。
- wrangler deploy --dry-run：Worker 打包与 USERS 绑定通过，没有发布账号新版。
- 修复账号统计文字对比度不足；测试中的重名标签定位改为账号面板内定位。

## 代码自审

| 检查 | 结论 |
|---|---|
| 身份隔离 | 用户 ID 来自 GitHub 验证结果和随机会话，不接受客户端指定目标用户 |
| CSRF 与重定向 | 固定 Origin、CSRF 校验、签名 state、PKCE、固定回调地址 |
| 密钥处理 | 不入前端，不存 GitHub token，会话只存摘要，生产查询参数脱敏 |
| 并发与容量 | 每用户事务存储、收藏/标签/会话上限、写入频控 |
| 静态兼容 | Pages 不调用账号接口，保留本地收藏 |
| 失败反馈 | 请求失败不伪更新收藏；缺配置明确提示未启用 |

## 风险与下一步

- 真实 OAuth 密钥缺失；新账号版本未发布到 Cloudflare，不能宣称线上登录成功。
- workers.dev 公网访问此前超时；基础版本发布成功不等于公网验收成功。
- 收藏保存 ID 而非文章全文；旧文章离开快照后不会显示。
- 免费额度账号共享；不自动开通付费。未实现自助注销、数据导出和完整抗攻击保护。
- 配置 Secrets、发布新版、真实双账号/多设备验收后才能关闭上线待办。
