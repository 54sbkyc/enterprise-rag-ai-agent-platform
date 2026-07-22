# pgvector 检索后端

项目默认继续使用 SQLite 保存业务数据和向量 JSON，因此克隆仓库后不需要额外服务就能运行。需要更大语料规模时，可以启用 pgvector 检索后端，把向量 Top-K 计算交给 PostgreSQL 的 HNSW 索引，同时保留现有 BM25、权限、审计和本地降级能力。

这不是“把 SQLite 改名为 PostgreSQL”。当前迁移范围只包含向量检索通道；用户、文档元数据、片段正文、问答日志、Agent 状态和评测结果仍以 SQLite 为准。

## 1. 工作方式

1. 文档入库或重建 Embedding 后，应用先完成 SQLite 事务，再把 `chunk_id`、`document_id`、模型、内容哈希和向量幂等写入 pgvector。
2. 查询时先从 SQLite 读取当前角色可访问且状态为 `ready` 的片段，再把这些实时 `chunk_id` 作为 pgvector 候选白名单。
3. pgvector 使用余弦距离 HNSW 索引返回候选，应用再与字段加权 BM25、本地重排分数融合。
4. pgvector 不可用时，默认回退到 SQLite JSON 向量；搜索解释、引用和 Agent 输出会标记 `vector_backend`、`vector_degraded`，不会伪装成正常 pgvector 检索。

权限过滤始终以 SQLite 当前状态为准。即使文档刚修改密级、外部索引暂时未同步或存在孤儿向量，旧向量也不在允许的 `chunk_id` 集合中，不能被低权限用户召回。

## 2. 配置并启动

先创建本地配置：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中至少设置：

```dotenv
RAG_BOOTSTRAP_ADMIN_PASSWORD=<your-strong-bootstrap-password>
PGVECTOR_PASSWORD=<your-random-postgres-password>
PGVECTOR_DIMENSIONS=1536
EMBEDDING_MODEL=<your-embedding-model>
EMBEDDING_API_KEY=<your-provider-key>
```

`PGVECTOR_DIMENSIONS` 必须与 Embedding 模型输出维度一致。当前 HNSW `vector` 索引限制为最多 2000 维，应用会在写入前校验并返回不含 DSN 的错误码。

使用 Compose 叠加配置启动：

```powershell
docker compose -f compose.yaml -f compose.pgvector.yaml config
docker compose -f compose.yaml -f compose.pgvector.yaml up --build -d
Invoke-RestMethod http://127.0.0.1:8000/api/health/ready
```

就绪响应中的 `vector_store` 应为：

```json
{"backend":"pgvector","status":"ready","count":0}
```

应用使用有界 Psycopg 连接池。可通过 `PGVECTOR_POOL_MIN_SIZE` 和 `PGVECTOR_POOL_MAX_SIZE` 调整，默认分别为 `1` 和 `5`。

## 3. 对账历史向量

已有 SQLite Embedding 不需要重新调用模型。管理员登录后可以调用对账接口，按当前 SQLite 数据删除并重建对应 pgvector 行：

```powershell
$login = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/auth/login `
  -ContentType application/json `
  -Body (@{username='admin'; password='<your-admin-password>'} | ConvertTo-Json)

$headers = @{Authorization="Bearer $($login.token)"}
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/documents/vector-store/sync `
  -Headers $headers `
  -ContentType application/json `
  -Body '{}'
```

也可以传入 `{"document_ids":[1,2]}` 只对账指定文档。响应会分别给出文档数、成功/失败数、写入片段数、无向量片段数以及每个文档的清理和同步结果。

## 4. 故障与一致性

- `RAG_VECTOR_STORE_FALLBACK=true`：pgvector 故障时继续使用 SQLite JSON 向量，服务保持就绪，但检索结果标记降级。
- `RAG_VECTOR_STORE_FALLBACK=false`：就绪检查在 pgvector 不可用时返回 `503`，适合要求外部向量后端必须在线的部署。
- SQLite 与 pgvector 无法共享事务。应用采用“SQLite 为事实源、外部索引可重建”的策略，避免把跨库双写伪装成强一致事务。
- 重索引和删除会主动清理外部向量；即使清理失败，实时允许 ID 过滤仍阻止孤儿向量参与检索。恢复后运行对账接口即可收敛。
- 修改向量维度需要使用新的 pgvector 数据卷或执行受控迁移，应用不会静默重建不兼容的表。

## 5. CI 证据与边界

GitHub Actions 的 `pgvector-integration` Job 会启动官方 pgvector PostgreSQL 镜像，真实执行扩展初始化、HNSW 建索引、批量 upsert、余弦查询、候选权限过滤、更新和删除测试。

当前仍保留两项诚实边界：BM25 会读取当前可访问片段进行本地计算；业务数据库仍是单实例 SQLite。下一阶段若要支持大规模多实例，应继续迁移业务表、全文检索和任务队列，而不是把“接入 pgvector”描述为完整 PostgreSQL 改造。
