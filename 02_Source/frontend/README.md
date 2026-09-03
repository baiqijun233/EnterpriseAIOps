# 运维指挥中心前端

这是一个无构建步骤的静态运维控制台，直接使用项目现有 API。默认加载演示数据，适合快速查看界面和交互。

## 本地运行

在 PowerShell 中执行：

```powershell
python -m http.server 4173 --directory .\02_Source\frontend
```

浏览器打开 `http://127.0.0.1:4173/`。

## 接入 API

页面启动时读取 `localStorage` 中的 `aiops-api-base`，例如：

```js
localStorage.setItem("aiops-api-base", "https://ops.example.com")
```

生产环境建议通过同域反向代理转发 `/api`、`/health` 和 `/ready`，避免为静态页面开放宽泛的跨域策略。清除该值即可回到演示模式。

## 页面能力

- 任务流按全部、待审批、已完成筛选。
- 支持风险筛选、展开/收起全部任务、任务详情提示和导航锚点定位。
- 支持外观切换、工作区切换、个人资料提示、服务拓扑定位和运行手册入口。
- 提交告警弹窗，字段校验后调用 `POST /api/v1/incidents`。
- 任务列表调用 `GET /api/v1/tasks?limit=50`，兼容项目当前 `state.alert` 数据结构。
- API 不可用时保留本地演示数据并显示提示，不会静默伪装成已接入。
