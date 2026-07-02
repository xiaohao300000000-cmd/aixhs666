const tokenInput = document.querySelector("#ops-token");
const autoRefresh = document.querySelector("#auto-refresh");
const state = { hidden: false };

document.addEventListener("visibilitychange", () => { state.hidden = document.hidden; });
document.querySelector("#refresh-all").addEventListener("click", refreshAll);
document.querySelector("#task-filter").addEventListener("click", loadTasks);
document.querySelector("#create-task").addEventListener("submit", createTask);
document.querySelector("#create-query").addEventListener("submit", createQuery);
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

function card(label, value, cls = "") {
  return `<div class="card"><div class="label">${escapeHtml(label)}</div><div class="value ${cls}">${escapeHtml(value ?? "-")}</div></div>`;
}

function statusBadge(value) {
  return `<span class="status ${escapeHtml(value || "")}">${escapeHtml(value || "-")}</span>`;
}

async function loadSystem() {
  const data = await getJson("/ops/api/system");
  document.querySelector("#system").innerHTML = [
    card("API", data.api.status, data.api.status),
    card("PostgreSQL", data.postgresql.status, data.postgresql.status),
    card("Workers online", data.worker_online_count),
    card("MediaCrawler", data.mediacrawler.status, data.mediacrawler.status),
    card("Playwright", data.playwright.status, data.playwright.status),
    card("XHS login", data.xiaohongshu_login.status, data.xiaohongshu_login.status),
    card("Feishu", data.feishu.status, data.feishu.status),
    card("Current time", data.generated_at),
    card("Last success", data.latest_successful_collection_at),
    card("Last failure", data.latest_failed_collection_at),
  ].join("");
  const daily = data.dashboard.daily_metrics?.[0] || {};
  const db = data.dashboard.database_metrics || {};
  document.querySelector("#dashboard").innerHTML = [
    card("Today posts", daily.new_content_count),
    card("Today comments", daily.new_comment_count),
    card("Today users", daily.new_profile_count),
    card("Duplicate count", daily.duplicate_content_count),
    card("Partial", db.partial_task_count),
    card("Retry", db.retry_task_count),
    card("High value signals", db.high_value_signal_count),
    card("Pending phrases", db.pending_phrase_count),
    card("Latest failure reason", db.latest_failure_reason),
  ].join("");
}

async function loadWorkers() {
  const data = await getJson("/ops/api/workers");
  document.querySelector("#workers").innerHTML = data.items.map((item) => `
    <tr><td>${escapeHtml(item.worker_id)}</td><td>${item.online ? "online" : "offline"}</td><td>${escapeHtml(item.status)}</td><td>${item.current_task_id ?? ""}</td><td>${escapeHtml(item.started_at)}</td><td>${escapeHtml(item.last_heartbeat_at)}</td><td>${item.completed_task_count}</td><td>${item.failed_task_count}</td><td class="error">${escapeHtml(item.last_error)}</td></tr>
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
    <tr><td>${item.task_id}</td><td>${escapeHtml(item.task_type)}</td><td>${escapeHtml(item.query)}</td><td>${escapeHtml(item.target_id)}</td><td>${statusBadge(item.status)}</td><td>${item.priority}</td><td>${item.attempt_count}</td><td>${escapeHtml(item.worker_id)}</td><td>${escapeHtml(item.started_at)}</td><td>${escapeHtml(item.finished_at)}</td><td class="error">${escapeHtml(item.last_error)}</td><td>${taskButtons(item)}</td></tr>
  `).join("");
}

function taskButtons(item) {
  return [
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/retry">Retry</button>`,
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/resume">Resume</button>`,
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/cancel" data-confirm="Cancel task ${item.task_id}?">Cancel</button>`,
    `<button class="secondary" data-post="/ops/api/tasks/${item.task_id}/run-once">Run once</button>`,
  ].join(" ");
}

async function loadQueries() {
  const data = await getJson("/ops/api/queries");
  document.querySelector("#queries").innerHTML = data.items.map((item) => `
    <tr><td>${item.id}</td><td>${escapeHtml(item.query_text)}</td><td>${escapeHtml(item.status)}</td><td>${item.priority}</td><td>${item.output_count}</td><td>${escapeHtml(item.last_run_at)}</td><td>${pct(item.success_rate)}</td><td>${pct(item.failure_rate)}</td><td><button class="secondary" data-post="/ops/api/queries/${item.id}/tasks">Create task</button> <button class="secondary" data-post="/ops/api/queries/${item.id}/enable">Enable</button> <button class="secondary" data-post="/ops/api/queries/${item.id}/disable">Disable</button></td></tr>
  `).join("");
}

async function loadRecent() {
  const data = await getJson("/ops/api/recent");
  document.querySelector("#contents").innerHTML = data.contents.map((item) => `<div class="item"><strong>${escapeHtml(item.title)}</strong><div>${escapeHtml(item.body_summary)}</div><div class="muted">${escapeHtml(item.author)} · likes ${item.like_count} · ${escapeHtml(item.url)}</div></div>`).join("");
  document.querySelector("#comments").innerHTML = data.comments.map((item) => `<div class="item">${escapeHtml(item.body_text)}<div class="muted">${escapeHtml(item.author)} · ${escapeHtml(item.content_title)} · likes ${item.like_count}</div></div>`).join("");
  document.querySelector("#profiles").innerHTML = data.profiles.map((item) => `<div class="item"><strong>${escapeHtml(item.display_name)}</strong><div>${escapeHtml(item.bio)}</div><details><summary>${escapeHtml(item.public_contact_text_masked || "contact")}</summary>${escapeHtml(item.public_contact_text)}</details><div class="muted">${escapeHtml(item.platform_user_id)} · ${escapeHtml(item.profile_url)}</div></div>`).join("");
}

async function loadErrors() {
  const data = await getJson("/ops/api/errors");
  document.querySelector("#errors").innerHTML = data.items.map((item) => `<div class="item"><strong>Task ${item.task_id}</strong> ${escapeHtml(item.error_type)}<pre class="error">${escapeHtml(item.full_error)}</pre><button class="secondary" data-post="/ops/api/tasks/${item.task_id}/retry">Retry</button></div>`).join("");
}

async function loadBrowser() {
  const data = await getJson("/ops/api/browser");
  document.querySelector("#browser").innerHTML = [
    card("Backend", data.backend),
    card("MediaCrawler", data.mediacrawler_available ? "正常" : "异常", data.mediacrawler_available ? "正常" : "异常"),
    card("Playwright profile", data.playwright_profile_dir),
    card("Headless", data.headless),
    card("Login", data.login_status),
    card("Recent run", data.mediacrawler_recent_run_dir),
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

async function handleActionClick(event) {
  const button = event.target.closest("button[data-post]");
  if (!button) return;
  if (button.dataset.confirm && !window.confirm(button.dataset.confirm)) return;
  await postJson(button.dataset.post);
  refreshAll();
}

function refreshAll() {
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

setInterval(() => { if (autoRefresh.checked && !state.hidden) loadWorkers().catch(console.error); }, 3000);
setInterval(() => { if (autoRefresh.checked && !state.hidden) { loadTasks().catch(console.error); loadSystem().catch(console.error); } }, 5000);
setInterval(() => { if (autoRefresh.checked && !state.hidden) { loadRecent().catch(console.error); loadErrors().catch(console.error); } }, 10000);
refreshAll();
