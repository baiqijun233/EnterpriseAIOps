# 企业级多 Agent 智能运维系统

本项目展示异常检测投票、拓扑 BFS 根因分析、故障自愈建议、dry-run、风险审批和审计记录，并提供一个不依赖第三方库的本地 HTTP API 初版。

当前核心链路支持阶段级重试、SQLite 检查点保存、等待审批后恢复，以及从 `04_Data\topology.json` 加载服务拓扑。API 重启后可继续查询已保存任务。

默认只依赖 Python 标准库，便于离线演示。Kafka、Neo4j、Redis 和 Celery 都已提供可选适配层，未配置时仍可使用内存总线、JSON 拓扑和 SQLite。

项目附带 `.env.example` 作为变量清单，但程序不会自动加载 `.env` 文件；请按下方 PowerShell 命令设置环境变量。

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
& ".\02_Source\agent_tech_portfolio\start_api.ps1"
```

启动 FastAPI API（可选）：

```powershell
python -m pip install -r 02_Source\agent_tech_portfolio\requirements-fastapi.txt
$env:PYTHONPATH = (Resolve-Path .\02_Source\agent_tech_portfolio).Path
python -m fastapi_app
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

项目提供 `docker-compose.kafka.yml` 作为单节点 Kafka 启动配置，也提供 `docker-compose.production.yml` 启动 Kafka、Redis、Neo4j。启动后可将 `AIOPS_EVENT_BUS` 设置为 `kafka`；默认 Topic 为 `aiops.events`，消费失败消息进入 `aiops.events.dlq`。

生产适配依赖可统一安装：

```powershell
python -m pip install -r 02_Source\agent_tech_portfolio\requirements-production.txt
```

Prometheus 可抓取 `GET /metrics`，无需额外修改核心流程。

Neo4j 拓扑模式：设置 `AIOPS_TOPOLOGY=neo4j`，并配置 `AIOPS_NEO4J_URI`、`AIOPS_NEO4J_USER`、`AIOPS_NEO4J_PASSWORD`；RCA 会直接查询服务依赖关系。

Redis/Celery 适配器位于 `adapters\task_queue.py`，用于异步任务入队和分发；需要独立启动 Celery Worker 才会实际消费任务。项目提供 `celery_app.py` 的 `aiops.echo` 示例任务，可按下面命令启动 Worker：

```powershell
$env:AIOPS_CELERY_BROKER = "redis://localhost:6379/0"
& "E:\Agent\AIProjects\Project024_EnterpriseAIOps\02_Source\agent_tech_portfolio\start_worker.ps1"
```

也可以在源码目录手动执行 `celery -A celery_app:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO`；脚本会自动设置绝对源码路径，因此不依赖当前工作目录。

Windows 本地验证建议使用 `--pool=solo`；停止 Worker 在终端按 `Ctrl+C` 即可。Worker 只消费已注册任务，未知任务会被记录为失败，不会自动执行任意代码。

提交一条真实 AIOps 异步任务（需要 Worker 正在运行）：

```powershell
$sourceDir = "E:\Agent\AIProjects\Project024_EnterpriseAIOps\02_Source\agent_tech_portfolio"
$env:PYTHONPATH = $sourceDir
python -c "from celery_app import celery_app; r=celery_app.send_task('aiops.handle_incident', kwargs={'service':'order-service','metric':'cpu','value':95,'baseline':[40,41,39,42,40]}); print(r.get(timeout=30))"
```

该任务会复用正式 API 的 SQLite、拓扑、事件总线和 LLM 环境变量配置。

LLM 模式默认是 `auto`：检测到 `AIOPS_DEEPSEEK_API_KEY` 时优先使用 DeepSeek，没有密钥则自动回退到无 LLM 离线模式。也可以显式设置 `AIOPS_LLM=deterministic` 生成离线解释，或设置 `AIOPS_LLM=none` 完全关闭 LLM。

接入 DeepSeek 官方 API 时，在 PowerShell 中配置以下环境变量后启动服务：

```powershell
$env:AIOPS_LLM = "deepseek"
$env:AIOPS_DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
$env:AIOPS_DEEPSEEK_MODEL = "deepseek-chat"
$env:PYTHONPATH = (Resolve-Path .\02_Source\agent_tech_portfolio).Path
python -m api_server
```

如果不设置 `AIOPS_LLM`，只要存在 `AIOPS_DEEPSEEK_API_KEY`，企业 API 会自动优先使用 DeepSeek。

可选的 `AIOPS_DEEPSEEK_ENDPOINT` 默认是 `https://api.deepseek.com/chat/completions`。密钥只从环境变量读取，不写入仓库、日志或接口响应。也可以继续使用 OpenAI 兼容服务：设置 `AIOPS_LLM=openai`、`AIOPS_LLM_ENDPOINT`、`AIOPS_LLM_API_KEY` 和 `AIOPS_LLM_MODEL`。

Kafka 发送失败不会让主流程直接崩溃，错误会记录在任务的 `event_bus_errors` 字段，便于降级和排查。
