# 企业级多 Agent 智能运维系统

本项目展示异常检测投票、拓扑 BFS 根因分析、故障自愈建议、dry-run、风险审批和审计记录，并提供一个不依赖第三方库的本地 HTTP API 初版。

当前核心链路支持阶段级重试、SQLite 检查点保存、等待审批后恢复，以及从 `04_Data\topology.json` 加载服务拓扑。API 重启后可继续查询已保存任务。

默认只依赖 Python 标准库，便于离线演示。Kafka 属于可选的生产事件总线适配层，未配置时使用内存总线；Neo4j、Redis 和 Celery 仍属于后续可替换适配层。

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
# 对处于 awaiting_approval 的任务进行人工审批
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/tasks/<task_id>/approval -ContentType "application/json" -Body '{"approved":true}'
```

参考仓库保存在上级项目的 `02_Source\reference_multi_agent_aiops`，仅用于对照架构；项目仓库通过 `.gitignore` 忽略其内容，参考仓库自身保留独立 Git 历史。

Kafka 模式（需要已运行的 Kafka broker）：

```powershell
python -m pip install -r 02_Source\agent_tech_portfolio\requirements-kafka.txt
$env:AIOPS_EVENT_BUS = "kafka"
$env:AIOPS_KAFKA_BOOTSTRAP = "localhost:9092"
$env:PYTHONPATH = "02_Source\agent_tech_portfolio"
python -m api_server
```

Kafka 发送失败不会让主流程直接崩溃，错误会记录在任务的 `event_bus_errors` 字段，便于降级和排查。
