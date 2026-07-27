# 模型网关韧性与故障处理

问答生成、Embedding 和 Agent Planner 统一通过 `backend/app/provider_gateway.py` 请求 OpenAI-compatible 服务。该网关不保存 API Key，不改变业务 Prompt，只负责有界超时、重试、退避、错误分类、熔断和运行诊断。

## 默认策略

| 调用链 | 超时 | 最大尝试次数 | 失败后的业务行为 |
| --- | ---: | ---: | --- |
| 问答生成 | 20 秒 | 3 | 返回带引用的本地抽取式回答，并记录降级原因 |
| Embedding | 30 秒 | 3 | 标记索引失败，不写入部分向量 |
| Agent Planner | 15 秒 | 2 | 回退到确定性白名单计划 |

重试采用指数退避，默认从 0.25 秒开始，单次等待最多 2 秒。供应商返回 `Retry-After` 时优先采用该值，但仍受最大等待限制。

## 错误语义

| 情况 | 错误码 | 是否重试 |
| --- | --- | --- |
| 网络中断、连接失败、HTTP 5xx | `provider_unavailable` | 是 |
| 请求超时、HTTP 408 | `provider_timeout` | 是 |
| HTTP 429 | `provider_rate_limited` | 是 |
| HTTP 401/403 | `provider_auth_error` | 否 |
| 其他 HTTP 4xx | `provider_request_rejected` | 否 |
| 非法 JSON、字段缺失、响应超限 | `invalid_provider_response` | 否 |
| 熔断期间拒绝调用 | `provider_circuit_open` | 否，不发出网络请求 |

连续 5 个最终失败的可重试请求会按供应商主机打开熔断器 30 秒。冷却期结束后只允许一个探测请求；成功或收到不可重试的 HTTP 响应表示供应商已经可达，熔断器关闭。该状态是进程内保护，不宣称跨实例一致。

## 配置

完整模板见 [../.env.example](../.env.example)。常用变量包括：

- `LLM_*`：问答生成的超时、尝试次数和退避上限。
- `EMBEDDING_*`：Embedding 批次的超时、尝试次数和退避上限。
- `AGENT_PLANNER_*`：模型规划的超时、尝试次数和退避上限。
- `MODEL_GATEWAY_CIRCUIT_FAILURE_THRESHOLD`：打开熔断器前的连续失败请求数。
- `MODEL_GATEWAY_CIRCUIT_COOLDOWN_SECONDS`：熔断冷却时间。
- `MODEL_GATEWAY_MAX_RESPONSE_BYTES`：单次 JSON 响应上限，默认 5 MiB。

为防止配置错误放大故障，最大尝试次数硬限制为 10，超时硬限制为 300 秒，响应上限硬限制为 20 MiB。

## 运行诊断

`GET /api/health/ready` 的 `model_gateway` 字段提供进程内聚合状态：

```json
{
  "status": "ready",
  "circuit_state": "closed",
  "tracked_providers": 1,
  "open_circuits": 0,
  "requests": 12,
  "attempts": 14,
  "retries": 2,
  "successes": 11,
  "failures": 1,
  "circuit_rejections": 0
}
```

模型服务是可选增强，因此熔断不会让整个应用就绪检查返回 503；问答和 Planner 会按上表降级。每次问答的 `usage` 与决策轨迹还会持久化 `provider_attempts`、`provider_latency_ms` 和 `provider_status_code`，Embedding 管理接口返回同类诊断。

## 故障验证

```powershell
python -m pytest backend/tests/test_provider_gateway.py -q
```

测试会注入 429、超时、401、连续 503、超大响应和半开探测，验证重试边界、`Retry-After`、错误分类、熔断拒绝与恢复，不依赖真实付费模型服务。

## 生产边界

当前计数器和熔断状态属于单进程。多 Worker 或多实例部署应迁移到独立 API Gateway、Service Mesh 或共享状态的模型代理，并把调用指标接入集中 tracing 和告警系统。
