# 面试演示检查清单

这份清单用于 AI 应用开发面试前的最后检查。目标是保证 8 分钟内稳定展示真实能力，不在现场临时调环境或堆功能说明。

## 面试前一天

- 确认 [GitHub Actions](https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/actions/workflows/tests.yml) 为绿色。
- 确认 [v1.3.0 Release](https://github.com/54sbkyc/enterprise-rag-ai-agent-platform/releases/tag/v1.3.0) 可以打开。
- 本地运行 `git status -sb`，确保公开仓库工作区干净。
- 运行 `\.\scripts\verify_project.ps1`，记录当前 pytest 通过数量。
- 确认验证输出中的 RAG quality gate 为 `PASSED`，Actions 中可下载 JSON 报告。
- 检查 README 四张截图、架构图和生产化路线图链接。

## 面试前五分钟

1. 运行 `\.\start.ps1`，确认健康检查返回 `version: 1.3.0` 和 `status: ok`。
2. 使用 `admin / admin123` 登录，确认文档、检索、Agent 和评测页面可进入。
3. 提前打开 GitHub 仓库、Actions、Release 和本地应用四个标签页。
4. 关闭无关软件和通知，不展示 `.env`、数据库、上传目录或个人文件。
5. 保留 README 截图作为网络或本地服务异常时的备用演示材料。

## 八分钟主线

| 时间 | 展示内容 | 要证明的能力 |
| --- | --- | --- |
| 0:00-0:45 | GitHub README、Actions、Release | 项目可复现、可维护、能交付。 |
| 0:45-2:00 | 检索调试：员工事假问题 | BM25、可选向量、重排、Top-K 和权限过滤。 |
| 2:00-3:15 | 问答：员工事假问题 | 引用、置信度、决策轨迹、Token 和成本。 |
| 3:15-4:15 | 问答：火星差旅问题 | 即使命中差旅制度，核心条件无依据时仍拒答。 |
| 4:15-5:45 | Agent 工作台 | 受控计划、工具白名单、权限、重试、耗时和状态。 |
| 5:45-6:45 | 评测中心 | 12 条角色化黄金集、门禁结论、批准/历史基线差异，以及 Recall@K、MRR、答案、拒答与访问控制准确率。 |
| 6:45-8:00 | 架构和生产化路线图 | 诚实说明 SQLite、进程内 Agent、外部队列、pgvector 和 ACL 演进。 |

## 必备问题

```text
员工事假需要提前多久申请？
```

```text
火星差旅费用如何报销？
```

```text
请创建知识缺口：公司量子卫星报销规则是什么？
```

## 故障预案

- **Embedding 未配置**：明确说明当前走 BM25，本地界面会展示向量分数为 0；不要声称语义通道已启用。
- **LLM 未配置或调用失败**：展示本地抽取或透明降级状态，说明回答仍受引用和覆盖率闸门约束。
- **网络不可用**：使用本地应用、README 截图和已保存架构图继续演示。
- **本地服务异常**：先展示 GitHub Actions、Release 和测试结果，不在面试现场长时间排障。

## 不要这样讲

- 不说“已经达到大型企业生产级”。
- 不把 12 条内置角色化回归集的 100% 指标描述成通用业务准确率。
- 不把本地抽取式回答说成真实大模型生成。
- 不回避 SQLite、单实例任务执行器、启发式覆盖阈值和部门级 ACL 尚未落地。

完整讲解台词见 [AI 应用演示脚本](demo_runbook.md)，技术追问见 [面试讲解要点](interview_talking_points.md)。
