# 企业级多 Agent 智能运维系统

本项目展示异常检测投票、拓扑 BFS 根因分析、故障自愈建议、dry-run、风险审批和审计记录，并提供一个不依赖第三方库的本地 HTTP API 初版。

默认只依赖 Python 标准库，便于离线演示。Kafka、Neo4j、Redis 和 Celery 属于可替换的生产适配层，不在本地演示中伪装为已接入。

运行测试：

```powershell
python -m unittest discover -s 06_Tests -v
```

运行离线演示：

```powershell
$env:PYTHONPATH = "02_Source\agent_tech_portfolio"
python -c "from aiops_agent import AIOpsOrchestrator, Alert; print(AIOpsOrchestrator().handle(Alert('order-service','cpu',95,[40,41,39,42,40])))"
```

启动标准库 HTTP API：

```powershell
$env:PYTHONPATH = "02_Source\agent_tech_portfolio"
python -m api_server
```

接口示例：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/incidents -ContentType "application/json" -Body '{"service":"order-service","metric":"cpu","value":95,"baseline":[40,41,39,42,40]}'
Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks
```

参考仓库保存在上级项目的 `02_Source\reference_multi_agent_aiops`，仅用于对照架构；项目仓库通过 `.gitignore` 忽略其内容，参考仓库自身保留独立 Git 历史。
