# Docker 安全部署

这套容器交付用于单机演示、小规模内部试用和可复现验收。它解决环境一致性、弱默认口令、数据持久化、运行用户和健康检查问题，但仍保持单实例 SQLite 与进程内 Agent，不将项目描述为多实例生产平台。

## 1. 准备配置

需要 Docker Desktop 或 Docker Engine + Compose。先从模板创建本地配置：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中至少设置一个长度不小于 12 位的首次管理员密码：

```dotenv
RAG_BOOTSTRAP_ADMIN_USERNAME=admin
RAG_BOOTSTRAP_ADMIN_PASSWORD=<your-strong-bootstrap-password>
```

`.env` 已被 Git 忽略，不能提交。生产模式只在数据库中没有管理员时使用这组配置创建账号；容器重启或修改环境变量不会覆盖已有管理员密码。后续密码轮换应在用户管理界面完成。

## 2. 校验并启动

```powershell
docker compose config
docker compose up --build -d
docker compose ps
```

默认只监听本机 `127.0.0.1:8000`。需要更换端口时，在 `.env` 中设置 `RAG_HTTP_PORT`。启动完成后检查数据库就绪状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/ready
```

返回 `status: ready` 和 `database: ok` 后，访问 `http://127.0.0.1:8000`，使用 `.env` 中配置的管理员账号登录。生产模式不会创建 `employee / user123` 演示账号，普通用户应由管理员创建。

默认 Compose 继续使用 SQLite JSON 向量。需要 PostgreSQL + pgvector HNSW 检索时，使用 `compose.pgvector.yaml` 叠加启动，详见 [pgvector 检索后端](pgvector_retrieval.md)。

## 3. 运行与排障

```powershell
docker compose logs --follow --tail 100 app
docker compose restart app
docker compose ps
```

容器使用固定单 Worker，原因是当前 Agent 任务执行器位于进程内；直接扩容 Worker 或副本会破坏任务所有权和恢复语义。镜像以 UID `10001` 的非 root 用户运行，Compose 同时启用只读根文件系统、能力裁剪、`no-new-privileges` 和独立 `/tmp`。

## 4. 数据持久化与备份

SQLite 数据库和上传文件保存在命名卷 `enterprise-rag-ai-agent-platform_rag_data`。普通停止不会删除数据：

```powershell
docker compose down
```

备份前暂停应用写入，再从只读数据卷生成归档：

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
docker compose stop app
docker run --rm `
  --volume enterprise-rag-ai-agent-platform_rag_data:/data:ro `
  --volume "${PWD}\backups:/backup" `
  enterprise-rag-ai-agent-platform:local `
  sh -c "tar -czf /backup/rag-data-backup.tar.gz -C /data ."
docker compose start app
```

`backups/` 已被 Git 和 Docker 构建上下文忽略，但其中仍是敏感业务数据，应转移到受控备份位置并按策略加密、留存。请在隔离环境定期验证备份可恢复。`docker compose down --volumes` 会永久删除命名卷，不应作为普通停止命令使用。

## 5. 对外部署边界

- 默认端口只绑定 `127.0.0.1`；对外提供服务时应放在 HTTPS 反向代理之后，不要直接暴露 Uvicorn。
- 当前 SQLite、上传卷和进程内 Agent 只适合单实例。多实例应迁移 PostgreSQL、对象存储和外部任务队列。
- 对外环境还需要 SSO/OIDC、速率限制、恶意文件扫描、集中日志、密钥托管和备份恢复演练。
- LLM 与 Embedding Key 仅通过本地 `.env` 或部署平台 Secret 注入，不能写入镜像和仓库。
