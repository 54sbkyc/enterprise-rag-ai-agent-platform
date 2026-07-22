# 简历项目卡

本文档用于把“企业知识库 RAG + AI Agent 平台”写进 AI 应用开发、Python 全栈开发、后端开发简历中。它强调工程闭环，不把项目描述成单纯毕业设计。

相关材料：

- GitHub 仓库：[enterprise-rag-ai-agent-platform](https://github.com/54sbkyc/enterprise-rag-ai-agent-platform)
- 正式版本：[v1.3.0](https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/releases/tag/v1.3.0)
- 持续集成：[GitHub Actions](https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/actions/workflows/tests.yml)
- 面试讲解：[interview_talking_points.md](interview_talking_points.md)
- 面试前检查：[interview_demo_checklist.md](interview_demo_checklist.md)
- 面试官评分卡：[portfolio_review_scorecard.md](portfolio_review_scorecard.md)
- 最终验收：[final_acceptance_report.md](final_acceptance_report.md)

## 项目名称

企业知识库 RAG + AI Agent 平台

## 一句话定位

基于 FastAPI + 原生前端实现的企业知识库 AI 应用，覆盖文档入库、权限过滤、RAG 问答、引用溯源、Agent 工具调用、质量评测、安全审计和 AI 可观测。

## 推荐简历写法

```text
企业知识库 RAG + AI Agent 平台 | Python / FastAPI / SQLite / JavaScript
- 基于 FastAPI + SQLite + 原生前端实现企业知识库问答系统，支持标题/正文字段加权 BM25、可选 Embedding、融合重排、引用溯源、关键条件覆盖拒答和角色权限过滤。
- 设计关键条件覆盖率拒答和 12 条角色化 RAG 质量门禁，使用黄金集指纹、批准基线和历史运行回退检测；Recall@K、MRR、答案、拒答与访问控制五项批准基线均为 100%。
- 设计受控 Agent 规划与执行链路，实现工具白名单、权限校验、超时重试、失败状态、运行生命周期持久化和逐步耗时追踪。
- 建设 AI 可观测与工程交付能力，记录生成/降级方式、Token 和成本，使用 136 项 pytest、Playwright、RAG 质量门禁和 GitHub Actions 容器实跑保障回归质量。
- 加固企业应用边界，实现文档密级、Prompt 注入拦截、会话过期、上传限额、跨域白名单、模型失败透明降级和疑似密钥扫描。
- 提供非 root Docker/Compose 交付，落实生产强密码引导、只读根文件系统、持久卷、数据库就绪检查和安全重启验证。
```

## 面试 60 秒介绍

```text
这个项目是我面向 AI 应用开发岗位做的企业知识库 RAG + AI Agent 平台。它不是聊天套壳，而是从企业内部资料问答出发，完成了文档入库、权限过滤、字段加权 BM25 与可选向量混合检索、引用溯源和关键条件拒答。我把检索和生成质量拆成 Recall@K、MRR、答案、拒答与访问控制准确率，并用 12 条角色化黄金集、批准基线和失败退出码做 CI 回归门禁；Agent 则具备工具白名单、异步执行、幂等、取消重试和运行轨迹。交付侧使用非 root 容器、强密码引导、持久卷和容器 CI 实跑，同时明确说明 SQLite、单实例任务执行器等生产化边界。
```

## 面试追问时的展开点

| 追问方向 | 可以怎么回答 |
| --- | --- |
| RAG 怎么做 | 文档切分后以正文 70%、标题 30% 计算字段加权 BM25；配置 Embedding 后融合语义召回，再做本地重排并返回 Top-K 引用。 |
| Agent 有什么价值 | Agent 先生成受控计划，再执行白名单工具；每步记录重试、耗时、状态和权限判断。 |
| 怎么降低幻觉 | 用引用片段和关键条件覆盖率约束回答；版本化黄金集在 CI 中检查检索、答案和拒答退化，线上负反馈再进入知识缺口。 |
| 企业安全怎么体现 | 后端权限校验、文档密级过滤、受限主题保守拒答、角色化访问控制回归、Prompt 注入拦截、敏感信息脱敏、会话过期和审计日志。 |
| 工程能力怎么体现 | FastAPI 接口、SQLite 持久化、异步任务、136 项自动化测试、带失败退出码的 AI 质量门禁、非 root 容器 CI 实跑和发布治理。 |

## 最适合投递的岗位

- AI 应用开发工程师
- Python 后端开发工程师
- Python 全栈开发工程师
- RAG/Agent 应用开发实习或初级岗位
- 企业内部工具/知识库系统开发岗位

## 关键词

`Python`、`FastAPI`、`RAG`、`BM25`、`Embedding`、`Hybrid Search`、`MRR`、`AI Agent`、`工具调用`、`AI 可观测`、`权限控制`、`Docker`、`自动化测试`

## 诚实边界

- 当前混合检索向量保存在 SQLite，生产化可升级为 pgvector + 独立 rerank。
- 当前数据库是 SQLite，生产化可升级为 PostgreSQL。
- 当前 Agent 使用单实例进程内异步执行器，生产化还需要外部队列、任务租约、跨实例恢复、人工审批和更细粒度 ACL。
- 默认可以离线运行，真实大模型效果需要配置 OpenAI 兼容 API。
