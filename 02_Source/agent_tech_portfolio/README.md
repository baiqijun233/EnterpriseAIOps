# EnterpriseAIOps 源码

这里是 EnterpriseAIOps 的 API、任务编排、适配器和 Worker 实现。默认配置使用 SQLite、内存事件总线、JSON 拓扑和 dry-run 执行，方便先验证流程，再接入企业基础设施。

## 运行

在仓库根目录执行：

```powershell
python -m unittest discover -s 06_Tests -p 'test_*.py'
& .\02_Source\agent_tech_portfolio\start_api.ps1
```

容器方式：

```powershell
docker compose -f .\02_Source\agent_tech_portfolio\docker-compose.production.yml up -d --build
```

API 默认提供 `/health`、`/ready`、`/metrics`、`/api/v1/incidents` 和任务查询接口。

## 模块

- `aiops_agent.py`：检测、根因分析、修复建议和审批状态。
- `api_server.py`：HTTP API 与请求校验。
- `adapters/`：Redis 安全状态、Celery 队列和 Neo4j 拓扑适配器。
- `common/`：任务存储和公共数据结构。
- `start_api.ps1`、`start_worker.ps1`：本机启动入口。

## 配置

配置通过环境变量注入。常用项为 `AIOPS_LLM`、`AIOPS_STORAGE`、`AIOPS_EVENT_BUS`、`AIOPS_TOPOLOGY`、`AIOPS_RAG` 和 `AIOPS_REPAIR_EXECUTOR`。模型、数据库、消息队列和拓扑服务的凭证不会写入代码或日志。

修复执行默认是 dry-run；启用 allowlist 时只接受参数列表，不执行任意 shell 字符串。外部模型不可用时，系统会回退到确定性分析。

## 验证

```powershell
python -m unittest discover -s 06_Tests -p 'test_*.py'
python -m compileall -q 02_Source 06_Tests
& .\02_Source\agent_tech_portfolio\verify.ps1
```
