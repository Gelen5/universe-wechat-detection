# 爆款成品库定向审计（2026-11-07）

基线：`5fb514918cb1a5af8fd6f2f82f748e8833596d23`（本地 fetch 后的 `origin/main`）。本记录为代码审计，不代表生产配置或生产数据已核实。

## 数据源

`server/models.py` 的 `LowfansArticle` 保存来源 ID、链接、标题、观测日期、阅读量、账号基线和爆发倍数；唯一约束为 `(stat_date, range_type, art_id)`，同一文章在不同日期仍有多行。`server/lowfans_sync.py` 写入本地快照，页面不直接调用付费上游。商品应复制所选观测的证据快照，按文章 ID 辨别重复，同时保留原始观测日期；链接存在不等于已验证页面和数据当前仍可访问。

## 积分和权限

`server/accounts.py` 的 `reserve_points` 在独立连接内锁钱包、预扣、写账本和 usage 后直接提交，并随机创建 request ID。它不能与新商品授权天然组成单一事务；不能直接先调用它再写授权，也不能仅靠进程锁保障跨 worker 幂等。`server/main.py` 的计费中间件还会依据 pricing rule 预扣，新解锁路径必须避免重复计费。建议在同一个数据库事务内锁钱包、检查用户与商品唯一授权、写钱包及账本和授权，失败整体回滚；并发和 PostgreSQL 行锁需实测。

`server/accounts.py` 的 `require_user`、`require_admin` 可复用。商品详情必须在服务端按授权返回正文；`server/main.py` 将 `/static` 作为公开静态目录，不能放置付费原文或原图。

## 生成和调度

`server/wechat_plus_service.py` 有 `generate_json` 和既有创作编排；`server/wechat_plus_tasks.py` 使用 Celery、租约及心跳处理长任务。需进一步确认直接复用时的输入、结果、取消、重试及成本归属，不能将普通用户计费链路误用于平台生产。第一版默认不配置自动批量生成。

## 迁移和部署

`docker-compose.yml` 定义 Alembic migrate 服务；但 `server/lowfans_sync.py` 和 `server/viral_insights_membership.py` 记录了既有生产部署跳过该服务、模块启动 `create_all` 建表的情况。具体当前线上部署脚本及版本尚未核实。新增表需同时考虑版本化迁移和实际部署路径，避免假设上线时迁移自动执行；不能随意运行旧迁移或修改生产表。

## 待完成验证

- 最新生产代码、配置、真实样本和上游数据可核验性。
- PostgreSQL 下并发购买、锁顺序、失败回滚及现有账本兼容。
- 生成任务的恢复与成本记录，已购版本不可变和下架后交付。
- 新增迁移在空库及现有生产架构上的兼容性，备份与回滚。
