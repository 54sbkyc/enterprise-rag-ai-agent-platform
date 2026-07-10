# 简历项目卡

本文档用于把“企业知识库 RAG + AI Agent 平台”写进 AI 应用开发、Python 全栈开发、后端开发简历中。它强调工程闭环，不把项目描述成单纯毕业设计。

相关材料：

- 面试讲解：[interview_talking_points.md](interview_talking_points.md)
- 面试官评分卡：[portfolio_review_scorecard.md](portfolio_review_scorecard.md)
- 最终验收：[final_acceptance_report.md](final_acceptance_report.md)

## 项目名称

企业知识库 RAG + AI Agent 平台

## 一句话定位

基于 FastAPI + 原生前端实现的企业知识库 AI 应用，覆盖文档入库、权限过滤、RAG 问答、引用溯源、Agent 工具调用、质量评测、安全审计和 AI 可观测。

## 推荐简历写法

```text
企业知识库 RAG + AI Agent 平台 | Python / FastAPI / SQLite / JavaScript
- 基于 FastAPI + SQLite + 原生前端实现企业知识库问答系统，支持文档解析、BM25、可选 Embedding、融合重排、引用溯源、关键条件覆盖拒答和角色权限过滤。
- 设计受控 Agent 规划与执行链路，实现工具白名单、权限校验、超时重试、失败状态和运行生命周期持久化。
- 建设 AI 可观测能力，记录问答决策轨迹、生成/降级方式、Token 来源和成本估算，并在首页汇总 Agent 运行和工具调用指标。
- 实现 Recall@K、MRR、答案正确率、拒答准确率、知识缺口、反馈闭环和审计日志。
- 使用 pytest 覆盖 Agent、权限、安全、分页、评测、前端契约和发布治理，并配置 GitHub Actions 自动运行测试。
- 加固运行边界，实现会话过期、上传限额、跨域白名单、模型失败透明降级和公开仓库疑似密钥扫描。
```

## 面试 60 秒介绍

```text
这个项目是我面向 AI 应用开发岗位做的企业知识库 RAG + AI Agent 平台。它不是简单聊天页面，而是从企业内部资料问答出发，做了文档入库、权限过滤、检索增强、引用溯源、安全拦截、质量评测和审计日志。后面我又补了 Agent 工具调用和 AI 可观测，每次问答都能看到决策轨迹、token 和成本估算，首页也能看到 Agent 运行和工具调用指标。为了让项目更接近真实工程，我还补了自动化测试、GitHub Actions、生产化路线图、发布清单和最终验收报告。
```

## 面试追问时的展开点

| 追问方向 | 可以怎么回答 |
| --- | --- |
| RAG 怎么做 | 文档切分后默认走 BM25；配置 Embedding 后融合语义召回，再按标题和词项覆盖重排，最后返回 Top-K 引用。 |
| Agent 有什么价值 | Agent 先生成受控计划，再执行白名单工具；每步记录重试、耗时、状态和权限判断。 |
| 怎么降低幻觉 | 用引用片段约束回答，同时检查问题关键条件是否被依据覆盖；覆盖不足或低置信度时拒答，并通过评测中心和知识缺口持续改进。 |
| 企业安全怎么体现 | 后端权限校验、文档密级过滤、Prompt 注入拦截、敏感信息脱敏、会话过期、上传限额、跨域白名单和审计日志。 |
| 工程能力怎么体现 | FastAPI 接口、SQLite 持久化、前端工作台、自动化测试、CI、发布检查脚本和 GitHub 发布清单。 |

## 最适合投递的岗位

- AI 应用开发工程师
- Python 后端开发工程师
- Python 全栈开发工程师
- RAG/Agent 应用开发实习或初级岗位
- 企业内部工具/知识库系统开发岗位

## 关键词

`Python`、`FastAPI`、`RAG`、`BM25`、`Embedding`、`Hybrid Search`、`MRR`、`AI Agent`、`工具调用`、`AI 可观测`、`权限控制`、`自动化测试`

## 诚实边界

- 当前混合检索向量保存在 SQLite，生产化可升级为 pgvector + 独立 rerank。
- 当前数据库是 SQLite，生产化可升级为 PostgreSQL。
- 当前 Agent 仍同步执行，生产化还需要异步队列、取消、幂等、人工审批和更细粒度 ACL。
- 默认可以离线运行，真实大模型效果需要配置 OpenAI 兼容 API。
