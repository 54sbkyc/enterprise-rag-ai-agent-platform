# 最终验收报告

本文档用于 GitHub 发布前的最终人工验收。它不是毕业设计论文材料，而是面向面试官和招聘方的 AI 应用开发作品集交付说明。

相关入口：

- 项目首页：[../README.md](../README.md)
- 简历项目卡：[resume_project_card.md](resume_project_card.md)
- 面试官评分卡：[portfolio_review_scorecard.md](portfolio_review_scorecard.md)
- 面试讲解：[interview_talking_points.md](interview_talking_points.md)
- AI 应用演示脚本：[demo_runbook.md](demo_runbook.md)
- Docker 安全部署：[container_deployment.md](container_deployment.md)
- 生产化路线图：[production_roadmap.md](production_roadmap.md)
- GitHub 发布清单：[github_release_checklist.md](github_release_checklist.md)
- 安全说明：[../SECURITY.md](../SECURITY.md)
- 贡献指南：[../CONTRIBUTING.md](../CONTRIBUTING.md)
- 架构决策记录：[architecture_decisions.md](architecture_decisions.md)

GitHub 发布版需要包含 `docs/resume_project_card.md` 和 `docs/portfolio_review_scorecard.md`，让招聘方能快速看到简历写法和面试官视角的项目价值判断。
同时需要包含 `SECURITY.md`、`CONTRIBUTING.md` 和 `docs/architecture_decisions.md`，展示安全边界、复现流程和关键技术取舍。

## 项目定位

项目定位为“企业知识库 RAG + AI Agent 平台”。它展示的不是单个聊天页面，而是一条完整的 AI 应用工程闭环：文档入库、权限过滤、检索问答、引用溯源、Agent 工具调用、质量评测、安全审计、成本估算和运行轨迹可观测。

作为 AI 应用开发作品集，它重点证明以下能力：

- 能把业务场景拆成可运行的产品流程。
- 能用 FastAPI 完成后端接口、权限、安全和数据持久化。
- 能实现 RAG 检索问答和引用约束回答。
- 能把 Agent 设计成可控工具链，而不是不可追踪的黑盒。
- 能用测试、CI、发布清单和验收报告保证项目可复现。
- 能把应用交付为带强密码引导、持久卷和真实就绪检查的非 root 容器。

## 功能验收

| 模块 | 验收状态 | 说明 |
| --- | --- | --- |
| 文档入库 | 已完成 | 支持 TXT、Markdown、PDF、DOCX 解析、切分、索引和版本记录。 |
| 权限控制 | 已完成 | 管理员、技术员工和普通员工角色分离，后端接口和检索范围按权限收敛；受限主题对低权限用户保守拒答。 |
| RAG 问答 | 已完成 | 支持 BM25、可选 Embedding、融合重排、权限过滤、引用回答和关键条件覆盖拒答。 |
| 安全拦截 | 已完成 | 支持 Prompt 注入拦截、敏感信息脱敏和审计记录。 |
| 运行时防护 | 已完成 | 支持会话过期、上传限额、跨域白名单、生产强密码引导、数据库就绪检查和模型降级透明标记。 |
| AI Agent | 已完成 | 支持受控规划、工具白名单、进程内异步执行、权限检查、幂等提交、协作式取消、失败重试和生命周期持久化。 |
| AI 可观测 | 已完成 | 记录决策轨迹、生成方式、Token 来源、成本估算、Agent 运行和工具调用指标。 |
| 质量评测 | 已完成 | 12 条黄金用例按角色执行，支持 Recall@K、MRR、答案、拒答、访问控制准确率和报告导出。 |
| 知识治理 | 已完成 | 支持知识缺口、健康体检和反馈沉淀。 |
| 前端工作台 | 已完成 | 原生 HTML/CSS/JavaScript 实现首页、问答、Agent、评测和治理页面。 |

## 工程验收

| 项目 | 验收状态 | 说明 |
| --- | --- | --- |
| 一键启动 | 已完成 | `start.ps1` 可创建虚拟环境、安装依赖并启动服务。 |
| 离线演示 | 已完成 | 未配置 API Key 时可使用本地抽取式回答。 |
| 大模型接入 | 已完成 | 支持 OpenAI Chat Completions 兼容配置。 |
| 自动化测试 | 已完成 | pytest 覆盖 Agent、权限、安全、分页、质量评测、黄金集门禁、前端契约和发布治理。 |
| AI 回归门禁 | 已完成 | 隔离数据库执行版本化黄金集，检查绝对阈值与批准/历史基线回退，失败时阻止 CI。 |
| 环境一致性 | 已完成 | 逐项验证锁定依赖存在且版本一致，再执行依赖冲突检查。 |
| 容器交付 | 已完成 | 非 root 单 Worker 镜像、只读根文件系统、持久卷和 Compose 安全默认项可在干净机器复现。 |
| CI | 已完成 | GitHub Actions 同时运行 136 项测试、RAG 门禁和容器构建/登录/重启烟测。 |
| 发布治理 | 已完成 | `.gitignore`、发布清单和检查脚本隔离本地数据库、上传文件、缓存、Word 文档和隧道工具。 |
| 密钥防泄漏 | 已完成 | 发布检查会扫描公开源码和文档中的常见疑似密钥格式。 |
| 文档完整性 | 已完成 | README、面试文档、生产化路线图、发布清单和本报告形成完整说明链路。 |

## 发布前验证

每次准备推到 GitHub 前，建议按顺序执行：

```powershell
.\scripts\verify_project.ps1
git status --ignored
```

验收标准：

- 测试命令退出码为 `0`。
- 发布检查脚本不报告缺失的必需文件。
- 发布检查脚本不报告疑似密钥格式。
- 发布检查脚本可以报告本地 WARN，但这些 WARN 必须是数据库、上传文件、Word 文档、隧道工具、缓存或内部计划等不进入 GitHub 的内容。
- `git status --ignored` 中不应把本地运行数据、毕业设计 Word、API Key 或隧道工具列为待提交文件。

## 不进入 GitHub

以下内容保留在本地工作副本中，但不进入公开仓库：

- `backend/data/*.db` 和 `backend/data/uploads/`：本地运行数据和上传资料。
- `*.docx`：毕业设计、课程报告、学习手册等 Word 文档。
- `tools/`、`start_tunnel.ps1`、`tunnel-url.txt`：本地临时公网访问工具。
- `.runtime/`、`.pytest_cache/`、`__pycache__/`、`*.pyc`：运行与测试缓存。
- `backups/`：容器数据卷备份，可能包含账号、问答记录和上传资料。
- `docs/superpowers/`：Codex 实施计划和内部过程记录。
- `docs/opening_report.md`、`docs/thesis_outline.md`、`docs/hieu_thesis_revision_rules.md`、`docs/demo_script.md`：毕业设计或校内答辩导向文档。

这样做的原因是：GitHub 作品集应该突出 AI 应用开发能力，而不是把本地运行痕迹、论文过程材料和临时工具一起暴露出去。

## 生产化边界

面试中可以主动说明当前版本的取舍：

- 检索层已支持 BM25 + 可选 Embedding 混合召回和本地重排；生产环境需将向量迁移到 pgvector 并接入独立 rerank 模型。
- 本地回答已增加关键条件覆盖率闸门，能拒绝“召回相似资料但核心条件无依据”的问题；该启发式阈值仍需用真实业务评测集持续校准。
- 数据库当前使用 SQLite，适合轻量演示；生产环境建议迁移到 PostgreSQL。
- Agent 已有进程内异步执行、幂等、协作式取消、重试和持久化状态；生产环境仍需外部队列、任务租约、跨实例恢复、供应商级取消、人工审批和更细粒度 ACL。
- 当前容器固定一个 Worker 并使用持久卷，适合单实例部署；公网与多实例环境仍需 HTTPS 反向代理、对象存储、SSO、集中日志和密钥托管。
- 默认回答可离线运行；真实大模型效果需要配置 OpenAI 兼容 API。

这些边界不降低项目含金量。能清楚说明当前实现和生产升级路径，反而更像真实工程项目。

## 面试验收话术

可以这样介绍：

```text
这个项目是我在毕业设计基础上继续升级出的 AI 应用开发作品集。它不是简单 ChatGPT 套壳，而是围绕企业知识库问答做了文档入库、权限过滤、RAG 检索、引用溯源、Agent 工具调用、安全审计、质量评测和 AI 可观测。为了让项目可以复现和交付，我还补了 136 项自动化测试、RAG 质量门禁、非 root 容器、容器 CI 实跑、发布清单和最终验收报告。
```
