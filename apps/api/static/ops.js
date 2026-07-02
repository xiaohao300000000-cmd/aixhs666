const tokenInput = document.querySelector("#ops-token");
const autoRefresh = document.querySelector("#auto-refresh");
const notice = document.querySelector("#notice");
const state = { hidden: false };

document.addEventListener("visibilitychange", () => { state.hidden = document.hidden; });
document.querySelector("#refresh-all").addEventListener("click", refreshAll);
document.querySelector("#task-filter").addEventListener("click", loadTasks);
document.querySelector("#create-task").addEventListener("submit", createTask);
document.querySelector("#create-query").addEventListener("submit", createQuery);
document.querySelector("#run-pipeline").addEventListener("submit", runPipeline);
document.body.addEventListener("click", handleActionClick);

function headers() {
  const value = tokenInput.value.trim();
  return value ? { "Content-Type": "application/json", "X-Ops-Token": value } : { "Content-Type": "application/json" };
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function postJson(url, body = {}) {
  const response = await fetch(url, { method: "POST", headers: headers(), body: JSON.stringify(body) });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function showNotice(message, kind = "info") {
  notice.hidden = false;
  notice.className = `notice ${kind}`;
  notice.textContent = message;
}

function card(label, value, cls = "") {
  return `<div class="card"><div class="label">${escapeHtml(label)}</div><div class="value ${cls}">${escapeHtml(value ?? "-")}</div></div>`;
}

function statusBadge(value) {
  return `<span class="status ${escapeHtml(value || "")}">${escapeHtml(zhStatus(value))}</span>`;
}

async function loadSystem() {
  const data = await getJson("/ops/api/system");
  document.querySelector("#system").innerHTML = [
    card("API", data.api.status, data.api.status),
    card("数据库", data.postgresql.status, data.postgresql.status),
    card("在线采集进程", data.worker_online_count),
    card("MediaCrawler", data.mediacrawler.status, data.mediacrawler.status),
    card("Playwright", data.playwright.status, data.playwright.status),
    card("小红书登录态", data.xiaohongshu_login.status, data.xiaohongshu_login.status),
    card("Feishu", data.feishu.status, data.feishu.status),
    card("当前时间", data.generated_at),
    card("上次成功采集", data.latest_successful_collection_at),
    card("上次失败采集", data.latest_failed_collection_at),
  ].join("");
  const daily = data.dashboard.daily_metrics?.[0] || {};
  const db = data.dashboard.database_metrics || {};
  document.querySelector("#dashboard").innerHTML = [
    card("今日新增内容", daily.new_content_count),
    card("今日新增评论", daily.new_comment_count),
    card("今日新增用户", daily.new_profile_count),
    card("重复内容数", daily.duplicate_content_count),
    card("部分完成任务", db.partial_task_count),
    card("待重试任务", db.retry_task_count),
    card("高价值信号", db.high_value_signal_count),
    card("待审核新词", db.pending_phrase_count),
    card("最近失败原因", db.latest_failure_reason),
  ].join("");
}

async function loadPublicDashboard() {
  const data = await getJson("/ops/api/dashboard/public");
  const overview = data.overview || {};
  document.querySelector("#business-overview").innerHTML = [
    metric("运行状态", overview.run_status || "-"),
    metric("新增内容", overview.new_contents || 0),
    metric("新增评论", overview.new_comments || 0),
    metric("新增用户", overview.new_profiles || 0),
    metric("需求事件", overview.demand_events || 0),
    metric("候选查询", overview.candidate_queries || 0),
    metric("警告", overview.warnings || 0),
    metric("错误", overview.errors || 0),
  ].join("");

  const metadata = data.analysis_metadata || {};
  document.querySelector("#analysis-version").textContent = metadata.rule_version
    ? `${metadata.rule_version} · ${metadata.generated_at || ""}`
    : "暂无分析版本";

  document.querySelector("#insight-board").innerHTML = [
    insightColumn("高频问题", data.insights?.frequent_questions || []),
    insightColumn("新增焦虑点", data.insights?.emerging_anxieties || []),
    insightColumn("内容选题", data.insights?.content_topics || []),
    insightColumn("本地差异", data.insights?.local_demand_differences || [], true),
  ].join("");

  document.querySelector("#evidence-list").innerHTML = (data.evidence || []).slice(0, 12).map(evidenceItem).join("") || emptyState("暂无证据。先运行一轮流程。");
  document.querySelector("#recommended-actions").innerHTML = (data.recommended_actions || []).map((item) => `<div class="item">${escapeHtml(item)}</div>`).join("") || emptyState("暂无推荐动作");
  document.querySelector("#candidate-queries").innerHTML = (data.insights?.candidate_queries || []).slice(0, 10).map(candidateItem).join("") || emptyState("暂无候选查询");
  document.querySelector("#query-performance").innerHTML = (data.queries || []).slice(0, 10).map(queryPerformanceItem).join("") || emptyState("暂无查询词");
}

function metric(label, value) {
  return `<div class="metric"><div class="label">${escapeHtml(label)}</div><div class="metric-value">${escapeHtml(value)}</div></div>`;
}

function insightColumn(title, items, local = false) {
  const body = items.length
    ? items.slice(0, 6).map((item) => local ? localInsightItem(item) : insightItem(item)).join("")
    : emptyState("暂无数据");
  return `<div class="insight-column"><h3>${escapeHtml(title)}</h3>${body}</div>`;
}

function insightItem(item) {
  const examples = (item.examples || []).slice(0, 2).map((example) => `<li>${escapeHtml(example)}</li>`).join("");
  return `<div class="insight-item"><strong>${escapeHtml(item.title)}</strong><div class="muted">${escapeHtml(item.reason)} · 证据 ${item.evidence_count ?? 0}</div><ul>${examples}</ul></div>`;
}

function localInsightItem(item) {
  return `<div class="insight-item"><strong>${escapeHtml(item.region)}</strong><div>${escapeHtml((item.top_terms || []).join("、"))}</div><div class="muted">${escapeHtml(item.reason)} · 证据 ${item.evidence_count ?? 0}</div></div>`;
}

function evidenceItem(item) {
  return `<details class="evidence-item"><summary><strong>${escapeHtml(item.source_entity_type)}</strong> ${escapeHtml(item.source_entity_id)} · ${escapeHtml(item.occurred_at)}</summary><div>${escapeHtml(item.evidence_text)}</div><div class="muted">profile ${escapeHtml(item.public_profile_id)} · content ${escapeHtml(item.source_content_id)} · comment ${escapeHtml(item.source_comment_id)} · low-info ${escapeHtml(item.is_low_information)}</div></details>`;
}

function candidateItem(item) {
  return `<div class="item"><strong>${escapeHtml(item.phrase)}</strong><div class="muted">潜力 ${pct(item.query_potential_score)} · 新鲜度 ${pct(item.novelty_score)} · 证据 ${item.source_text_count}</div><button class="secondary" data-create-query="${escapeHtml(item.phrase)}">加入查询词</button></div>`;
}

function queryPerformanceItem(item) {
  return `<div class="item"><strong>${escapeHtml(item.query_text)}</strong><div class="muted">${escapeHtml(item.status)} · 优先级 ${item.priority} · 产出 ${item.output_count} · 成功 ${pct(item.success_rate)} · 失败 ${pct(item.failure_rate)}</div></div>`;
}

function emptyState(text) {
  return `<div class="empty">${escapeHtml(text)}</div>`;
}

async function loadWorkers() {
  const data = await getJson("/ops/api/workers");
  document.querySelector("#workers").innerHTML = data.items.map((item) => `
    <tr><td>${escapeHtml(item.worker_id)}</td><td>${item.online ? "在线" : "离线"}</td><td>${escapeHtml(zhStatus(item.status))}</td><td>${item.current_task_id ?? ""}</td><td>${escapeHtml(item.started_at)}</td><td>${escapeHtml(item.last_heartbeat_at)}</td><td>${item.completed_task_count}</td><td>${item.failed_task_count}</td><td class="error">${escapeHtml(item.last_error)}</td></tr>
  `).join("");
}

async function loadTasks() {
  const params = new URLSearchParams();
  const status = document.querySelector("#task-status").value;
  const type = document.querySelector("#task-type").value;
  const q = document.querySelector("#task-q").value;
  if (status) params.set("status", status);
  if (type) params.set("task_type", type);
  if (q) params.set("q", q);
  const data = await getJson(`/ops/api/tasks?${params}`);
  document.querySelector("#tasks").innerHTML = data.items.map((item) => `
    <tr><td>${item.task_id}</td><td>${escapeHtml(zhTaskType(item.task_type))}</td><td>${escapeHtml(item.query)}</td><td>${escapeHtml(item.target_id)}</td><td>${statusBadge(item.status)}</td><td>${item.priority}</td><td>${item.attempt_count}</td><td>${escapeHtml(item.worker_id)}</td><td>${escapeHtml(item.started_at)}</td><td>${escapeHtml(item.finished_at)}</td><td class="error">${escapeHtml(item.last_error)}</td><td>${taskButtons(item)}</td></tr>
  `).join("");
}

function taskButtons(item) {
  return [
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/retry">重试</button>`,
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/resume">继续</button>`,
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/cancel" data-confirm="取消任务 ${item.task_id}？">取消</button>`,
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/run-once">运行一次</button>`,
  ].join(" ");
}

async function loadQueries() {
  const data = await getJson("/ops/api/queries");
  document.querySelector("#queries").innerHTML = data.items.map((item) => `
    <tr><td>${item.id}</td><td>${escapeHtml(item.query_text)}</td><td>${escapeHtml(zhStatus(item.status))}</td><td>${item.priority}</td><td>${item.output_count}</td><td>${escapeHtml(item.last_run_at)}</td><td>${pct(item.success_rate)}</td><td>${pct(item.failure_rate)}</td><td><button class="secondary" data-post="/ops/api/queries/${item.id}/tasks">创建任务</button> <button class="secondary" data-post="/ops/api/queries/${item.id}/enable">启用</button> <button class="secondary" data-post="/ops/api/queries/${item.id}/disable">停用</button></td></tr>
  `).join("");
}

async function loadRecent() {
  const data = await getJson("/ops/api/recent");
  document.querySelector("#contents").innerHTML = data.contents.map((item) => `<div class="item"><strong>${escapeHtml(item.title)}</strong><div>${escapeHtml(item.body_summary)}</div><div class="muted">${escapeHtml(item.author)} · 点赞 ${item.like_count} · ${escapeHtml(item.url)}</div></div>`).join("");
  document.querySelector("#comments").innerHTML = data.comments.map((item) => `<div class="item">${escapeHtml(item.body_text)}<div class="muted">${escapeHtml(item.author)} · ${escapeHtml(item.content_title)} · 点赞 ${item.like_count}</div></div>`).join("");
  document.querySelector("#profiles").innerHTML = data.profiles.map((item) => `<div class="item"><strong>${escapeHtml(item.display_name)}</strong><div>${escapeHtml(item.bio)}</div><details><summary>${escapeHtml(item.public_contact_text_masked || "联系方式")}</summary>${escapeHtml(item.public_contact_text)}</details><div class="muted">${escapeHtml(item.platform_user_id)} · ${escapeHtml(item.profile_url)}</div></div>`).join("");
}

async function loadErrors() {
  const data = await getJson("/ops/api/errors");
  document.querySelector("#errors").innerHTML = data.items.map((item) => `<div class="item"><strong>任务 ${item.task_id}</strong> ${escapeHtml(zhStatus(item.error_type))}<pre class="error">${escapeHtml(item.full_error)}</pre><button class="secondary" data-post="/ops/api/tasks/${item.task_id}/retry">重试</button></div>`).join("");
}

async function loadBrowser() {
  const data = await getJson("/ops/api/browser");
  document.querySelector("#browser").innerHTML = [
    card("采集后端", data.backend),
    card("MediaCrawler", data.mediacrawler_available ? "正常" : "异常", data.mediacrawler_available ? "正常" : "异常"),
    card("Playwright 目录", data.playwright_profile_dir),
    card("无头模式", data.headless ? "是" : "否"),
    card("登录状态", data.login_status),
    card("最近运行目录", data.mediacrawler_recent_run_dir),
  ].join("");
}

async function createTask(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  await postJson("/ops/api/tasks", { query_text: form.get("query_text"), limit: Number(form.get("limit")), priority: Number(form.get("priority")) });
  event.target.reset();
  loadTasks(); loadQueries();
}

async function createQuery(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  await postJson("/ops/api/queries", { query_text: form.get("query_text"), priority: Number(form.get("priority")) });
  event.target.reset();
  loadQueries();
}

async function runPipeline(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const mode = form.get("mode");
  const queryId = Number(form.get("query_id"));
  const payload = {
    all_enabled: mode !== "query" || !queryId,
    query_ids: mode === "query" && queryId ? [queryId] : [],
    collection_limit: Number(form.get("collection_limit") || 20),
    skip_analysis: Boolean(form.get("skip_analysis")),
    requested_by: "ops_dashboard",
  };
  try {
    showNotice("正在启动一轮流程...", "info");
    await ensureRunnableQuery();
    const result = await postJson("/ops/api/pipeline/runs", payload);
    showNotice(`流程已完成：运行编号 ${result.run_id}，状态 ${zhStatus(result.status)}`, "success");
    refreshAll();
  } catch (error) {
    showNotice(`运行失败：${humanError(error)}`, "error");
  }
}

async function ensureRunnableQuery() {
  const data = await getJson("/ops/api/queries");
  if ((data.items || []).some((item) => item.status === "active")) return;
  await postJson("/ops/api/queries", { query_text: "admissions", priority: 100 });
}

async function handleActionClick(event) {
  const createQueryButton = event.target.closest("button[data-create-query]");
  if (createQueryButton) {
    try {
      await postJson("/ops/api/queries", { query_text: createQueryButton.dataset.createQuery, priority: 50 });
      showNotice("候选查询已加入查询词库", "success");
      refreshAll();
    } catch (error) {
      showNotice(`加入查询失败：${humanError(error)}`, "error");
    }
    return;
  }
  const button = event.target.closest("button[data-post]");
  if (!button) return;
  if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) return;
  try {
    await postJson(button.dataset.post);
    showNotice("操作已完成", "success");
    refreshAll();
  } catch (error) {
    showNotice(`操作失败：${humanError(error)}`, "error");
  }
}

function refreshAll() {
  loadPublicDashboard().catch(console.error);
  loadSystem().catch(console.error);
  loadWorkers().catch(console.error);
  loadTasks().catch(console.error);
  loadQueries().catch(console.error);
  loadRecent().catch(console.error);
  loadErrors().catch(console.error);
  loadBrowser().catch(console.error);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

function pct(value) {
  return value == null ? "-" : `${Math.round(value * 100)}%`;
}

function zhStatus(value) {
  const map = {
    pending: "待运行",
    running: "运行中",
    partial: "部分完成",
    retry: "待重试",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    active: "启用",
    paused: "停用",
    idle: "空闲",
    error: "错误",
  };
  return map[value] || value || "-";
}

function zhTaskType(value) {
  const map = {
    search: "搜索",
    comments: "评论",
    collect_comments: "评论",
    comment_collection: "评论",
    profile: "用户主页",
    content_detail: "内容详情",
    collect_content: "内容详情",
  };
  return map[value] || value || "-";
}

function humanError(error) {
  const text = String(error?.message || error || "");
  try {
    const parsed = JSON.parse(text);
    return parsed.detail || text;
  } catch {
    return text;
  }
}

setInterval(() => { if (autoRefresh.checked && !state.hidden) loadWorkers().catch(console.error); }, 3000);
setInterval(() => { if (autoRefresh.checked && !state.hidden) { loadTasks().catch(console.error); loadSystem().catch(console.error); } }, 5000);
setInterval(() => { if (autoRefresh.checked && !state.hidden) { loadPublicDashboard().catch(console.error); loadRecent().catch(console.error); loadErrors().catch(console.error); } }, 10000);
refreshAll();
