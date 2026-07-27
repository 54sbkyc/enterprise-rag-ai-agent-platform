# 数据库迁移运维指南

本项目使用 SQLite 保存业务事实。`v1.7.0` 起，表结构不再由启动时零散执行 `ALTER TABLE` 维护，而是由有序、不可变的版本化迁移管理。

## 运行机制

- `backend/app/migrations/` 保存按版本排序的 SQL 基线，已发布文件不得修改。
- `schema_migrations` 记录版本、名称、SHA-256 校验值、应用时间和耗时。
- 每个待执行版本使用独立事务；任何 SQL、外键检查或历史写入失败都会回滚该版本。
- `BEGIN IMMEDIATE` 串行化同一 SQLite 文件上的并发启动，避免两个实例重复执行迁移。
- 已应用名称或校验值变化会判定为 `drift_detected`；数据库包含应用不认识的未来版本会判定为 `unsupported`。
- 服务启动自动执行待应用迁移，`/api/health/ready` 只有在当前版本等于期望版本且历史校验通过时才返回就绪。

## 运维命令

在项目根目录执行：

```powershell
cd backend
python -m app.migration_cli status
python -m app.migration_cli backup
python -m app.migration_cli upgrade
```

`status` 是只读检查，返回当前版本、期望版本、待执行版本和完整迁移历史。`backup` 使用 SQLite Online Backup API 创建一致性副本并执行 `PRAGMA integrity_check`；也可以指定目标路径：

```powershell
python -m app.migration_cli backup --output ..\backups\before-v1.7.0.db
```

备份命令不会覆盖已有文件。生产容器还应在宿主机或存储平台对命名卷做快照，不能只依赖容器可写层。

## 推荐升级流程

1. 停止写入流量或进入维护窗口。
2. 执行 `status`，确认没有 `drift_detected` 或 `unsupported`。
3. 执行 `backup`，保存输出路径并确认 `integrity_check` 为 `ok`。
4. 执行 `upgrade`，再次执行 `status`。
5. 启动服务，检查 `/api/health/ready`，再执行登录、问答和文档读取烟测。

## 故障恢复

迁移失败时，当前版本的 DDL、数据写入和历史记录会一起回滚。先保留失败日志和原数据库，不要手工修改 `schema_migrations`，修复代码后重新执行 `upgrade`。

本项目不提供自动 `downgrade`。SQLite 的删列、表重建和数据转换难以保证通用可逆，自动降级容易制造静默数据损坏。需要回退应用版本时，应停止服务并恢复升级前通过完整性检查的数据库副本。

## 新增迁移规则

1. 新增下一个连续版本文件，不修改已发布迁移。
2. DDL 使用幂等或明确前置条件，数据转换必须有回归样例。
3. 为新版本补充全新库、上一版本升级、失败回滚和重复执行测试。
4. 更新 `LATEST_SCHEMA_VERSION`、运维文档和发布说明。
5. 先备份真实旧库副本，再在副本上执行升级验证。

## 当前边界

迁移器只管理本项目的 SQLite 业务库，不管理可重建的 pgvector 投影，也不等同于 PostgreSQL 的 Alembic 迁移方案。迁移业务事实源到 PostgreSQL 时，应引入适配 SQLAlchemy/Alembic 的独立迁移链、权限账号、备份恢复演练和多实例部署锁。
