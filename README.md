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

EnterpriseAIOps 将监控告警、异常检测、拓扑分析、修复建议和变更审批串成可恢复的任务链路，适合云原生服务、内部平台和企业后端系统。默认使用离线数据和 dry-run 执行，先验证流程与安全边界，再接入真实基础设施。

<details>
<summary>快速导航</summary>

[项目预览](#项目预览) · [核心能力](#核心能力) · [运行架构](#运行架构) · [快速开始](#快速开始) · [接口](#常用接口) · [配置](#配置与安全边界) · [测试](#测试与验证) · [路线图](#当前边界与路线图)

</details>

## 项目预览

![API 文档](03_Assets/screenshots/enterprise-aiops-swagger.png)
![就绪检查](03_Assets/screenshots/ready-response.png)
![运行验收摘要](03_Assets/screenshots/verification-report.png)

图片来自本地 API 和容器链路，展示接口、就绪探针和验收结果，不包含凭证或内部地址。

## 核心能力

| 模块 | 已实现能力 | 默认模式 |
| --- | --- | --- |
| Agent 编排 | Monitor、RCA、Heal、Change 四阶段任务链路 | 本地同步 |
| 异常检测 | 3-Sigma、EWMA、Isolation Forest 投票 | 标准库 |
| 根因分析 | 拓扑 BFS、置信度计算、可选检索/模型解释 | JSON 拓扑 |
| 状态与事件 | 检查点、幂等审批、内存总线或 Kafka | SQLite / 内存 |
| 安全治理 | 限流、熔断、爆炸半径、角色权限、审计 | dry-run |
| 异步与运维 | Celery、Redis、健康/就绪探针、Prometheus 指标 | 按需启用 |

## 运行架构

```mermaid
flowchart LR
    A[告警输入] --> B[Monitor\n异常确认]
    B --> C[RCA\n拓扑根因]
    C --> D[Heal\n动作建议]
    D --> E[Change\n风险审批]
    E --> F[Repair Executor\ndry-run / allowlist]
    B -.事件.-> G[(内存总线或 Kafka)]
    F -.状态.-> H[(SQLite 或 PostgreSQL)]
```

## 快速开始

环境要求：Python 3.11+；容器运行需要 Docker Desktop 或 Docker Engine。

```powershell
python -m unittest discover -s 06_Tests -p 'test_*.py'
& .\02_Source\agent_tech_portfolio\start_api.ps1
```

另开终端检查：

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
| POST | `/api/v1/incidents` | 提交一条运维告警 |
| GET | `/api/v1/tasks` | 查询最近任务 |
| GET | `/api/v1/tasks/{task_id}` | 查询任务详情 |
| POST | `/api/v1/tasks/{task_id}/approval` | 恢复等待审批的任务 |
| GET | `/metrics` | Prometheus 文本指标 |

## 配置与安全边界

配置通过环境变量注入，常用项包括 `AIOPS_LLM`、`AIOPS_STORAGE`、`AIOPS_EVENT_BUS`、`AIOPS_TOPOLOGY`、`AIOPS_RAG` 和 `AIOPS_REPAIR_EXECUTOR`。外部模型、数据库、Kafka、Neo4j、Qdrant 和 Redis 的凭证不会写入仓库。

默认修复策略为 dry-run；allowlist 模式只接受显式参数列表，不执行任意 shell 字符串。模型不可用时会回退到离线分析，外部消息总线不可用时会记录错误并保留任务状态。

## 测试与验证

```powershell
python -m unittest discover -s 06_Tests -p 'test_*.py'
python -m compileall -q 02_Source 06_Tests
docker compose -f .\02_Source\agent_tech_portfolio\docker-compose.production.yml config
& .\02_Source\agent_tech_portfolio\verify.ps1
```

当前本地基线为 52 项测试通过，覆盖检测、RCA、审批、存储、异步 Worker 和安全护栏。

## 项目结构

```text
02_Source/agent_tech_portfolio/
├─ aiops_agent.py          任务编排与安全策略
├─ api_server.py           HTTP API 入口
├─ adapters/               Redis、Neo4j、队列等适配器
├─ common/                 存储和公共组件
├─ start_*.ps1             API/Worker 启动脚本
├─ Dockerfile              容器构建文件
└─ docker-compose*.yml     本地与扩展拓扑模板
```

## 实现范围与第三方组件

维护者主导流程设计、Agent 编排、故障安全策略、接口、测试和部署配置。Celery、Redis、Kafka、PostgreSQL、Neo4j、Qdrant 及兼容模型服务通过适配层接入，便于按目标环境替换。

## 当前边界与路线图

当前版本可在离线模式和单机容器中验证完整流程。正式部署还需要企业数据库与消息集群、TLS/反向代理、集中式密钥管理、监控告警、变更平台回滚接口和压测数据；后续将完善全链路观测、CMDB 接口和灰度发布策略。

## 贡献、许可证与安全

欢迎通过 Issue 或 Pull Request 参与。提交前请运行测试并移除运行数据、密钥和本机路径。本项目使用 [MIT License](LICENSE)，安全问题请按 [SECURITY.md](SECURITY.md) 联系维护者。
