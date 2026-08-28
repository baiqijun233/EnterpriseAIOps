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

## 2026-08-28 - DeepSeek 真实 API 验证

- 从用户提供的本地密钥文件临时读取密钥，仅注入当前测试进程环境变量，未写入代码、日志或 Git。
- 使用 `AIOPS_LLM=deepseek` 调用 DeepSeek `deepseek-chat`，完整处理一条高 CPU 告警。
- 验证结果：任务状态 `resolved`，阶段依次为 `monitor`、`rca`、`heal`、`change`；RCA 已生成 DeepSeek 解释，未出现 `llm_error`。
- 测试结束后已清除当前 PowerShell 进程中的密钥环境变量；密钥文件未复制、未改动。

## 2026-08-28 - 独立运行自查与修复

- 发现并修复标准库 API 对 JSON 数组请求可能返回 500 的问题；补充 400 边界测试。
- 发现并修复 FastAPI 指标每次重置、应用资源未统一释放的问题；改为应用级指标和生命周期关闭。
- 审批恢复增加同一进程内并发锁，重复审批只允许一次成功。
- Celery 新增真实 `aiops.handle_incident` 任务，复用正式 API 的 SQLite、拓扑、事件总线和 LLM 配置。
- 新增 `.env.example`、`verify.ps1`、`start_worker.ps1` 和项目级 `05_Docs\运行手册.md`，降低对人工讲解和当前工作目录的依赖。
- 真实验证：从任意工作目录启动 Worker，完整异步任务返回 `resolved`，事件阶段为 `monitor,rca,heal,change`。
- 自查后自动化测试共 22 项全部通过，编译检查、差异检查和一键验证脚本均通过。
- 已知生产边界：缺少认证/授权/限流；审批锁尚未覆盖多进程；健康检查暂为存活检查；真实 LLM、Kafka、Neo4j 的可用性需要单独探针和告警。
- 复核追加修复：标准库 HTTP 服务改为每个服务实例独立编排器，并在 `server_close()` 统一释放 SQLite、事件总线和拓扑资源，避免多实例共享状态或句柄残留。
- 追加验证：22 项测试、一键验证脚本、Python 编译检查和 Git 差异检查全部通过。
- 启动脚本改为按自身路径设置绝对源码目录；补充 `start_api.ps1`，并明确 `.env.example` 仅为变量参考，不会被程序自动加载。
- 曾尝试从任意目录启动标准 API 做真实请求验收，但本机安全策略拦截了包含进程扫描清理的测试命令；未影响已通过的 22 项路由和编排器测试，也未留下由该命令启动的服务。

## 2026-08-28 - 企业 API 优先使用 DeepSeek

- `AIOPS_LLM` 默认策略改为 `auto`：检测到 `AIOPS_DEEPSEEK_API_KEY` 时自动选择 DeepSeek；未配置密钥时自动回退到离线模式。
- 显式设置 `none`、`deterministic`、`deepseek` 或 `openai` 时仍按用户配置执行，不改变审批、审计和失败降级逻辑。
- `.env.example`、README 和运行手册已同步；新增自动选择和无密钥回退测试。
- 本轮自动化测试共 24 项全部通过，编译、差异和一键验证均通过。
- 使用用户提供的本地密钥做真实自动模式验证：未设置 `AIOPS_LLM` 时成功自动选择 DeepSeek，任务返回 `resolved`，生成 RCA 解释且无 `llm_error`；测试后已清除进程环境变量，未记录密钥内容。

## 2026-08-29 - 安全护栏与跨进程幂等审批

- 按参考文档的主要安全链路，新增单服务滑动窗口限流、dry-run 检查、20% 爆炸半径阈值、单服务熔断与半开探测。
- 安全护栏不通过时任务进入 `awaiting_approval`，保留人工复核通道；审批事件仍保留审计编号。
- `TaskStore.save_if_status` 使用 SQLite `UPDATE ... WHERE status = ?` 条件更新，两个独立数据库连接同时审批时只允许一个成功。
- 本轮不添加 Kubernetes 和 RBAC：当前为本地/演示部署，两者对真实性和求职展示的收益低于安全护栏与幂等性。如需公网部署，再优先补认证授权。
- 新增 6 项安全与多实例测试，当前自动化测试共 30 项。
