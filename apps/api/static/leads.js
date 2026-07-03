const lanes = ["new", "needs_enrichment", "qualified", "handled"];

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

async function loadSummary() {
  const summary = await fetchJson("/api/leads/summary");
  document.getElementById("today-new").textContent = summary.today_new ?? 0;
  document.getElementById("needs-enrichment").textContent = summary.needs_enrichment ?? 0;
  document.getElementById("qualified").textContent = summary.qualified ?? 0;
  document.getElementById("handled").textContent = summary.handled ?? 0;
}

async function loadLane(status) {
  const payload = await fetchJson(`/api/leads?status=${encodeURIComponent(status)}`);
  const container = document.getElementById(`lane-${status}`);
  container.innerHTML = "";
  if (!payload.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无客户";
    container.appendChild(empty);
    return;
  }
  for (const lead of payload.items) {
    container.appendChild(renderLeadCard(lead));
  }
}

function renderLeadCard(lead) {
  const card = document.createElement("article");
  card.className = "lead-card";
  const evidence = lead.evidence?.[0]?.evidence_text || "暂无证据";
  const missing = lead.missing_info?.length ? lead.missing_info.join("、") : "无";
  card.innerHTML = `
    <header>
      <h3>${escapeHtml(lead.display_name || lead.platform_user_id || "未知用户")}</h3>
      <span class="score">${lead.intent_score}</span>
    </header>
    <div class="meta">${escapeHtml(lead.region_text || "未知地区")} · ${escapeHtml(lead.product || "未知课程")} · ${escapeHtml(lead.demand_type || "未知需求")} · ${escapeHtml(lead.intent_stage || "未知阶段")}</div>
    <div class="missing">缺失信息：${escapeHtml(missing)}</div>
    <div class="evidence">${escapeHtml(evidence)}</div>
    <div class="next-step">${escapeHtml(lead.recommended_next_step || "")}</div>
    <div class="actions">
      <button class="secondary" type="button" data-action="handled">已处理</button>
      <button class="secondary" type="button" data-action="ignored">忽略</button>
    </div>
  `;
  card.querySelector('[data-action="handled"]').addEventListener("click", () => updateStatus(lead.id, "handled"));
  card.querySelector('[data-action="ignored"]').addEventListener("click", () => updateStatus(lead.id, "ignored"));
  return card;
}

async function updateStatus(leadId, status) {
  await fetchJson(`/api/leads/${leadId}/status`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({status}),
  });
  await loadAll();
}

async function runBackfill() {
  const button = document.getElementById("backfill-button");
  button.disabled = true;
  button.textContent = "生成中...";
  try {
    await fetchJson("/api/leads/backfill", {method: "POST"});
    await loadAll();
  } finally {
    button.disabled = false;
    button.textContent = "从历史数据生成客户";
  }
}

async function loadAll() {
  await loadSummary();
  await Promise.all(lanes.map(loadLane));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.getElementById("backfill-button").addEventListener("click", runBackfill);
loadAll().catch((error) => {
  console.error(error);
});
