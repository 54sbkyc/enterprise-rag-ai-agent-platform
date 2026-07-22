# 数据库表说明

系统使用 SQLite 存储结构化数据。数据库位于 `backend/data` 目录下，初始化脚本为 `backend/app/schema.sql`。

## 表结构概览

| 表名 | 作用 |
| --- | --- |
| `users` | 存储系统用户、角色、显示名称、启用状态和密码哈希。 |
| `sessions` | 存储登录会话 token，用于接口鉴权。 |
| `documents` | 存储文档元数据、密级、片段数、Embedding 状态和模型。 |
| `chunks` | 存储知识片段、词频 JSON、向量 JSON、模型和内容哈希。 |
| `qa_logs` | 存储问答日志，包括问题、回答、置信度、拦截信息、引用 JSON。 |
| `evaluations` | 存储单条评测结果，包括期望关键词、期望来源、得分、引用命中率。 |
| `evaluation_cases` | 存储黄金/自定义评测用例、稳定键、数据集版本、业务分类和是否应回答标记。 |
| `batch_eval_runs` | 存储评测指标、数据集指纹、门禁策略、失败指标、基线引用及指标差异。 |
| `batch_eval_results` | 存储批量评测每条用例的明细结果。 |
| `agent_runs` | 存储 Agent 任务状态、计划、工具轨迹、幂等键、取消和重试关系。 |
| `audit_logs` | 存储管理员操作审计。 |

## 核心关系

| 关系 | 说明 |
| --- | --- |
| `documents.id` -> `chunks.document_id` | 一个文档对应多个知识片段。 |
| `users.id` -> `sessions.user_id` | 一个用户可拥有多个会话。 |
| `users.id` -> `qa_logs.user_id` | 问答日志关联提问用户。 |
| `users.id` -> `evaluations.user_id` | 单条评测记录关联执行用户。 |
| `batch_eval_runs.id` -> `batch_eval_results.run_id` | 一次批量评测对应多条明细。 |
| `batch_eval_runs.id` -> `batch_eval_runs.baseline_run_id` | 当前门禁运行可关联一个数据集指纹和 Top K 相同的历史基线。 |
| `evaluation_cases.id` -> `batch_eval_results.case_id` | 批量评测明细可关联原始用例。 |
| `users.id` -> `agent_runs.user_id` | Agent 任务关联提交用户，用于任务级访问隔离。 |
| `agent_runs.id` -> `agent_runs.parent_run_id` | 重试任务关联原失败或取消任务。 |
| `users.id` -> `audit_logs.user_id` | 操作审计关联操作者。 |

## 关键字段说明

| 表名 | 字段 | 说明 |
| --- | --- | --- |
| `documents` | `access_level` | 文档密级，取值为 `public`、`internal`、`sensitive`。 |
| `documents` | `chunk_count` | 当前文档切分出的知识片段数量。 |
| `chunks` | `token_json` | 片段词频统计，与即时计算的标题词频共同用于字段加权 BM25。 |
| `chunks` | `embedding_json` | 可选语义向量，用于混合召回。 |
| `chunks` | `embedding_model` | 生成该向量的模型名称。 |
| `qa_logs` | `blocked` | 安全策略是否拦截该问题。 |
| `qa_logs` | `citations_json` | 回答引用片段的 JSON 序列化结果。 |
| `evaluations` | `score` | 单条评测得分。 |
| `evaluations` | `citation_hit` | 期望来源文档命中率。 |
| `evaluation_cases` | `case_key` | 黄金用例的稳定唯一标识；自定义用例为空。 |
| `evaluation_cases` | `dataset_version` | 用例所属黄金集版本或 `custom`。 |
| `evaluation_cases` | `actor_role` | 执行用例时采用的管理员、技术员工或普通员工角色。 |
| `batch_eval_runs` | `avg_score` | 批量评测平均得分。 |
| `batch_eval_runs` | `avg_confidence` | 批量评测平均置信度。 |
| `batch_eval_runs` | `citation_hit_rate` | 批量评测引用命中率。 |
| `batch_eval_runs` | `dataset_hash` | 规范化用例内容的 SHA-256 指纹，用于匹配兼容基线。 |
| `batch_eval_runs` | `gate_status` | 绝对阈值和相对回退检查后的门禁结论。 |
| `batch_eval_runs` | `thresholds_json` | Recall@K、MRR、答案、拒答和访问控制准确率阈值。 |
| `batch_eval_runs` | `access_control_accuracy` | 所有用例引用均处于执行角色权限范围内的比例。 |
| `batch_eval_runs` | `metric_deltas_json` | 当前指标相对历史基线的变化。 |
| `batch_eval_runs` | `baseline_reference` | 历史运行编号或随代码提交的批准基线版本。 |
| `agent_runs` | `status` | 任务状态，包括 queued、running、cancel_requested、cancelled、completed、blocked 和 failed。 |
| `agent_runs` | `idempotency_key` | 用户级幂等键，避免网络重试导致重复执行。 |
| `agent_runs` | `tool_calls_json` | Agent 每一步工具输入、输出、状态、重试次数和耗时。 |
| `agent_runs` | `parent_run_id` | 失败或取消任务重试后的父任务编号。 |
| `audit_logs` | `detail` | 管理动作详情，使用 JSON 字符串保存。 |

## 设计特点

- 使用外键维护文档、片段、用户、评测之间的引用关系。
- 删除文档时级联删除片段，避免无主知识片段。
- 删除用户后保留问答和评测记录，用户字段置空，保证审计历史不丢失。
- 密级字段存储在文档表，检索和问答时统一按用户角色过滤。
- 引用、关键词、期望来源等半结构化字段使用 JSON 字符串保存，便于扩展。
- 黄金数据集保存在 Git 中并通过稳定键同步；界面新增的自定义用例不会覆盖版本化基线。
