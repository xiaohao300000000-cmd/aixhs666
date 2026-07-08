const lanes = [
  {id: "immediate", bucket: "立即处理"},
  {id: "today", bucket: "今日内处理"},
  {id: "observe", bucket: "可观察"},
  {id: "insufficient", bucket: "信息不足"},
  {id: "stale", bucket: "过期/低优先级"},
];

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
  document.getElementById("priority-immediate").textContent = summary.priority_immediate ?? 0;
  document.getElementById("priority-today").textContent = summary.priority_today ?? 0;
  document.getElementById("information-insufficient").textContent = summary.information_insufficient ?? 0;
}

async function loadBoard() {
  const payload = await fetchJson("/api/leads?page_size=200");
  for (const lane of lanes) {
    const container = document.getElementById(`lane-${lane.id}`);
    container.innerHTML = "";
    const items = payload.items.filter((lead) => lead.priority_bucket === lane.bucket);
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "暂无客户";
      container.appendChild(empty);
      continue;
    }
    for (const lead of items) {
      container.appendChild(renderLeadCard(lead));
    }
  }
}

function renderLeadCard(lead) {
  const card = document.createElement("article");
  card.className = "lead-card";
  const reasons = Array.isArray(lead.why_recommended) ? lead.why_recommended : [];
  const evidenceItems = Array.isArray(lead.evidence_context) ? lead.evidence_context : [];
  card.innerHTML = `
    <header>
      <div>
        <h3>${escapeHtml(lead.business_summary || lead.display_name || lead.platform_user_id || "未知线索")}</h3>
        <div class="subhead">${escapeHtml(lead.source_role || "需求主体不确定")} · ${escapeHtml(lead.freshness_label || "未知时间")} · ${escapeHtml(lead.sla_due_label || "")}</div>
      </div>
      <span class="score">${escapeHtml(lead.priority_bucket || "")}</span>
    </header>
    <div class="meta">${escapeHtml(lead.region_text || "未知地区")} · ${escapeHtml(lead.product || "未知课程")} · ${escapeHtml(lead.demand_type || "未知需求")} · ${escapeHtml(lead.status_label || lead.status)}</div>
    <section class="reason-list">
      <strong>为什么推荐</strong>
      ${reasons.map((reason) => `<div>${escapeHtml(reason)}</div>`).join("") || "<div>暂无推荐原因</div>"}
    </section>
    <details class="evidence-panel">
      <summary>展开证据和上下文</summary>
      ${renderEvidence(evidenceItems)}
      ${lead.profile_url ? `<a href="${escapeAttribute(lead.profile_url)}" target="_blank" rel="noreferrer">用户主页</a>` : ""}
    </details>
    <div class="next-step">${escapeHtml(lead.recommended_next_step || "")}</div>
    <div class="actions">
      ${(lead.judgment_actions || []).map((action) => `<button class="secondary" type="button" data-action="${escapeAttribute(action.status)}">${escapeHtml(action.label)}</button>`).join("")}
    </div>
  `;
  for (const button of card.querySelectorAll("[data-action]")) {
    button.addEventListener("click", () => updateStatus(lead.id, button.dataset.action));
  }
  return card;
}

function renderEvidence(items) {
  if (!items.length) {
    return '<div class="evidence"><strong>证据</strong>暂无证据</div>';
  }
  return items
    .map(
      (item) => `
        <div class="evidence">
          <strong>${escapeHtml(item.source_role || "证据")}</strong>
          <div>${escapeHtml(item.full_text || item.evidence_text || "")}</div>
        </div>
      `,
    )
    .join("");
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
  await loadBoard();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

document.getElementById("backfill-button").addEventListener("click", runBackfill);
loadAll().catch((error) => {
  console.error(error);
});
