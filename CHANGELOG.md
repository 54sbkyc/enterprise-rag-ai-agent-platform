# Changelog

本文件记录公开作品集版本的重要变化。版本号遵循 Semantic Versioning。

## [Unreleased]

### Changed

- 将简历项目卡更新为带公开仓库、Release、CI 和量化工程指标的可投递版本。
- 新增面试前检查、8 分钟演示主线、故障预案和避免过度宣传的检查清单。

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

[1.1.0]: https://github.com/sbkyc/enterprise-rag-ai-agent-platform/releases/tag/v1.1.0
