# 更新记录

## 2026-09-03

- 发布 v0.1.1，新增运维指挥中心前端，并通过 FastAPI /console/ 提供访问入口。
- Docker 镜像纳入前端资源，版本标签根据 Git 标签动态生成。

## 2026-08-29

- 完成四 Agent 运维编排、阶段重试、检查点和审批恢复。
- 接入 DeepSeek 自动优先、Kafka、Redis/Celery、Neo4j、PostgreSQL、Qdrant 和可观测性适配层。
- 增加 API Key 认证、角色权限、限流、熔断、爆炸半径和执行后健康检查。
- 完成 Docker API/Worker 与基础设施 Compose 验收。
- 完成 DeepSeek 真实调用、异步 Worker、API 重启恢复和 52 项自动化测试验证。
