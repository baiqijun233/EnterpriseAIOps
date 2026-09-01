# 企业级多 Agent 智能运维系统

本项目展示异常检测投票（3-Sigma、EWMA、Isolation Forest）、拓扑 BFS 根因分析、故障自愈建议、dry-run、限流、爆炸半径、熔断、风险审批和审计记录，并提供一个不依赖第三方库的本地 HTTP API 初版。

当前核心链路支持阶段级重试、SQLite 检查点保存、等待审批后恢复，以及从 `04_Data\topology.json` 加载服务拓扑。审批恢复使用 SQLite 条件更新，同一任务在多个 API 进程中也只能成功审批一次。API 重启后可继续查询已保存任务。

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
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/incidents -ContentType "application/json" -Body '{"service":"order-service","metric":"cpu","value":95,"baseline":[40,41,39,42,40]}'
Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks
# 对处于 awaiting_approval 的任务进行人工审批
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/tasks/<task_id>/approval -ContentType "application/json" -Body '{"approved":true}'
```

API Key 认证默认关闭，便于仅本机访问的离线演示。公网或共享环境必须启用认证：

```powershell
$keyBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($keyBytes)
$apiKey = [Convert]::ToBase64String($keyBytes)
$env:AIOPS_AUTH_ENABLED = "true"
$env:AIOPS_API_KEYS = ConvertTo-Json @{$apiKey = "admin"} -Compress
& ".\02_Source\agent_tech_portfolio\start_api.ps1"
```

调用受保护接口时通过 `X-API-Key` 请求头传递：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/tasks -Headers @{"X-API-Key" = $apiKey}
```

角色权限按等级继承：`viewer` 可查看任务，`operator` 可额外提交告警，`approver` 可额外人工审批，`admin` 拥有全部权限。`/health`、`/ready` 和 `/metrics` 保持公开，便于存活检查、就绪检查和 Prometheus 抓取。密钥至少 16 位，只从环境变量读取，不会写入日志和接口响应；审批审计只保留角色和不可逆的 12 位 Key 指纹。

`GET /health` 只表示 API 进程存活。`GET /ready` 实际执行 SQLite 只读查询，并对当前启用的 Kafka 读取元数据、对 Neo4j 验证连通性；结果缓存 5 秒。必需依赖失败时返回 HTTP 503 和结构化的 `checks`。LLM 只检查本地配置，不在就绪探针中调用生成接口，避免产生费用。

参考仓库保存在上级项目的 `02_Source\reference_multi_agent_aiops`，仅用于对照架构；项目仓库通过 `.gitignore` 忽略其内容，参考仓库自身保留独立 Git 历史。

Kafka 模式（需要已运行的 Kafka broker）：

```powershell
python -m pip install -r 02_Source\agent_tech_portfolio\requirements-kafka.txt
$env:AIOPS_EVENT_BUS = "kafka"
$env:AIOPS_KAFKA_BOOTSTRAP = "localhost:29092"
$env:PYTHONPATH = "02_Source\agent_tech_portfolio"
python -m api_server
```

项目提供 `docker-compose.kafka.yml` 作为单节点 Kafka 启动配置，也提供 `docker-compose.production.yml` 启动 Kafka、Redis、Neo4j。启动后可将 `AIOPS_EVENT_BUS` 设置为 `kafka`；事件按 `aiops.alerts`、`aiops.events`、`aiops.commands`、`aiops.audit` 分主题，消费失败消息进入对应 `.dlq`。

生产适配依赖可统一安装：

```powershell
python -m pip install -r 02_Source\agent_tech_portfolio\requirements-production.txt
```

生产 Compose 还提供 PostgreSQL 和 Qdrant。默认仍使用 SQLite、内存事件总线和本地 RAG；上线前只需设置 `AIOPS_STORAGE=postgres`、`AIOPS_EVENT_BUS=kafka`、`AIOPS_RAG=qdrant` 及对应地址。容器内部地址分别为 `postgres:5432`、`kafka:9092`、`qdrant:6333`，宿主机默认映射为 PostgreSQL `15433`、Kafka `29092`、Qdrant `16333`，均可通过 `AIOPS_POSTGRES_PORT`、`AIOPS_KAFKA_PORT`、`AIOPS_QDRANT_PORT` 调整。

Prometheus 可抓取 `GET /metrics`，无需额外修改核心流程。

Neo4j 拓扑模式：设置 `AIOPS_TOPOLOGY=neo4j`，并配置 `AIOPS_NEO4J_URI`、`AIOPS_NEO4J_USER`、`AIOPS_NEO4J_PASSWORD`；RCA 会直接查询服务依赖关系。

Redis/Celery 适配器位于 `adapters\task_queue.py`，用于异步任务入队和分发；需要独立启动 Celery Worker 才会实际消费任务。项目提供 `celery_app.py` 的 `aiops.echo` 示例任务，可按下面命令启动 Worker：

```powershell
$env:AIOPS_CELERY_BROKER = "redis://localhost:6379/0"
& ".\start_worker.ps1"
```

也可以在源码目录手动执行 `celery -A celery_app:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO`；脚本会自动设置绝对源码路径，因此不依赖当前工作目录。

Windows 本地验证建议使用 `--pool=solo`；停止 Worker 在终端按 `Ctrl+C` 即可。Worker 只消费已注册任务，未知任务会被记录为失败，不会自动执行任意代码。

检查 Worker 是否真正注册了本项目的 `aiops.handle_incident` 任务：

```powershell
& ".\02_Source\agent_tech_portfolio\check_worker.ps1"
```

就绪时退出码为 0，未就绪为 1。该检查会过滤同一 Broker 上其他项目的 Worker，不会因为“任意 Worker 能 ping 通”就误报成功。

提交一条真实 AIOps 异步任务（需要 Worker 正在运行）：

```powershell
$env:PYTHONPATH = (Get-Location).Path
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

真实修复执行器默认关闭。`AIOPS_REPAIR_EXECUTOR=dry-run` 只记录意图；显式设置 `allowlist` 后，通过 `AIOPS_REPAIR_COMMANDS` 配置 `restart`/`rollback` 参数列表，执行阶段会记录 `executing`、`resolved` 或 `execution_failed`，并在失败时触发熔断。命令始终以参数列表运行，不经过 shell。

RCA 在告警包含 `recent_deploy` 证据时会计算贝叶斯后验置信度，并在结果中标记 `confidence_method=bayesian`；缺少先验数据时使用拓扑启发式基线。可运行 `python 06_Tests/run_local_benchmark.py` 生成固定种子的检测基准报告到 `07_Logs`。

项目提供 `Dockerfile` 和生产 Compose 中的 `api`、`worker` 服务。Compose 构建上下文为项目根目录，API 使用 FastAPI，Worker 使用 Celery `solo` 池，SQLite 数据保存在 `aiops_app_data` 命名卷。默认事件总线、拓扑和修复执行器仍为离线安全模式。

自动修复安全护栏按以下顺序执行：单服务滑动窗口限流 → dry-run 预演检查 → 爆炸半径检查 → 单服务熔断检查 → 变更审批。默认每个服务 60 秒最多 5 次自动修复建议，爆炸半径不超过 20%；被护栏拦截的任务会进入 `awaiting_approval`，不会被当成已执行修复。

熔断器提供 `record_failure(service)` 和 `record_success(service)`，供真实修复执行器回写结果。当前项目只输出 dry-run 建议，不会伪造真实变更成功或失败。

默认 `AIOPS_SAFETY_BACKEND=memory`，适合单进程离线演示。多 API 实例可改为 Redis 共享状态：

```powershell
$env:AIOPS_SAFETY_BACKEND = "redis"
$env:AIOPS_SAFETY_REDIS_URL = "redis://localhost:6379/0"
$env:AIOPS_SAFETY_KEY_PREFIX = "project024:aiops:safety"
& ".\02_Source\agent_tech_portfolio\start_api.ps1"
```

Redis 后端使用 Lua 将限流和熔断的“检查+更新”合并为单次原子操作，默认 Key 位于 `project024:aiops:safety:*` 命名空间，可通过 `AIOPS_SAFETY_KEY_PREFIX` 调整。`/ready` 会对该 Redis 执行 `PING`；Redis 不可用时 API 返回 503 就绪失败。
