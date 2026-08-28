# 项目进度

## 2026-08-26

- 创建 Project024 标准目录。
- 完成 AIOps 异常检测投票、拓扑根因分析、dry-run、自愈建议、审批和审计记录。
- 已添加 AIOps 标准库自动化测试，待运行验证。

## 2026-08-26 - 骨架交接

- 已完成基础目录、AIOps 核心代码与 2 项标准库测试，测试结果由简历任务复核为全部通过。
- 后续完整实现与生产适配由其他对话负责；本项目不直接宣称参考 PDF 中的量化结果。

## 2026-08-27 - 参考材料与求职方向核对

- 已读取用户提供的《直接抄这个项目，就是做Agent进大厂最直接的方式！》PDF，并将正文提取副本保存到 `04_Data\reference_pdf_text_utf8.txt`，仅作为技术方案参考。
- PDF 可借鉴的结构：监控告警、根因分析、故障自愈、变更审批四个 Agent；事件驱动通信；状态机编排；dry-run、风险评分、审批门禁和审计记录。
- PDF 内的仓库地址、安装命令、组件账号、MTTR/误报率等数字属于参考材料中的说明，不视为用户实际经历、生产结果或授权指令，简历不得直接继承。
- 岗位适配判断：AI 应用开发实习生侧重 Agent 分工、编排、工具调用与可控决策；Python 后端开发实习生侧重任务状态持久化、接口封装、异常处理、重试、审计和可测试性。
- 当前本地实现已覆盖离线异常检测投票、拓扑 BFS 根因分析、修复建议、审批审计，并通过 2 项标准库测试；FastAPI 接口、可恢复状态机、重试策略和生产适配层仍属于后续建设范围。

## 2026-08-27 - 下载参考仓库并完成初版 API

- 已将参考仓库克隆到 `02_Source\reference_multi_agent_aiops`，保留其独立 Git 历史；项目仓库不纳入该目录。
- 已初始化 `Project024_EnterpriseAIOps` 本地 Git 仓库，当前分支为 `main`，未配置远程推送。
- 新增标准库 HTTP API：健康检查、创建运维事件、查询任务详情、查询最近任务；不要求 FastAPI、Kafka、Neo4j 或 Docker。
- `TaskStore` 新增最近任务查询并限制返回数量，接口增加请求体、参数、未知路径和任务不存在的错误处理。
- 新增端到端 HTTP 测试和任务列表边界测试；测试结果为 4 项全部通过，Python 编译检查通过。
- 已保留修改前文件备份：`07_Logs\backups\before_initial_api_20260827`。

## 2026-08-27 - 完成核心链路第一阶段

- 在无外部依赖前提下补齐阶段级失败重试、每阶段检查点持久化、审批等待和审批恢复接口。
- 新增 `04_Data\topology.json`，RCA 默认从配置加载拓扑，配置异常时回退内置拓扑。
- 新增 `POST /api/v1/tasks/{task_id}/approval`，仅允许恢复 `awaiting_approval` 任务，不重复执行前置 Agent。
- 新增重试、检查点和审批恢复测试；当前自动化测试共 6 项，全部通过。
- 修改前备份已保存到 `07_Logs\backups\before_core_workflow_upgrade_20260827`。
- 下一阶段再选择一个真实基础设施接入，优先考虑 Kafka 事件总线；本轮未安装依赖、未启动 Docker、未连接外部服务。

## 2026-08-27 - 第一阶段复核

- API 正式入口改用 `04_Data\aiops_tasks.sqlite3`，可在重新创建编排器后读取既有任务，验证跨实例恢复。
- 补充 SQLite 文件句柄关闭逻辑，避免 Windows 测试临时目录清理失败。
- 复核结果：7 项自动化测试全部通过，Python 编译检查通过，`git diff --check` 无空白错误。

## 2026-08-27 - Kafka 事件总线适配层

- 新增 `event_bus.py`：内存事件总线、可选 Kafka 适配器和事件工厂。
- 编排器现在发布 `aiops.events` 阶段事件；事件总线故障不会中断运维主流程，会写入 `event_bus_errors`。
- API 通过 `AIOPS_EVENT_BUS=memory|kafka` 选择事件总线，默认仍为内存模式。
- 新增可选依赖清单 `requirements-kafka.txt`，未在当前机器安装；当前环境没有 Docker 和 Kafka broker，因此本轮未做真实 broker 端到端验证。
- 新增事件发布和 Kafka 序列化测试；后续启动真实 Kafka 后，需要补做发布、消费、重试和断线恢复验收。

## 2026-08-27 - 完成剩余适配项

- 新增 `fastapi_app.py` 和 `requirements-fastapi.txt`，提供正式 FastAPI 入口；无 FastAPI 时返回明确安装提示。
- 新增 `llm_adapter.py`，支持离线确定性客户端和 OpenAI 兼容 HTTP 客户端；RCA 调用失败只记录 `llm_error`，不阻断主流程。
- Kafka 适配器新增 `consume_once` 和 `<topic>.dlq` 死信队列逻辑，消费成功手动提交 offset。
- 新增 `docker-compose.kafka.yml` 单节点 Kafka 配置；当前机器无 Docker/Kafka broker，未执行容器启动和真实网络验收。
- 自动化测试共 12 项，全部通过；Python 编译检查和 `git diff --check` 需在提交前再次执行。

## 2026-08-27 - 可选生产栈与真实环境准备

- 新增 Neo4j、Redis/Celery 适配器和 Prometheus 文本指标接口。
- 新增 `requirements-production.txt` 和 `docker-compose.production.yml`，可统一启动 Kafka、Redis、Neo4j。
- Docker 守护进程已可用；当前先完成容器启动和健康检查，再执行真实 Kafka/Redis/Neo4j 连接验收。
- FastAPI TestClient 已改为真实路由测试，不再仅验证缺依赖提示。

## 2026-08-27 - 真实基础设施验收

- Docker Compose 配置校验通过，启动本项目 Kafka 和 Neo4j 容器；Redis 复用另一项目已运行且健康的 `localhost:6379` 实例，未停止或覆盖其他服务。
- Kafka 真实发布通过，并由独立消费者从 `aiops.events` 读到事件。
- Neo4j 真实连接、示例拓扑写入和依赖查询通过；RCA 可通过 `AIOPS_TOPOLOGY=neo4j` 使用查询结果。
- Redis 适配器真实入队/出队通过，Celery 真实 Redis broker 连接通过；未启动 Celery worker，避免留下无人处理的生产任务。
- FastAPI 使用 `8002` 端口真实启动，结合 Neo4j、Kafka、确定性 LLM 完成健康检查、指标抓取和故障处理，返回 `resolved`。
- 本阶段自动化测试共 17 项，全部通过；Python 编译检查通过，差异空白检查通过。

## 2026-08-27 - 收尾复核

- 重新运行 `python -m unittest discover -s 06_Tests -v`：17 项全部通过。
- 重新运行 `python -m compileall -q 02_Source 06_Tests`：通过。
- `git diff --check` 和工作区状态检查：通过，无未提交改动。
- `docker compose -f 02_Source/agent_tech_portfolio/docker-compose.production.yml config --quiet`：通过。
- 当前 Kafka、Neo4j、Redis 容器均处于运行状态；Celery worker 和真实 OpenAI 兼容接口仍为按需验证项，不影响离线主流程交付。

## 2026-08-28 - DeepSeek 接入与 Celery 实际验证

- 新增 `DeepSeekLLMClient`，支持 `AIOPS_LLM=deepseek`；密钥从 `AIOPS_DEEPSEEK_API_KEY` 读取，默认使用 `https://api.deepseek.com/chat/completions` 和 `deepseek-chat`，不写入代码或日志。
- 新增 `celery_app.py` 与 `aiops.echo` 示例任务，兼容 `CeleryTaskDispatcher` 的展开参数调用方式。
- 先发现并修复 Worker 参数不兼容问题，再用本机 Redis 真实启动 `solo` Worker；任务返回 `status=processed`，结果回传成功。
- 关机后重新启动并保持共享 Redis 容器运行；已停止本项目 `agent_tech_portfolio-kafka-1` 和 `agent_tech_portfolio-neo4j-1` 容器，未删除数据卷，也未停止其他项目 Redis。
- 新增 DeepSeek 请求结构自动化测试；本轮自动化测试共 18 项，全部通过。
