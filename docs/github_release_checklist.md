# GitHub 发布清单

这份清单用于把当前工作副本整理成适合发布到 GitHub 的作品集仓库。原则是：保留能证明 AI 应用开发能力的源码、测试、截图和文档；不要提交本地运行数据、毕业设计 Word、隧道工具、缓存和密钥。

## 必须提交

- `README.md`：项目定位、截图、技术栈、运行方式、演示流程。
- `CHANGELOG.md`、`docs/releases/`：公开版本变更记录和 GitHub Release 说明。
- `LICENSE`：MIT 开源许可证，明确公开仓库的使用边界。
- `.gitignore`：屏蔽本地运行文件、数据库、上传文件、缓存、Word 文档和隧道工具。
- `.gitattributes`：固定源码与文档行尾，标记图片和压缩文件为二进制，避免跨平台差异。
- `.env.example`：展示可配置环境变量，不包含真实密钥。
- `Dockerfile`、`compose.yaml`、`compose.pgvector.yaml`、`.dockerignore`：非 root 应用容器、生产管理员引导、持久卷、可选 pgvector 服务和安全构建上下文。
- `SECURITY.md`：安全说明，解释密钥、本地数据、Prompt 注入、权限控制和 AI 安全边界。
- `CONTRIBUTING.md`：贡献指南，说明快速启动、运行测试、发布检查和文档同步流程。
- `.github/workflows/tests.yml`：GitHub Actions 工作流，自动运行 `pytest`、RAG 质量门禁、真实 pgvector 集成测试、容器烟测并上传 JSON 报告。
- `start.ps1`：一键创建虚拟环境、安装依赖、启动服务。
- `backend/app/`：FastAPI 后端、RAG、Agent、权限、安全、评测、可观测等核心代码。
- `backend/app/embeddings.py`、`backend/app/vector_store.py`、`backend/app/agent_planner.py`、`backend/app/evaluation_*.py`：向量生成、pgvector 存储适配、受控规划、版本化数据集和质量门禁核心实现。
- `backend/evaluation/golden_cases.v2.json`、`backend/evaluation/approved_baseline.v2.json`：进入代码评审的 12 条角色化 RAG 黄金数据集与批准基线；v1 文件仅保留为历史快照。
- `backend/tests/`：pytest 测试，证明核心流程可回归。
- `backend/requirements.txt`、`backend/requirements-runtime.txt`：开发测试依赖和容器精简运行依赖。
- `backend/seed_enterprise_documents.py`：可复现的企业样例文档导入脚本。
- `frontend/`：前端页面、样式和交互逻辑。
- `samples/`：轻量样例文档，可用于演示上传和权限过滤。
- `docs/resume_project_card.md`：简历项目卡，用于投递和面试前快速准备。
- `docs/portfolio_review_scorecard.md`：面试官评分卡，用于说明项目含金量和边界。
- `docs/architecture_decisions.md`：架构决策记录，说明 FastAPI、SQLite、混合检索、Agent 规划与发布治理等取舍。
- `docs/interview_talking_points.md`：面试讲解要点。
- `docs/demo_runbook.md`：面向 AI 应用开发岗位的 8 分钟演示脚本和生产化追问。
- `docs/interview_demo_checklist.md`：面试前环境检查、演示主线和故障预案。
- `docs/production_roadmap.md`：生产化演进路径，说明 embedding、pgvector、rerank、PostgreSQL、异步 Agent、部门级 ACL 等升级方向。
- `docs/container_deployment.md`：容器启动、强密码、就绪检查、日志、持久卷备份和单实例边界。
- `docs/pgvector_retrieval.md`：真实向量后端的配置、历史对账、权限过滤、故障降级、CI 证据和诚实边界。
- `docs/rag_quality_gate.md`：门禁指标、阈值、基线匹配、CLI 与 CI 行为说明。
- `docs/final_acceptance_report.md`：最终验收报告，说明功能完成度、工程完成度、发布前验证和生产化边界。
- `docs/screenshots/`：README 使用的展示截图。
- `docs/diagrams/`：组件、时序、流程、用例和数据库 ER 架构图及 PlantUML 源文件。
- `docs/github_release_checklist.md`：本清单。
- `scripts/prepare_github_release.ps1`：发布前检查脚本。
- `scripts/verify_project.ps1`：编译、依赖、测试和发布检查的一键总验收脚本。

## 不应提交

- `backend/data/rag_platform.db`、`backend/data/*.db`、`backend/data/*.db-wal`、`backend/data/*.db-shm`：本地运行数据库和 SQLite 临时文件。
- `backend/data/uploads/`：本地上传文件，可能包含私有资料。
- `.venv/`：本地 Python 虚拟环境。
- `.runtime/`：本地服务 PID 和日志。
- `backups/`：容器数据卷备份，可能包含账号、问答记录和上传资料。
- `.pytest_cache/`、`__pycache__/`、`*.pyc`：测试和 Python 缓存。
- `.env`、`.env.*`：真实 API Key 和本地配置，`.env.example` 除外。
- `*.docx`：毕业设计报告、课程报告、学习手册等 Word 文件。
- `tools/`：本地隧道工具或二进制文件。
- `start_tunnel.ps1`、`tunnel-url.txt`：本地临时公网访问配置。
- `*.zip`、`*.7z`、`*.rar`：临时压缩包或交付包。
- `htmlcov/`、`.coverage`：本地测试覆盖率输出。
- `docs/superpowers/`：Codex 实施计划和内部过程记录，不适合作为公开作品集内容。
- `docs/opening_report.md`、`docs/thesis_outline.md`、`docs/hieu_thesis_revision_rules.md`、`docs/demo_script.md`：毕业设计或校内答辩导向文档，GitHub 作品集发布版不提交。
- `scripts/` 下的论文、报告、截图录制和视频生成 Python 脚本：属于本地交付过程工具，不进入公开作品集。

## 发布前检查

1. 运行一键总验收：

   ```powershell
   .\scripts\verify_project.ps1
   ```

2. 如需单独运行发布检查脚本：

   ```powershell
   .\scripts\prepare_github_release.ps1
   ```

   如需单独复现 AI 质量基线：

   ```powershell
   cd backend
   python -m app.eval_gate_cli --output ..\.runtime\evaluation-gate-report.json
   ```

3. 检查 Git 状态：

   ```powershell
   git status --ignored
   ```

4. 确认 README 中的截图能正常显示：

   - `docs/screenshots/dashboard-ai-ops.png`
   - `docs/screenshots/agent-workbench.png`
   - `docs/screenshots/qa-observability.png`
   - `docs/screenshots/rag-quality-gate.png`

5. 确认疑似密钥扫描通过，并人工确认仓库里没有真实 API Key、个人隐私、毕业设计 Word 文件、本地数据库或上传资料。

6. 确认 CI 文件已纳入提交：

   ```text
   .github/workflows/tests.yml
   ```

   容器交付变更还要确认 `docker compose config`、镜像构建和容器烟测通过。

7. 确认最终验收报告已纳入提交：

   ```text
   docs/final_acceptance_report.md
   ```

## 推荐 GitHub 首次提交顺序

1. 初始化仓库并查看忽略效果：

   ```powershell
   git init
   git status --ignored
   ```

2. 只添加发布版应提交内容：

   ```powershell
   git add README.md CHANGELOG.md LICENSE .gitignore .gitattributes .env.example .dockerignore Dockerfile compose.yaml compose.pgvector.yaml .github start.ps1 backend frontend samples SECURITY.md CONTRIBUTING.md docs/screenshots docs/diagrams docs/releases docs/resume_project_card.md docs/portfolio_review_scorecard.md docs/architecture_decisions.md docs/interview_talking_points.md docs/interview_demo_checklist.md docs/demo_runbook.md docs/container_deployment.md docs/pgvector_retrieval.md docs/production_roadmap.md docs/rag_quality_gate.md docs/final_acceptance_report.md docs/github_release_checklist.md scripts/prepare_github_release.ps1 scripts/verify_project.ps1
   ```

3. 提交：

   ```powershell
   git commit -m "feat: publish enterprise rag ai agent portfolio"
   ```

4. 推送到 GitHub 前，再运行一次：

   ```powershell
   .\scripts\verify_project.ps1
   ```

## 面试展示建议

- 不要把仓库解释成“毕业设计源码”，而是解释为“从毕业设计基础升级出的 AI 应用开发作品集”。
- 面试时先展示 README 第一屏、首页 AI 运营指标、Agent 工作台和问答可观测轨迹。
- 如果被问到生产化差距，主动说明 pgvector 已作为可选向量投影落地，但业务事实源和 BM25 仍在 SQLite、Agent 仍使用单实例进程内执行器；后续继续迁移业务表、全文检索、独立 rerank、外部任务队列和更细粒度 ACL。
