# 企业级多 Agent 智能运维系统

本项目展示异常检测投票、拓扑 BFS 根因分析、故障自愈建议、dry-run、风险审批和审计记录。

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
