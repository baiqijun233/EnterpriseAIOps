# 贡献指南

感谢关注 EnterpriseAIOps。提交 Issue 或 Pull Request 前，请先确认改动范围和验证方式。

## 开发环境

- Python 3.11+
- Docker Desktop（需要验证 Compose 或外部基础设施时）
- Windows 使用 PowerShell 7；Linux/macOS 使用等价终端命令

## 提交前检查

```powershell
python -m unittest discover -s 06_Tests -p 'test_*.py'
python -m compileall -q 02_Source 06_Tests
git diff --check
```

涉及 API、编排、存储、事件总线或安全策略的改动，请同时补充回归测试和文档说明。不要提交 `.env`、API Key、数据库文件、运行日志或外部服务凭证。

## 提交规范

- 一个提交聚焦一个主题。
- 描述中写清行为变化、验证命令和已知限制。
- 不要把参考资料中的示例数字写成真实生产结果。
