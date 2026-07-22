# 贡献指南

本文档用于说明如何在本地复现、修改和验证本项目。即使项目主要作为个人作品集，也建议按这个流程维护，避免 GitHub 发布版混入本地数据或毕业设计过程材料。

## 快速启动

PowerShell 下运行：

```powershell
.\start.ps1
```

脚本会创建虚拟环境、安装依赖并启动服务。启动后访问脚本输出的本地地址，通常是：

```text
http://127.0.0.1:8000
```

## 运行测试

修改后至少运行：

```powershell
cd backend
python -m pytest
```

确认当前解释器与锁定依赖一致：

```powershell
python check_requirements.py
```

涉及检索、切分、重排、回答或拒答规则的改动，还必须运行确定性 RAG 质量门禁：

```powershell
python -m app.eval_gate_cli --output ..\.runtime\evaluation-gate-report.json
```

门禁失败时不要通过降低阈值掩盖退化；先查看失败指标和用例，再说明算法调整或黄金集版本升级的理由。

如果只改了发布治理或文档，可以先运行相关静态测试，再跑全量测试：

```powershell
cd backend
python -m pytest tests/test_github_release_governance.py tests/test_final_release_acceptance.py tests/test_portfolio_showcase_kit.py
python -m pytest
```

## 发布检查

准备推到 GitHub 前，回到项目根目录运行：

```powershell
.\scripts\verify_project.ps1
```

这个脚本不会删除、移动或打包文件。它会依次完成 Python 编译检查、依赖一致性检查、全量测试，以及必需文件、`.gitignore`、Markdown 链接和疑似密钥格式检查。

## 文档同步

如果你修改了功能或项目定位，请同步检查：

- [README.md](README.md)
- [docs/resume_project_card.md](docs/resume_project_card.md)
- [docs/interview_talking_points.md](docs/interview_talking_points.md)
- [docs/demo_runbook.md](docs/demo_runbook.md)
- [docs/production_roadmap.md](docs/production_roadmap.md)
- [docs/final_acceptance_report.md](docs/final_acceptance_report.md)
- [docs/github_release_checklist.md](docs/github_release_checklist.md)

如果新增了关键技术取舍，也请补充到 [docs/architecture_decisions.md](docs/architecture_decisions.md)。

## 不要提交

以下内容不要提交到 GitHub：

- 真实 API Key 或 `.env`
- `backend/data/*.db`
- `backend/data/uploads/`
- `.runtime/`
- `.venv/`
- `__pycache__/`
- `*.docx`
- `tools/`
- `start_tunnel.ps1`
- `tunnel-url.txt`
- `docs/superpowers/`
- 毕业设计或校内答辩专用 Markdown

具体范围见 [docs/github_release_checklist.md](docs/github_release_checklist.md)。

## 提交建议

推荐提交信息：

```text
feat: add enterprise rag ai agent portfolio
docs: improve github release readiness
test: cover release governance checks
fix: tighten permission filtering
```

提交前建议执行：

```powershell
.\scripts\verify_project.ps1
```
