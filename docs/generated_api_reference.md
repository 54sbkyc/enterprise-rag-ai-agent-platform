# 接口清单

本文档用于论文的接口设计章节。所有业务接口均以 `/api` 开头，除登录和健康检查外均需要 `Authorization: Bearer <token>`。

## 基础与认证

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/health` | 无 | 服务健康检查，返回应用名、版本和状态。 |
| POST | `/api/auth/login` | 无 | 用户登录，返回 token 和用户信息。 |
| GET | `/api/auth/me` | 登录用户 | 获取当前用户公开信息。 |
| POST | `/api/auth/logout` | 登录用户 | 删除当前会话。 |

## 用户管理

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/users` | 管理员 | 查询用户列表。 |
| POST | `/api/users` | 管理员 | 创建用户。 |
| PATCH | `/api/users/{user_id}` | 管理员 | 修改角色、启用状态或密码。 |
| DELETE | `/api/users/{user_id}` | 管理员 | 删除用户，并清理该账号的登录会话；不允许删除当前登录账号。 |

## 文档管理

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/documents/upload` | 管理员/技术员工 | 上传并解析文档，生成知识片段。 |
| POST | `/api/documents/embeddings/rebuild` | 管理员/技术员工 | 为历史文档批量补建或更新向量索引。 |
| GET | `/api/documents` | 管理员/技术员工 | 查询可见文档，支持关键词、密级、类型和排序筛选。 |
| GET | `/api/documents/{document_id}/chunks` | 管理员/技术员工 | 查看指定文档的知识片段。 |
| GET | `/api/documents/{document_id}/versions` | 管理员/技术员工 | 查看文档版本历史，包含版本号、操作类型、密级、片段数和操作者。 |
| PATCH | `/api/documents/{document_id}` | 管理员/技术员工 | 修改文档标题或密级。 |
| POST | `/api/documents/{document_id}/reindex` | 管理员/技术员工 | 重新解析并切分文档。 |
| DELETE | `/api/documents/{document_id}` | 管理员/技术员工 | 删除文档及其片段。 |

## 检索与问答

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/search` | 管理员/技术员工 | 执行标题/正文字段加权 BM25 或混合检索，按角色过滤密级，并返回分数拆解和排序解释。 |
| POST | `/api/ask` | 登录用户 | 执行安全检查、检索、回答生成、引用返回和日志记录。 |
| POST | `/api/qa-feedback` | 登录用户 | 提交问答有用性反馈，负向反馈自动沉淀为知识缺口。 |
| GET | `/api/qa-feedback` | 管理员/技术员工 | 查询员工问答反馈、关联问答记录和知识缺口状态。 |
| GET | `/api/logs` | 管理员/技术员工 | 查看问答日志和引用情况。 |

## Agent 任务

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/agent/run` | 登录用户 | 兼容接口，同步执行一次 Agent 任务并保存工具轨迹。 |
| POST | `/api/agent/tasks` | 登录用户 | 异步创建 Agent 任务，支持用户级幂等键并立即返回任务编号。 |
| GET | `/api/agent/runs` | 登录用户 | 分页查询任务历史；普通用户仅能查看自己的任务。 |
| GET | `/api/agent/runs/{run_id}` | 任务所有者/管理角色 | 查询任务状态、计划、工具轨迹和最终结果。 |
| POST | `/api/agent/runs/{run_id}/cancel` | 任务所有者/管理角色 | 请求协作式取消排队或运行中的异步任务。 |
| POST | `/api/agent/runs/{run_id}/retry` | 任务所有者/管理角色 | 将失败或已取消任务重试为一个关联的新任务。 |

## 知识缺口

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/knowledge-gaps` | 管理员/技术员工 | 查询低置信问题沉淀出的知识缺口，可按状态筛选。 |
| POST | `/api/knowledge-gaps` | 管理员/技术员工 | 创建知识缺口，支持关联来源问答记录。 |
| PATCH | `/api/knowledge-gaps/{gap_id}` | 管理员/技术员工 | 修改处理状态或备注。 |
| DELETE | `/api/knowledge-gaps/{gap_id}` | 管理员/技术员工 | 删除知识缺口记录。 |

## 知识库健康体检

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/knowledge-health` | 管理员/技术员工 | 生成知识库健康分、指标、风险文档、低置信样本、缺口状态和治理建议。 |
| GET | `/api/knowledge-health/export` | 管理员/技术员工 | 导出知识库健康体检 Markdown 或 CSV 报告。 |

## 评测

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/evaluate` | 管理员/技术员工 | 运行单条评测并保存得分。 |
| GET | `/api/evaluations` | 管理员/技术员工 | 查询评测记录。 |
| GET | `/api/evaluation/cases` | 管理员/技术员工 | 查询批量评测用例。 |
| GET | `/api/evaluation/dataset` | 管理员/技术员工 | 查询黄金数据集版本、指纹、用例数、默认阈值和批准基线。 |
| POST | `/api/evaluation/cases` | 管理员/技术员工 | 新增可编辑的自定义评测用例。 |
| PATCH | `/api/evaluation/cases/{case_id}` | 管理员/技术员工 | 修改自定义评测用例；版本化黄金用例只读。 |
| DELETE | `/api/evaluation/cases/{case_id}` | 管理员/技术员工 | 删除自定义评测用例；版本化黄金用例不可删除。 |
| POST | `/api/evaluation/batch/run` | 管理员/技术员工 | 默认仅运行黄金用例；支持 Top K、指标阈值、最小用例数、最大回退、指定基线和显式包含自定义用例。 |
| GET | `/api/evaluation/batch/runs` | 管理员/技术员工 | 查询门禁历史、数据集指纹、失败指标和基线差异。 |
| GET | `/api/evaluation/batch/runs/{run_id}/export` | 管理员/技术员工 | 导出 Markdown 或 CSV 报告。 |

## 统计与审计

| 方法 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- |
| GET | `/api/stats` | 管理员/技术员工 | 查询片段数、安全拦截数、平均置信度和评测均分。 |
| GET | `/api/dashboard` | 管理员/技术员工 | 查询首页总览数据。 |
| GET | `/api/analytics` | 管理员/技术员工 | 查询图表统计数据。 |
| GET | `/api/audit-logs` | 管理员 | 查询管理操作审计记录。 |

## 典型响应字段

| 字段 | 含义 |
| --- | --- |
| `confidence` | 回答置信度，来源于命中片段相似度。 |
| `citations` | 引用片段数组，包含文档 ID、标题、片段编号、相似度和片段内容。 |
| `blocked` | 是否被安全策略拦截。 |
| `block_reason` | 被拦截时的原因。 |
| `citation_hit` | 评测时引用来源命中率。 |
| `gate.status` | RAG 质量门禁结论，取值为 `passed` 或 `failed`。 |
| `gate.failed_metrics` | 未达到绝对阈值或相对基线要求的指标。 |
| `gate.metric_deltas` | 当前运行相对兼容历史基线的指标变化。 |
| `gate.baseline_reference` | 当前使用的历史运行或随代码提交的批准基线标识。 |
| `dataset.fingerprint` | 评测用例规范化后生成的 SHA-256 指纹。 |
