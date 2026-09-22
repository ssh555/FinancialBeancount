"use strict";

const state = {
  view: "overview",
  reviewType: "imports",
  transactionPage: 1,
  transactions: [],
  counts: { imports: 0, matches: 0, refunds: 0, classifications: 0 },
};

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const money = value => new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(value || 0));
const text = value => String(value ?? "");
const escapeHtml = value => text(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const merchant = tx => tx?.merchant || tx?.counterparty || "未命名交易";

function apiBase() { return sessionStorage.getItem("financial-beancount-api") || ""; }
function actor() { return localStorage.getItem("financial-beancount-actor") || "local-user"; }

async function request(path, options = {}) {
  const token = sessionStorage.getItem("financial-beancount-token");
  const headers = { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(`${apiBase()}${path}`, { ...options, headers, cache: "no-store" });
  } catch (_) {
    setConnection(false);
    throw new Error("无法连接本地账本服务");
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) setConnection(false, "需要令牌");
    throw new Error(payload.error?.message || `请求失败 (${response.status})`);
  }
  setConnection(true);
  return payload;
}

function setConnection(online, label = online ? "本地已连接" : "连接中断") {
  $("#connection-button").classList.toggle("online", online);
  $("#connection-label").textContent = label;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 2600);
}

function skeleton(container, count = 3) {
  container.innerHTML = Array.from({ length: count }, () => '<div class="list-card skeleton"></div>').join("");
}

function showView(name) {
  state.view = name;
  $$(".view").forEach(view => view.classList.toggle("active", view.id === `${name}-view`));
  $$(".bottom-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  if (name === "overview") loadOverview();
  if (name === "transactions") loadTransactions(true);
  if (name === "review") loadReviews();
  if (name === "settings") loadSettings();
  $("#app").focus({ preventScroll: true });
}

function dateQuery() {
  const params = new URLSearchParams();
  if ($("#date-from").value) params.set("date_from", $("#date-from").value);
  if ($("#date-to").value) params.set("date_to", $("#date-to").value);
  return params.toString();
}

async function loadOverview() {
  $("#summary-cards").innerHTML = '<div class="summary-card skeleton"></div>'.repeat(4);
  $("#category-list").innerHTML = '<div class="skeleton"></div>';
  try {
    const { data } = await request(`/api/v1/statistics/summary?${dateQuery()}`);
    const cards = [
      ["净支出", money(data.net_expense), `${data.expense_count} 笔消费`, "featured"],
      ["总支出", money(data.gross_expense), "退款前", ""],
      ["已确认退款", money(data.refunds), `${data.refund_count} 笔`, ""],
      ["普通收入", money(data.ordinary_income), `${data.income_count} 笔`, ""],
    ];
    $("#summary-cards").innerHTML = cards.map(([title, value, note, css]) =>
      `<article class="summary-card ${css}"><small>${title}</small><strong>${value}</strong><small>${note}</small></article>`
    ).join("");
    const maximum = Math.max(...data.categories.map(item => Number(item.net_expense)), 1);
    $("#category-total").textContent = `${data.categories.length} 类`;
    $("#category-list").innerHTML = data.categories.length ? data.categories.map(item => `
      <div class="category-row"><span>${escapeHtml(item.category)}</span><strong>${money(item.net_expense)}</strong>
      <div class="category-bar"><span style="width:${Math.max(0, Number(item.net_expense)) / maximum * 100}%"></span></div></div>`).join("") : empty("当前范围没有可统计交易");
    if (data.pending_review_excluded_count) toast(`${data.pending_review_excluded_count} 笔待审核交易未计入统计`);
  } catch (error) { renderError($("#summary-cards"), error); renderError($("#category-list"), error); }
  refreshCounts();
}

async function loadTransactions(reset = false) {
  const list = $("#transaction-list");
  if (reset) { state.transactionPage = 1; state.transactions = []; skeleton(list, 4); }
  const params = new URLSearchParams({ page: state.transactionPage, page_size: 30 });
  const query = $("#transaction-search").value.trim();
  if (query) params.set("search", query);
  try {
    const payload = await request(`/api/v1/transactions?${params}`);
    state.transactions.push(...payload.data);
    list.innerHTML = state.transactions.length ? state.transactions.map(tx => transactionCard(tx)).join("") : empty("还没有唯一交易");
    $("#load-more").classList.toggle("hidden", state.transactions.length >= payload.meta.total);
  } catch (error) { renderError(list, error); }
}

function transactionCard(tx) {
  const income = tx.direction === "income" || Number(tx.amount) > 0;
  return `<button class="list-card" type="button" data-detail="transaction" data-id="${escapeHtml(tx.canonical_id)}">
    <span class="list-top"><span class="list-title">${escapeHtml(merchant(tx))}</span><span class="amount ${income ? "income" : "expense"}">${income ? "+" : "−"}${money(Math.abs(Number(tx.amount)))}</span></span>
    <span class="list-meta"><span>${escapeHtml(tx.booking_date)}</span><span class="tag">${escapeHtml(tx.category || "未分类")}</span><span>${tx.source_count} 个来源</span></span>
  </button>`;
}

async function refreshCounts() {
  const paths = {
    imports: "/api/v1/import-reviews?status=pending&page_size=1",
    matches: "/api/v1/review/candidates?status=pending&page_size=1",
    refunds: "/api/v1/review/refunds?status=pending&page_size=1",
    classifications: "/api/v1/review/classifications?status=pending&page_size=1",
  };
  const results = await Promise.allSettled(Object.entries(paths).map(async ([key, path]) => [key, await request(path)]));
  for (const result of results) if (result.status === "fulfilled") state.counts[result.value[0]] = result.value[1].meta.total;
  const total = Object.values(state.counts).reduce((sum, count) => sum + count, 0);
  for (const [key, count] of Object.entries(state.counts)) $(`#count-${key}`).textContent = count;
  $("#review-badge").textContent = total > 99 ? "99+" : total;
  $("#review-badge").classList.toggle("hidden", !total);
}

async function loadReviews() {
  await refreshCounts();
  const list = $("#review-list"); skeleton(list, 3);
  try {
    if (state.reviewType === "imports") await loadImportReviews(list);
    else {
      const routes = { matches: "candidates", refunds: "refunds", classifications: "classifications" };
      const { data } = await request(`/api/v1/review/${routes[state.reviewType]}?status=pending&page_size=100`);
      list.innerHTML = data.length ? data.map(item => reviewCard(state.reviewType, item)).join("") : empty("这一类没有待审核项");
    }
  } catch (error) { renderError(list, error); }
}

async function loadImportReviews(list) {
  const sessions = (await request("/api/v1/import-reviews?status=pending&page_size=100")).data;
  const groups = await Promise.all(sessions.map(async session => ({ session, items: (await request(`/api/v1/import-reviews/${session.session_id}/items?page_size=200`)).data })));
  const pending = groups.flatMap(({ session, items }) => items.filter(item => item.status === "pending").map(item => ({ ...item, session_id: session.session_id })));
  list.innerHTML = pending.length ? pending.map(item => reviewCard("imports", item)).join("") : empty("没有待审核的导入变化");
}

function reviewCard(type, item) {
  let id, title, meta, endpoint;
  if (type === "imports") {
    id = item.review_item_id; title = merchant(item.raw); meta = `${item.item_type} · ${item.raw.booking_date}`;
    endpoint = `/api/v1/import-reviews/${item.session_id}/items/${id}`;
  } else if (type === "matches") {
    id = item.candidate_id; title = `${merchant(item.payment)} ↔ ${merchant(item.bank)}`; meta = `置信度 ${item.confidence} · ${item.conflict_count} 个冲突`;
    endpoint = `/api/v1/review/candidates/${id}`;
  } else if (type === "refunds") {
    id = item.relationship_id; title = `${merchant(item.refund)} ↔ ${merchant(item.original)}`; meta = `退款 ${money(item.amount)} · 置信度 ${item.confidence}`;
    endpoint = `/api/v1/review/refunds/${id}`;
  } else {
    id = item.candidate_id; title = merchant(item.transaction); meta = `建议：${item.proposed_type} / ${item.proposed_category || "未分类"}`;
    endpoint = `/api/v1/review/classifications/${id}`;
  }
  return `<article class="list-card"><button class="plain-detail" type="button" data-endpoint="${escapeHtml(endpoint)}" data-title="${escapeHtml(title)}">
    <span class="list-top"><span class="list-title">${escapeHtml(title)}</span><span class="tag">待审核</span></span><span class="list-meta">${escapeHtml(meta)}</span></button>
    <div class="review-actions"><button class="button danger" data-decision="reject" data-endpoint="${escapeHtml(endpoint)}" type="button">拒绝</button><button class="button primary" data-decision="confirm" data-endpoint="${escapeHtml(endpoint)}" type="button">确认</button></div></article>`;
}

async function decide(button) {
  const action = button.dataset.decision;
  const endpoint = button.dataset.endpoint;
  if (!confirm(action === "confirm" ? "确认这项审核决定？" : "拒绝这项建议？原始记录仍会保留。")) return;
  button.disabled = true;
  try {
    await request(`${endpoint}/${action}`, { method: "POST", body: JSON.stringify({ actor: actor() }) });
    toast(action === "confirm" ? "已确认并记录审计事件" : "已拒绝并记录审计事件");
    await loadReviews();
  } catch (error) { toast(error.message); button.disabled = false; }
}

async function showDetail(endpoint, title) {
  const dialog = $("#detail-dialog");
  $("#dialog-title").textContent = title || "详情";
  $("#dialog-content").innerHTML = '<div class="skeleton"></div>';
  dialog.showModal();
  try {
    const { data } = await request(endpoint);
    $("#dialog-content").innerHTML = detailMarkup(data, endpoint);
  } catch (error) { renderError($("#dialog-content"), error); }
}

function detailMarkup(data, endpoint) {
  const primary = data.transaction || data.canonical || data.payment || data.refund || data.raw || data;
  const fields = [
    ["日期", primary.booking_date], ["金额", primary.amount != null ? money(primary.amount) : null],
    ["方向", primary.direction], ["商户", merchant(primary)], ["分类", primary.category],
    ["状态", data.status || primary.status], ["来源数量", primary.source_count],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  const editable = data.status === "pending" && (endpoint.includes("/review/candidates/") || endpoint.includes("/import-reviews/"));
  const editForm = editable ? `<form class="edit-form" data-modify-form data-endpoint="${escapeHtml(endpoint)}" data-kind="${endpoint.includes("/review/candidates/") ? "match" : "import"}">
    <h3>人工修正</h3>
    <label>商户<input name="merchant" value="${escapeHtml(primary.merchant || primary.counterparty || "")}"></label>
    <label>分类<input name="category" value="${escapeHtml(primary.category || "")}"></label>
    <label>备注<input name="notes" value="${escapeHtml(primary.notes || "")}"></label>
    <button class="button primary" type="submit">保存修正并完成审核</button>
  </form>` : "";
  const transactionForm = endpoint.startsWith("/api/v1/transactions/") ? `<form class="edit-form" data-transaction-edit data-endpoint="${escapeHtml(endpoint)}">
    <h3>修改唯一交易</h3>
    <label>日期<input name="booking_date" type="date" required value="${escapeHtml(primary.booking_date || "")}"></label>
    <label>金额<input name="amount" inputmode="decimal" required value="${escapeHtml(primary.amount || "")}"></label>
    <label>收支<select name="direction"><option value="expense" ${primary.direction === "expense" ? "selected" : ""}>支出</option><option value="income" ${primary.direction === "income" ? "selected" : ""}>收入</option></select></label>
    <label>商户<input name="merchant" required value="${escapeHtml(primary.merchant || "")}"></label>
    <label>分类<input name="category" value="${escapeHtml(primary.category || "")}"></label>
    <label>交易类型<select name="tx_type">${["unknown", "expense", "income", "refund", "transfer", "investment", "preauthorization"].map(value => `<option value="${value}" ${primary.tx_type === value ? "selected" : ""}>${value}</option>`).join("")}</select></label>
    <label>支付渠道<input name="payment_channel" value="${escapeHtml(primary.payment_channel || "")}"></label>
    <label>资金账户<input name="funding_account" value="${escapeHtml(primary.funding_account || "")}"></label>
    <label>状态<input name="status" value="${escapeHtml(primary.status || "")}"></label>
    <label>备注<input name="notes" value="${escapeHtml(primary.notes || "")}"></label>
    <button class="button primary" type="submit">保存修改</button>
    <button class="button danger" data-soft-delete type="button">移入已删除记录</button>
  </form>` : "";
  return `<dl class="detail-grid">${fields.map(([key, value]) => `<dt>${key}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>${editForm}${transactionForm}
    <h3 style="margin-top:22px">完整审计数据</h3><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

function loadSettings() {
  $("#api-base").value = apiBase();
  $("#api-token").value = sessionStorage.getItem("financial-beancount-token") || "";
  $("#review-actor").value = actor();
}

function showCreateForm() {
  $("#dialog-title").textContent = "新增交易";
  $("#dialog-content").innerHTML = `<form class="edit-form" data-transaction-create>
    <label>日期<input name="booking_date" type="date" required value="${new Date().toISOString().slice(0, 10)}"></label>
    <label>金额<input name="amount" inputmode="decimal" required placeholder="支出填负数，如 -25.00"></label>
    <label>收支<select name="direction"><option value="expense">支出</option><option value="income">收入</option></select></label>
    <label>商户<input name="merchant" required></label><label>分类<input name="category"></label><label>备注<input name="notes"></label>
    <button class="button primary" type="submit">保存交易</button></form>`;
  $("#detail-dialog").showModal();
}

async function showImportForm() {
  $("#dialog-title").textContent = "导入官方账单";
  $("#dialog-content").innerHTML = '<div class="skeleton"></div>';
  $("#detail-dialog").showModal();
  try {
    const { data } = await request("/api/v1/import-formats");
    $("#dialog-content").innerHTML = `<form class="edit-form" data-statement-import>
      <label>账单格式<select name="format_id">${data.map(item => `<option value="${escapeHtml(item.format_id)}">${escapeHtml(item.display_name)}</option>`).join("")}</select></label>
      <label>来源账户<input name="source_account" required placeholder="例如：支付宝-本人"></label>
      <label>账单文件<input name="statement" type="file" required accept=".csv,.xlsx,.pdf"></label>
      <p class="muted">文件仅发送到本机账本服务处理；原始观察会永久保留并进入审核流程。</p>
      <button class="button primary" type="submit">开始导入</button></form>`;
  } catch (error) { renderError($("#dialog-content"), error); }
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(text(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("无法读取账单文件"));
    reader.readAsDataURL(file);
  });
}

async function exportTransactions(format) {
  try {
    const payload = await request(`/api/v1/exports/transactions?format=${format}`);
    let content, mime;
    if (format === "csv") {
      const columns = ["canonical_id", "booking_date", "transaction_time", "amount", "direction", "merchant", "category", "payment_channel", "funding_account", "tx_type", "status", "review_status", "notes", "source_count"];
      const quote = value => `"${text(value).replaceAll('"', '""')}"`;
      content = "\ufeff" + [columns.join(","), ...payload.data.map(row => columns.map(column => quote(row[column])).join(","))].join("\r\n"); mime = "text/csv;charset=utf-8";
    } else { content = JSON.stringify({ exported_at: new Date().toISOString(), ...payload }, null, 2); mime = "application/json"; }
    const blob = new Blob([content], { type: mime });
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `financial-beancount-${new Date().toISOString().slice(0, 10)}.${format}`; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000); toast(`已导出 ${payload.meta.total} 笔唯一交易`);
  } catch (error) { toast(error.message); }
}

async function showTrash() {
  $("#dialog-title").textContent = "已删除交易"; $("#dialog-content").innerHTML = '<div class="skeleton"></div>'; if (!$("#detail-dialog").open) $("#detail-dialog").showModal();
  try {
    const payload = await request("/api/v1/deleted-transactions?page_size=200");
    $("#dialog-content").innerHTML = payload.data.length ? `<div class="stack-list">${payload.data.map(item => `<article class="list-card"><span class="list-top"><span class="list-title">${escapeHtml(merchant(item))}</span><span class="amount">${money(item.amount)}</span></span><span class="list-meta"><span>${escapeHtml(item.booking_date)}</span><span>${escapeHtml(item.deletion_reason || "未填写原因")}</span></span><button class="button primary wide" data-restore="${escapeHtml(item.canonical_id)}" type="button">恢复交易</button></article>`).join("")}</div>` : empty("回收站为空");
  } catch (error) { renderError($("#dialog-content"), error); }
}

function empty(message) { return `<div class="empty">${escapeHtml(message)}</div>`; }
function renderError(container, error) { container.innerHTML = empty(error.message || "加载失败"); }

document.addEventListener("click", event => {
  const nav = event.target.closest("[data-view]"); if (nav) showView(nav.dataset.view);
  const tab = event.target.closest("[data-review]"); if (tab) { state.reviewType = tab.dataset.review; $$("[data-review]").forEach(node => node.classList.toggle("active", node === tab)); loadReviews(); }
  const decision = event.target.closest("[data-decision]"); if (decision) decide(decision);
  const detail = event.target.closest("[data-detail='transaction']"); if (detail) showDetail(`/api/v1/transactions/${detail.dataset.id}`, "交易详情");
  const endpoint = event.target.closest("[data-endpoint]:not([data-decision])"); if (endpoint) showDetail(endpoint.dataset.endpoint, endpoint.dataset.title);
  if (event.target.closest("[data-action='refresh']")) showView(state.view);
});

$("#transaction-filter").addEventListener("submit", event => { event.preventDefault(); loadTransactions(true); });
$("#add-button").addEventListener("click", showCreateForm);
$("#import-button").addEventListener("click", showImportForm);
$("#export-json-button").addEventListener("click", () => exportTransactions("json"));
$("#export-csv-button").addEventListener("click", () => exportTransactions("csv"));
$("#trash-button").addEventListener("click", showTrash);
$("#load-more").addEventListener("click", () => { state.transactionPage += 1; loadTransactions(false); });
$("#apply-dates").addEventListener("click", loadOverview);
$("#connection-button").addEventListener("click", () => showView("settings"));
$("#dialog-close").addEventListener("click", () => $("#detail-dialog").close());
$("#settings-form").addEventListener("submit", async event => {
  event.preventDefault();
  sessionStorage.setItem("financial-beancount-api", $("#api-base").value.trim().replace(/\/$/, ""));
  sessionStorage.setItem("financial-beancount-token", $("#api-token").value.trim());
  localStorage.setItem("financial-beancount-actor", $("#review-actor").value.trim() || "local-user");
  try { await request("/api/v1/health"); toast("连接成功"); showView("overview"); } catch (error) { toast(error.message); }
});
$("#detail-dialog").addEventListener("submit", async event => {
  const form = event.target.closest("[data-modify-form]");
  if (!form) return;
  event.preventDefault();
  const submit = form.querySelector("button[type='submit']");
  submit.disabled = true;
  const changes = Object.fromEntries([...new FormData(form).entries()].map(([key, value]) => [key, text(value).trim() || null]));
  const action = form.dataset.kind === "match" ? "confirm" : "modify";
  try {
    await request(`${form.dataset.endpoint}/${action}`, { method: "POST", body: JSON.stringify({ actor: actor(), changes }) });
    $("#detail-dialog").close();
    toast("修正已保存，并写入完整审计记录");
    await loadReviews();
  } catch (error) { toast(error.message); submit.disabled = false; }
});
$("#detail-dialog").addEventListener("submit", async event => {
  const form = event.target.closest("[data-transaction-create], [data-transaction-edit], [data-statement-import]");
  if (!form) return;
  event.preventDefault();
  const submit = form.querySelector("button[type='submit']"); submit.disabled = true;
  try {
    if (form.matches("[data-statement-import]")) {
      const values = new FormData(form); const file = values.get("statement");
      const result = await request("/api/v1/imports", { method: "POST", body: JSON.stringify({ format_id: values.get("format_id"), source_account: values.get("source_account"), filename: file.name, content_base64: await fileAsBase64(file) }) });
      toast(`已解析 ${result.data.parsed_count} 条，${result.data.pending_review_count} 条待审核`);
      state.reviewType = "imports";
    } else if (form.matches("[data-transaction-create]")) {
      const values = Object.fromEntries(new FormData(form));
      values.actor = actor(); values.tx_type = values.direction === "expense" ? "expense" : "income";
      await request("/api/v1/transactions", { method: "POST", body: JSON.stringify(values) }); toast("交易已新增并记录审计事件");
    } else {
      const changes = Object.fromEntries(new FormData(form));
      await request(form.dataset.endpoint, { method: "PATCH", body: JSON.stringify({ actor: actor(), changes }) }); toast("交易修改已记录");
    }
    $("#detail-dialog").close(); await loadTransactions(true); await refreshCounts();
  } catch (error) { toast(error.message); submit.disabled = false; }
});
$("#detail-dialog").addEventListener("click", async event => {
  const restore = event.target.closest("[data-restore]");
  if (restore) {
    try {
      await request(`/api/v1/transactions/${restore.dataset.restore}/restore`, { method: "POST", body: JSON.stringify({ actor: actor() }) });
      toast("交易已恢复并记录审计事件"); await showTrash(); await loadTransactions(true);
    } catch (error) { toast(error.message); }
    return;
  }
  const button = event.target.closest("[data-soft-delete]"); if (!button) return;
  const form = button.closest("[data-transaction-edit]");
  if (!confirm("移除这条唯一交易？所有原始来源与审计记录都会保留。")) return;
  try {
    await request(form.dataset.endpoint, { method: "DELETE", body: JSON.stringify({ actor: actor(), reason: "user_deleted" }) });
    $("#detail-dialog").close(); toast("交易已软删除，可通过 API 恢复"); await loadTransactions(true);
  } catch (error) { toast(error.message); }
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js").catch(() => {});
request("/api/v1/health").then(() => loadOverview()).catch(error => { setConnection(false); toast(error.message); loadOverview(); });
