# Better Auth + Resend 注册验证迁移

## 当前状态与边界

基于 main `58e3626` 的隔离工作区实现。采用真正的 Better Auth 1.7.14 Node 服务和 emailOTP 插件，不是给原 Python 验证器改名。

默认 `AUTH_ENGINE=legacy`；没有更改生产环境、导入生产账号或发送真实邮件。Resend 和 Turnstile 尚未开通。不能把本地测试收件箱的通过称为真实邮件投递通过。

## 用户需要准备

1. 登录 https://resend.com/domains，添加 `auth.yuzoudiyigongzuotai.cn`。按 Resend 此时显示的记录在域名 DNS 控制台添加 SPF/DKIM 等记录，等待 Verified。不要复制阿里云邮件推送的 DNS 值，也不要删除网站解析或其他邮件服务记录。
2. 在 https://resend.com/api-keys 建立仅能向该发信域名发送邮件的 API Key。发件人可用 `宇宙第一工作台 <noreply@auth.yuzoudiyigongzuotai.cn>`。
3. 登录 https://dash.cloudflare.com/ 的 Turnstile，创建站点，允许 `yuzoudiyigongzuotai.cn`，取得 Site Key 和 Secret Key。不要求把域名 DNS 迁移到 Cloudflare。
4. 私密写入服务器配置：`RESEND_API_KEY`、`RESEND_FROM`、`TURNSTILE_SITE_KEY`、`TURNSTILE_SECRET_KEY`。不要贴进 Git、网页源码、截图或公开日志。
5. 服务间随机密钥 `AUTH_BRIDGE_SECRET` 和 Better Auth 签名密钥 `BETTER_AUTH_SECRET` 各自独立、至少 32 字符；只在服务端生成并保存在受保护的环境文件，不回显。

## 数据流

发码：原注册弹窗 → Turnstile `register_email` → FastAPI IP 限流 → 内部共享密钥 RPC → Redis 邮箱锁/60 秒冷却/一次性邮箱名单 → Better Auth 生成并哈希存储 6 位 OTP → 等待 Resend HTTP API 接受发送 → UI 提示已发送。

邮件包含 30 分钟 OTP 和备用链接。备用链接包含随机凭证，Redis 只保存 AES-GCM 加密的邮件/OTP，浏览器 URL fragment 不进入 HTTP 访问日志；它与 OTP 绑定相同的 Better Auth 验证记录。打开链接只填入邮箱，必须设置密码并提交注册，不能直接创建账号。

注册：Turnstile 新 token（action=`register`）→ Better Auth `emailOTP` 消费 OTP（最多 5 次错误）→ 建立已验证身份并设置密码 → FastAPI 使用该身份 ID 创建业务用户、钱包、赠送积分，均在原业务事务中 → 返回 Better Auth HttpOnly session cookie。

登录：原表单 → Better Auth 密码验证 → FastAPI 按固定 user ID 查业务账号状态 → 原积分与文章接口。后续 API 验证 Better Auth session，不根据浏览器提交的角色或 ID 授权。

退出：撤销 Better Auth session，并清除过渡期原 session。旧账号未验证的邮箱不会被迁移脚本虚标成已验证；旧账号可继续用原密码登录。

## 数据与回滚保护

- Better Auth 新增 `auth_user`、`auth_account`、`auth_session`、`auth_verification`；不改业务主键，不重新建立旧用户钱包，不重新赠送积分。
- 导入保留 PBKDF2 旧哈希；新密码使用 Better Auth 默认 scrypt。旧服务注册与首次导入之间的小窗口由登录时的按邮箱补导入覆盖。
- 同邮箱不同 ID 的冲突会停止导入/拒绝关联，不能静默合并钱包。
- 迁移期间可接受已有原 session（`AUTH_ACCEPT_LEGACY_SESSIONS=1`），待原会话过期后关闭。旧的管理员代操作会话仅在 actor 与当前 Better Auth 管理员一致时使用。
- 新用户业务表暂留独立 PBKDF2 回滚凭证；启用 Better Auth 时的新登录不调用它、不再创建原登录 session。后续若增加改密功能，必须同步设计回滚凭证更新，不能直接承诺无限期回滚。
- 运行中的验证码不应跨引擎切换；切换时提示用户重新获取验证码。

## 发布步骤（准备完成后）

1. 数据库备份、核对所有旧邮箱大小写和 ID；先在独立 PostgreSQL/Redis 验证导入，包含重复导入、密码、钱包对照。当前这一步尚未执行。
2. 配置 `.env.example` 所列变量，先保持 `AUTH_ENGINE=legacy`。Resend 域名必须 Verified，且用指定测试收件人实测送达；API 返回成功只能证明服务商接受，不证明进收件箱。
3. 安装本次提交的 `scripts/deploy_server.sh` 到标准部署入口（保持原部署锁与路径）。服务端配置 `AUTH_ENGINE=better-auth`、`TURNSTILE_ENABLED=1` 后使用标准部署脚本发布该提交。
4. 脚本自动加载 `docker-compose.auth.yml`、构建 auth、执行独立表迁移和导入，先启动 auth 并确认就绪，再切 web。auth 没有公网端口，不暴露 Better Auth 的原生任意注册/重置接口。
5. 验收真实 QQ/163 等目标收件箱、错误验证码/过期/重复使用/并发注册、旧用户登录、同一积分余额与历史文章、停用账号、管理员代操作和退出。核对注册赠送账本仅一笔。
6. 当前服务器资源有限：上线前核对内存和磁盘；Node sidecar 增加了常驻内存。未做生产性能实测，不能声称没有开销。

## 回滚

先将 `AUTH_ENGINE` 改回 `legacy`，再用标准部署入口 `--rollback <切换前提交>`；保留新增 auth 表、业务用户与钱包，不删除任何数据。原 session 如仍有效可继续使用，Better Auth session 用户需要重新登录。保留 auth 服务供必要的人工核查，停止它之前先确认没有进行中的认证操作。

## 已执行验证

- 最新专项回归：Node 7 项、Python/浏览器 18 项通过；npm 官方源依赖审计为 0 个已知漏洞；部署脚本通过 `bash -n`。这些不代表真实邮件已送达。
- Node 本地实际运行 Better Auth（SQLite），Resend 为内存收件箱、Turnstile 为响应替身：验证 OTP/备用链接、哈希、次数、过期、旧密码、并发与发信失败传播。
- Python 本地实际启动 Node 私有服务，经过 FastAPI HTTP 注册和业务数据库：验证无验证码不开户、不建钱包；成功只发一次 6 积分；重复注册、登录、退出、账号停用及身份冲突。
- 浏览器使用模拟 Turnstile：发码/注册分别提交不同 action token，备用链接不自动开户，原登录界面与布局回归。
- 扩大回归发现现有 SQLite 退款唯一索引导致 `test_image_task_dispatch_and_idempotent_reservation` 失败；已在完全未修改的 `58e3626` 工作区复现相同失败。未在本次认证迁移中修改积分退款索引，不把全部回归称为通过。
- 未完成：真实 Resend 发信/收信、真实 Turnstile、PostgreSQL 导入/容器发布、生产资源和延迟验证。

## 官方参考

- https://better-auth.com/docs/plugins/email-otp
- https://better-auth.com/docs/adapters/postgresql
- https://better-auth.com/docs/authentication/email-password
- https://resend.com/docs/api-reference/emails/send-email
- https://resend.com/docs/dashboard/domains/introduction
- https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
