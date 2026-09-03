(() => {
  "use strict";

  const API_BASE = (window.__AIOPS_API_BASE__ || localStorage.getItem("aiops-api-base") || "").replace(/\/$/, "");
  const demoTasks = [
    { task_id: "tsk-7f2c", service: "checkout-api", metric: "cpu_usage", severity: "high", stage: "rca", status: "awaiting_approval", duration: "02:18", summary: "节点 CPU 持续升高，等待变更审批" },
    { task_id: "tsk-6a19", service: "payment-gateway", metric: "latency_p95", severity: "medium", stage: "heal", status: "executing", duration: "01:42", summary: "检测到上游依赖延迟，正在执行限流" },
    { task_id: "tsk-4d83", service: "inventory-sync", metric: "error_rate", severity: "high", stage: "change", status: "resolved", duration: "03:06", summary: "回滚最近发布版本，健康检查通过" },
    { task_id: "tsk-3b47", service: "user-profile", metric: "request_rate", severity: "low", stage: "monitor", status: "resolved", duration: "00:56", summary: "短时流量尖峰，确认后自动恢复" },
    { task_id: "tsk-2c11", service: "search-indexer", metric: "queue_depth", severity: "medium", stage: "rca", status: "resolved", duration: "02:31", summary: "消费积压根因为下游写入抖动" },
    { task_id: "tsk-1e74", service: "notification-worker", metric: "retry_rate", severity: "medium", stage: "heal", status: "executing", duration: "01:15", summary: "重试率升高，正在调整消费并发" },
    { task_id: "tsk-0a92", service: "auth-service", metric: "latency_p99", severity: "low", stage: "monitor", status: "resolved", duration: "00:48", summary: "认证延迟短时波动，已自动恢复" }
  ];
  const agents = [
    { name: "Monitor Agent", role: "异常检测与告警确认", icon: "◒", color: "#53e1cc", load: 68, status: "运行中" },
    { name: "RCA Agent", role: "拓扑分析与根因解释", icon: "⌁", color: "#7aa9ff", load: 44, status: "运行中" },
    { name: "Heal Agent", role: "修复建议与风险评估", icon: "✦", color: "#f6c15d", load: 81, status: "处理中" },
    { name: "Change Agent", role: "审批门禁与安全执行", icon: "◇", color: "#cb9cff", load: 32, status: "运行中" }
  ];
  const services = [
    { name: "checkout-api", meta: "生产 · 12 实例", status: "健康", latency: "84ms", warn: false },
    { name: "payment-gateway", meta: "生产 · 8 实例", status: "健康", latency: "126ms", warn: false },
    { name: "inventory-sync", meta: "生产 · 6 实例", status: "需关注", latency: "438ms", warn: true },
    { name: "search-indexer", meta: "生产 · 4 实例", status: "健康", latency: "92ms", warn: false }
  ];
  const events = [
    { text: "RCA Agent 完成了 checkout-api 根因分析", time: "刚刚", warn: false },
    { text: "变更审批 #CHG-1042 进入人工复核", time: "2 分钟", warn: true },
    { text: "Heal Agent 为 payment-gateway 生成修复建议", time: "5 分钟", warn: false },
    { text: "inventory-sync 回滚完成，健康检查通过", time: "8 分钟", warn: false }
  ];

  const state = { tasks: [...demoTasks], filter: "all", severity: "all", showAll: false, connected: false, theme: localStorage.getItem("aiops-theme") || "dark" };
  const el = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const stageNames = { monitor: "Monitor", rca: "RCA 分析", heal: "Heal 修复", change: "Change 审批" };
  const statusNames = { resolved: "已完成", awaiting_approval: "待审批", executing: "执行中", execution_failed: "执行失败" };

  function normalizeTask(task) {
    const alert = task?.state?.alert || {};
    const events = Array.isArray(task?.state?.events) ? task.state.events : [];
    const stage = [...events].reverse().find((event) => event?.stage)?.stage || task?.stage || task?.current_stage || "monitor";
    return { ...task, task_id: task?.task_id || task?.id || `task-${Date.now().toString(36)}`, service: task?.service || alert.service || "未知服务", metric: task?.metric || alert.metric || "未知指标", severity: task?.severity || alert.severity || "medium", stage, status: task?.status || "executing", duration: task?.duration || "--", summary: task?.summary || task?.state?.result?.action || "任务正在处理中" };
  }

  function renderAgents() {
    el("agent-list").innerHTML = agents.map((agent) => `<div class="agent-row" style="--agent-color:${agent.color}"><div class="agent-avatar">${agent.icon}</div><div><strong class="agent-name">${agent.name}</strong><span class="agent-role">${agent.role}</span></div><span class="agent-status ${agent.status === "处理中" ? "busy" : ""}">${agent.status}</span><div class="agent-bar"><i style="width:${agent.load}%"></i></div></div>`).join("");
  }

  function renderServices() {
    el("service-list").innerHTML = services.map((service) => `<div class="service-row"><div><strong class="service-name">${service.name}</strong><span class="service-meta">${service.meta}</span></div><span class="service-health ${service.warn ? "warn" : ""}"><i></i>${service.status}</span><span class="service-latency">${service.latency}</span></div>`).join("");
  }

  function renderEvents() {
    el("event-list").innerHTML = events.map((event) => `<div class="event-row"><i class="event-marker ${event.warn ? "warn" : ""}"></i><span class="event-copy">${escapeHtml(event.text)}</span><time class="event-time">${event.time}</time></div>`).join("");
  }

  function visibleTasks() {
    return state.tasks.filter((task) => (state.filter === "all" || task.status === state.filter) && (state.severity === "all" || task.severity === state.severity));
  }

  function renderTasks() {
    const visible = visibleTasks();
    const displayed = state.showAll ? visible : visible.slice(0, 5);
    el("task-list").innerHTML = displayed.map((task) => `<tr data-task-id="${escapeHtml(task.task_id)}"><td><div class="task-main"><i class="task-severity ${escapeHtml(task.severity)}"></i><div><strong class="task-name">${escapeHtml(task.task_id)}</strong><span class="task-service">${escapeHtml(task.service)} · ${escapeHtml(task.metric)}</span></div></div></td><td><span class="stage ${escapeHtml(task.stage)}"><i></i>${escapeHtml(stageNames[task.stage] || task.stage)}</span></td><td>${escapeHtml(task.severity === "high" ? "高" : task.severity === "medium" ? "中" : "低")}</td><td>${escapeHtml(task.duration || "--")}</td><td><span class="state ${escapeHtml(task.status)}">${escapeHtml(statusNames[task.status] || task.status)}</span></td><td><button class="row-action" type="button" aria-label="查看任务详情" title="查看任务详情">→</button></td></tr>`).join("");
    el("task-total").textContent = state.tasks.length;
    el("task-pending").textContent = state.tasks.filter((task) => task.status === "awaiting_approval").length;
    el("task-summary").textContent = state.showAll ? `显示全部 ${visible.length} 条任务` : `显示最近 ${Math.min(visible.length, 5)} 条任务`;
    el("load-more").innerHTML = state.showAll ? "收起任务 <span>↑</span>" : "查看全部任务 <span>→</span>";
    el("load-more").hidden = visible.length <= 5;
    el("metric-active").textContent = state.tasks.filter((task) => task.status !== "resolved").length + 10;
    el("metric-approval").textContent = state.tasks.filter((task) => task.status === "awaiting_approval").length;
    document.querySelectorAll(".row-action").forEach((button) => button.addEventListener("click", () => showTask(button.closest("tr").dataset.taskId)));
  }

  function showTask(taskId) {
    const task = state.tasks.find((item) => item.task_id === taskId);
    if (!task) return;
    const action = task.status === "awaiting_approval" ? "\n\n该任务等待审批，可在 API 接入后从任务详情执行审批。" : "";
    showToast(`${task.task_id} · ${task.summary || statusNames[task.status]}${action}`);
  }

  async function loadTasks() {
    if (!API_BASE) return;
    try {
      const response = await fetch(`${API_BASE}/api/v1/tasks?limit=50`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.tasks)) throw new Error("tasks 字段格式无效");
      state.tasks = data.tasks.map(normalizeTask);
      state.connected = true;
      el("api-label").textContent = "API 已连接";
      document.querySelector(".api-status")?.classList.add("connected");
      renderTasks();
      updateSyncTime();
    } catch (error) {
      state.connected = false;
      el("api-label").textContent = "演示数据";
      showToast("API 暂不可用，已保留演示数据");
    }
  }

  function updateSyncTime() {
    const now = new Date();
    const time = now.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    el("last-sync").textContent = time;
    el("sidebar-sync").textContent = `${time} 同步`;
  }

  function showToast(message) {
    const toast = el("toast");
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => toast.classList.remove("show"), 3600);
  }

  function setMenu(menu, trigger, open) {
    if (!menu || !trigger) return;
    menu.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
  }

  function closeMenus() {
    setMenu(el("workspace-menu"), el("workspace-button"), false);
    setMenu(el("filter-menu"), el("more-filters"), false);
  }

  function applyTheme(theme) {
    state.theme = theme === "light" ? "light" : "dark";
    document.body.dataset.theme = state.theme;
    localStorage.setItem("aiops-theme", state.theme);
    const button = el("theme-button");
    if (button) {
      const icon = button.querySelector("span");
      if (icon) icon.textContent = state.theme === "dark" ? "◐" : "☼";
      button.setAttribute("aria-label", state.theme === "dark" ? "切换为浅色外观" : "切换为深色外观");
      button.title = button.getAttribute("aria-label");
    }
  }

  function focusSection(id, message) {
    const target = el(id);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    target.classList.add("section-focused");
    setTimeout(() => target.classList.remove("section-focused"), 900);
    showToast(message);
  }

  function openModal() { el("incident-modal").hidden = false; document.body.style.overflow = "hidden"; el("incident-modal").querySelector("input")?.focus(); }
  function closeModal() { el("incident-modal").hidden = true; document.body.style.overflow = ""; }

  async function submitIncident(event) {
    event.preventDefault();
    const form = new FormData(event.target);
    const baseline = String(form.get("baseline") || "").split(",").map((item) => Number(item.trim())).filter((item) => Number.isFinite(item));
    const payload = { service: String(form.get("service") || "").trim(), metric: String(form.get("metric") || "").trim(), value: Number(form.get("value")), severity: form.get("severity"), baseline };
    if (!payload.service || !payload.metric || !Number.isFinite(payload.value)) { showToast("请补全服务、指标和当前值"); return; }
    const submit = event.target.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      if (API_BASE) {
        const response = await fetch(`${API_BASE}/api/v1/incidents`, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(payload) });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const created = await response.json();
        state.tasks.unshift(normalizeTask({ ...created, service: payload.service, metric: payload.metric, severity: payload.severity, stage: "monitor", status: created.status || "executing", duration: "刚刚" }));
        showToast("告警已提交，任务流已刷新");
      } else {
        state.tasks.unshift({ task_id: `demo-${Date.now().toString(36).slice(-5)}`, service: payload.service, metric: payload.metric, severity: payload.severity, stage: "monitor", status: "executing", duration: "刚刚", summary: "演示模式下创建的本地任务" });
        showToast("演示任务已创建（未发送外部请求）");
      }
      renderTasks(); closeModal(); event.target.reset();
    } catch (error) {
      showToast("告警提交失败，请检查 API 地址或服务状态");
    } finally { submit.disabled = false; }
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(state.theme);
    renderAgents(); renderServices(); renderEvents(); renderTasks(); updateSyncTime(); loadTasks();
    el("open-incident").addEventListener("click", openModal); el("close-incident").addEventListener("click", closeModal); el("cancel-incident").addEventListener("click", closeModal); el("incident-form").addEventListener("submit", submitIncident);
    el("incident-modal").addEventListener("click", (event) => { if (event.target === el("incident-modal")) closeModal(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") { if (!el("incident-modal").hidden) closeModal(); closeMenus(); } });
    el("refresh-button").addEventListener("click", () => { updateSyncTime(); loadTasks(); showToast(state.connected ? "数据已刷新" : "已刷新演示数据"); });
    el("theme-button").addEventListener("click", () => { applyTheme(state.theme === "dark" ? "light" : "dark"); showToast(state.theme === "dark" ? "已切换为深色外观" : "已切换为浅色外观"); });
    el("workspace-button").addEventListener("click", () => { const menu = el("workspace-menu"); setMenu(menu, el("workspace-button"), menu.hidden); setMenu(el("filter-menu"), el("more-filters"), false); });
    el("workspace-menu").querySelectorAll("[data-workspace]").forEach((button) => button.addEventListener("click", () => { el("workspace-name").textContent = button.dataset.workspace; setMenu(el("workspace-menu"), el("workspace-button"), false); showToast(`已切换到${button.dataset.workspace}`); }));
    el("profile-button").addEventListener("click", () => showToast("林一舟 · 运维管理员\n当前权限：告警提交、任务查看、审批复核"));
    document.querySelectorAll(".nav-item").forEach((link) => link.addEventListener("click", () => { document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active")); link.classList.add("active"); closeMenus(); }));
    document.querySelectorAll(".filter-button").forEach((button) => button.addEventListener("click", () => { document.querySelectorAll(".filter-button").forEach((item) => item.classList.remove("active")); button.classList.add("active"); state.filter = button.dataset.filter; state.severity = "all"; state.showAll = false; renderTasks(); }));
    el("more-filters").addEventListener("click", () => { const menu = el("filter-menu"); setMenu(menu, el("more-filters"), menu.hidden); setMenu(el("workspace-menu"), el("workspace-button"), false); });
    el("filter-menu").querySelectorAll("[data-severity]").forEach((button) => button.addEventListener("click", () => { state.severity = button.dataset.severity; el("more-filters").classList.toggle("active-filter", state.severity !== "all"); el("more-filters").title = state.severity === "all" ? "更多任务筛选" : `风险筛选：${button.textContent}`; setMenu(el("filter-menu"), el("more-filters"), false); state.showAll = false; renderTasks(); showToast(`已应用${button.textContent}筛选`); }));
    el("load-more").addEventListener("click", () => { state.showAll = !state.showAll; renderTasks(); showToast(state.showAll ? "已展开全部任务" : "已收起任务列表"); });
    document.querySelector("#services .text-button").addEventListener("click", () => focusSection("services", "已定位到服务拓扑面板"));
    document.querySelectorAll(".runbook-item").forEach((button) => button.addEventListener("click", () => showToast(`已打开运行手册：${button.dataset.runbook}\n可按步骤执行并在审计记录中复核结果。`)));
    document.addEventListener("click", (event) => { if (!event.target.closest(".workspace-switcher") && !event.target.closest("#more-filters")) closeMenus(); });
  });
})();
