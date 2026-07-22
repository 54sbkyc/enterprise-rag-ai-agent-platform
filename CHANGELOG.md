# Changelog

本文件记录公开作品集版本的重要变化。版本号遵循 Semantic Versioning。

## [Unreleased]

## [1.3.0] - 2026-07-22

面向干净机器复现、安全启动和单实例部署验收的容器交付版本。

### Added

- 新增非 root Python 3.12 运行镜像与精简运行依赖，固定单 Uvicorn Worker 以匹配进程内 Agent 执行模型。
- 新增 Docker Compose 交付，默认仅绑定本机端口，并启用持久卷、只读根文件系统、独立 tmpfs、能力裁剪和 `no-new-privileges`。
- 新增 `development`、`test`、`production` 运行环境；生产空库必须提供至少 12 位首次管理员密码，不再创建公开演示账号。
- 新增 `/api/health/live` 和访问 SQLite 的 `/api/health/ready`，数据库异常返回不包含内部路径的通用 `503`。
- 新增容器部署、日志、备份和故障排查指南，数据卷备份目录默认不进入 Git 或镜像上下文。

### Changed

- GitHub Actions 新增容器实跑任务，验证 Compose、镜像构建、弱配置拒绝、非 root 身份、管理员登录和持久化重启。
- 生产管理员仅在数据库不存在管理员时创建，容器重启或环境变量变化不会覆盖已有密码。
- README、安全说明、贡献指南、架构决策、生产化路线图和发布治理统一纳入容器交付契约。

### Validation

- 136 项 pytest 自动化测试通过。
- 12 条角色化黄金用例全部通过，Recall@K、MRR、答案、拒答与访问控制准确率均为 100%。
- GitHub Actions 在干净 Ubuntu Runner 成功构建镜像，并通过生产空密码拒绝、UID `10001`、数据库就绪、管理员登录与持久卷重启烟测。
- Compose 配置解析、锁定依赖、Python 编译、Markdown 链接、忽略规则和疑似密钥扫描通过。

### Known Boundaries

- 当前容器仍是 SQLite + 进程内 Agent 的单实例交付，不支持直接横向扩容。
- 对外服务仍需要 HTTPS 反向代理、SSO/OIDC、速率限制、恶意文件扫描、集中日志与密钥托管。
- 多实例部署前应迁移 PostgreSQL、对象存储和外部任务队列。

## [1.2.0] - 2026-07-22

面向 AI 应用开发作品集的可靠性与安全增强版本。

### Added

- Agent 支持进程内异步任务、持久化状态、幂等提交、协作式取消和失败任务重试。
- 新增任务详情、取消、重试 API，以及工作台轮询、取消和历史重试交互。
- 新增版本化 RAG 黄金数据集、数据集指纹、绝对阈值和历史基线回归门禁。
- 新增随代码评审的批准基线，CI 校验数据集版本、指纹和 Top K 后执行 5 个百分点回退门禁。
- 新增 `python -m app.eval_gate_cli`，门禁失败返回非零退出码并在 GitHub Actions 上传 JSON 报告。
- 将黄金集升级为 12 条角色化 v2 用例，覆盖管理员、技术员工、普通员工的可回答、越权拒答和无依据拒答场景。
- 新增访问控制准确率：任何引用超出用例执行角色的文档密级都会使门禁失败。
- 新增受限主题预检，低权限用户询问敏感主题时保守拒答，避免从普通资料拼接出看似合理的越权答案。

### Changed

- 将简历项目卡更新为带公开仓库、Release、CI 和量化工程指标的可投递版本。
- 新增面试前检查、8 分钟演示主线、故障预案和避免过度宣传的检查清单。
- 仓库、Release、CI 和许可证链接迁移到新账号 `54sbkyc`。
- 评测中心展示门禁结论、失败指标和基线变化；黄金用例改为只读，自定义用例继续支持维护。
- 评测中心支持为自定义用例选择执行角色，并在运行结果、历史记录和导出报告中展示访问控制指标。
- 修复企业样例 Markdown 一级标题被写成问号占位符的问题。
- 将关键词召回升级为正文 70%、标题 30% 的字段加权 BM25，修复通用流程词压过精确标题的问题。
- 发布验收新增锁定依赖完整性检查，避免 `pip check` 无法发现声明依赖未安装的问题。

### Validation

- 129 项 pytest 自动化测试通过。
- 12 条角色化黄金用例全部通过，Recall@K、MRR、答案、拒答与访问控制准确率均为 100%。
- GitHub Actions 完成锁定依赖检查、全量测试、确定性 RAG 门禁和 JSON 报告上传。
- Playwright 覆盖桌面与 390x844 手机视口，确认评测中心无横向溢出。

### Known Boundaries

- SQLite 与进程内 Agent 执行器适合单实例演示和小规模部署，不代表多实例生产架构。
- 受限主题预检只读取不可访问文档标题元数据；生产环境仍应升级为文档级 ACL 与策略引擎。
- 向量存储仍使用 SQLite JSON；大规模语料应迁移 PostgreSQL + pgvector 并接入独立 rerank。

## [1.1.0] - 2026-07-10

首个公开的 AI 应用开发作品集版本。

### Added

- BM25 默认检索、可选 OpenAI 兼容 Embedding、混合召回和本地重排。
- 关键条件依据覆盖率闸门，在核心条件缺失时保守拒答并记录缺失词。
- Recall@K、MRR、答案正确率和拒答准确率批量评测。
- 受控 Agent 规划、工具白名单、权限检查、超时重试和运行状态持久化。
- 问答决策轨迹、Token 用量、成本估算和 Agent 运行指标。
- GitHub Actions、发布检查、架构图、MIT License 和公开仓库治理。

### Changed

- 文档入库、重建索引和样例数据统一记录 Embedding 状态。
- 评测用例迁移到当前企业样例文档，来源匹配同时支持标题和文件名。
- 验收脚本现在会检查每个原生命令的退出码，失败时立即停止。

### Validation

- 113 项 pytest 自动化测试。
- Playwright 覆盖登录、检索、Agent、评测、拒答和移动端导航。
- 发布检查验证公开文件、Markdown 链接、忽略规则和常见密钥模式。

### Known Boundaries

- 默认使用 SQLite，适合本地演示和中小规模原型，不代表大规模生产部署。
- 未配置 Embedding 或 LLM 服务时，系统分别使用 BM25 和本地抽取式回答。
- Agent 当前同步执行；生产环境仍需异步队列、幂等、取消和人工审批。
- 关键条件覆盖率是可配置启发式规则，需要用真实业务评测集持续校准。

[Unreleased]: https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/releases/tag/v1.1.0
