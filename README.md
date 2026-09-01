<div align="center">

# EnterpriseAIOps

### 面向企业后端的事件驱动智能运维服务

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](02_Source/agent_tech_portfolio/requirements-fastapi.txt)
[![CI](https://github.com/baiqijun233/EnterpriseAIOps/actions/workflows/ci.yml/badge.svg)](https://github.com/baiqijun233/EnterpriseAIOps/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](02_Source/agent_tech_portfolio/docker-compose.production.yml)
[![Tests](https://img.shields.io/badge/tests-unittest-2ea44f)](06_Tests)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**告警接入 → 异常确认 → 根因分析 → 审批与安全修复**

</div>

EnterpriseAIOps 将异常检测、拓扑分析、修复建议和变更审批串成可恢复的任务链路，适合云原生服务、内部平台和后端系统的运维自动化。默认使用离线数据和 dry-run 执行，便于在接入真实基础设施前验证流程与安全边界。

## 项目预览

![接口文档](03_Assets/screenshots/enterprise-aiops-swagger.png)
![就绪检查](03_Assets/screenshots/ready-response.png)
![运行验收摘要](03_Assets/screenshots/verification-report.png)

## 核心能力

- 3-Sigma、EWMA、Isolation Forest 投票式异常检测。
- 基于服务拓扑的 BFS 根因分析，可选接入检索或模型解释。
- 任务状态、检查点、幂等审批和 SQLite/PostgreSQL 存储。
- 内存事件总线或 Kafka，Celery + Redis 异步任务队列。
- 限流、熔断、爆炸半径、角色权限、审计和 dry-run 安全护栏。
- FastAPI 接口、Worker 就绪探针、Prometheus 指标和 Docker Compose。

## 运行架构

```text
告警 → Monitor → RCA → Heal → Change（审批） → Repair Executor
                                  ├→ 事件总线（内存或 Kafka）
                                  └→ 任务存储（SQLite 或 PostgreSQL）
```

## 快速开始

环境要求：Python 3.11+；容器运行需要 Docker Desktop 或 Docker Engine。

```powershell
python -m unittest discover -s 06_Tests -p 'test_*.py'
& .\02_Source\agent_tech_portfolio\start_api.ps1
```

另开终端检查接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

容器方式：

```powershell
docker compose -f .\02_Source\agent_tech_portfolio\docker-compose.production.yml up -d --build
Invoke-RestMethod http://127.0.0.1:18024/health
```

## 常用接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/health` | 进程存活检查 |
| GET | `/ready` | 存储、事件总线和执行器就绪检查 |
| POST | `/api/v1/incidents` | 提交运维告警 |
| GET | `/api/v1/tasks/{task_id}` | 查询任务详情 |
| POST | `/api/v1/tasks/{task_id}/approval` | 恢复审批任务 |
| GET | `/metrics` | Prometheus 指标 |

## 配置与安全边界

配置只通过环境变量注入，例如 `AIOPS_LLM`、`AIOPS_STORAGE`、`AIOPS_EVENT_BUS` 和 `AIOPS_REPAIR_EXECUTOR`。默认执行策略为 dry-run；allowlist 模式只接受显式参数列表并禁用任意 shell 字符串。外部模型、数据库、Kafka、Neo4j、Qdrant 等服务均为可选适配器，凭证不会写入仓库。

## 测试与验证

```powershell
python -m unittest discover -s 06_Tests -p 'test_*.py'
python -m compileall -q 02_Source 06_Tests
& .\02_Source\agent_tech_portfolio\verify.ps1
```

## 项目结构

```text
02_Source/agent_tech_portfolio/
├─ aiops_agent.py          任务编排与安全策略
├─ api_server.py           HTTP API 入口
├─ adapters/               Redis、Neo4j、队列等适配器
├─ common/                 存储和公共组件
├─ start_*.ps1             API/Worker 启动脚本
├─ Dockerfile              容器构建文件
└─ docker-compose*.yml     本地与生产拓扑模板
```

## 实现范围与第三方组件

维护者主导流程设计、Agent 编排、故障安全策略、接口、测试和部署配置。Celery、Redis、Kafka、PostgreSQL、Neo4j、Qdrant 及兼容模型服务通过适配层接入，便于按目标环境替换。

## 当前边界与路线图

当前版本可在离线模式和单机容器中验证完整流程；正式部署还需要企业数据库与消息集群、TLS/反向代理、集中式密钥管理、监控告警、变更平台回滚接口和压测数据。后续将完善全链路观测、CMDB 接口和灰度发布策略。

## 贡献、许可证与安全

欢迎通过 Issue 或 Pull Request 参与。提交前请运行测试并移除运行数据、密钥和本机路径。本项目使用 [MIT License](LICENSE)，安全问题请按 [SECURITY.md](SECURITY.md) 联系维护者。
