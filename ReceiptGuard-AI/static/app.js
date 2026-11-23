const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const esc = (val) =>
  String(val ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const fmtMoney = (val, cur = "TRY") => {
  const num = Number(val || 0);
  return `${num.toLocaleString("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${esc(cur)}`;
};

async function api(url, options = {}) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}

// ------------------------------------------------------------------
// Sekme Geçişleri
// ------------------------------------------------------------------
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "dashboard") loadDashboard();
    if (btn.dataset.tab === "documents") loadDocuments();
  });
});

// ------------------------------------------------------------------
// Sistem Durumu & Ayarlar
// ------------------------------------------------------------------
async function loadStatus() {
  try {
    const st = await api("/api/status");
    const badges = [];
    const ol = st.ollama;
    if (ol.running) {
      badges.push(`<span class="badge badge-ok">Ollama Aktif (${ol.recommended_llm})</span>`);
      if (ol.vision_models.length > 0) {
        badges.push(`<span class="badge badge-ok">VLM: ${ol.vision_models[0]}</span>`);
      } else if (st.active_config.has_gemini_key || st.active_config.has_openai_key) {
        badges.push(`<span class="badge badge-info">VLM: Bulut API</span>`);
      } else {
        badges.push(`<span class="badge badge-warn" title="ollama pull ${st.active_config.ollama_vlm_model}">VLM Yok (PDF/Manuel hazır)</span>`);
      }
    } else {
      badges.push(`<span class="badge badge-err">Ollama Kapalı</span>`);
    }
    badges.push(`<span class="badge badge-info">RAG: ${st.rag.total_chunks} parça</span>`);
    $("#status-badges").innerHTML = badges.join("");

    // Modal alanlarını doldur
    $("#s-llm-provider").value = st.active_config.llm_provider;
    $("#s-vlm-provider").value = st.active_config.vlm_provider;
    $("#s-ollama-llm").value = st.active_config.ollama_llm_model;
    $("#s-ollama-vlm").value = st.active_config.ollama_vlm_model;
    $("#s-openai-url").value = st.active_config.openai_base_url;

    const diag = $("#ollama-diagnostic");
    if (ol.running) {
      const vlmMsg = ol.vision_models.length
        ? `Görsel modeller: <b>${ol.vision_models.join(", ")}</b>`
        : `Görsel (VLM) model henüz yüklü değil. Görsel fiş okumak için terminalde <code>ollama pull ${st.active_config.ollama_vlm_model}</code> çalıştırabilir veya aşağıdan API anahtarı ekleyebilirsiniz.`;
      diag.className = "banner " + (ol.vision_models.length ? "ok" : "warn");
      diag.innerHTML = `Yüklü Ollama modelleri: <b>${ol.models.join(", ") || "yok"}</b>.<br>${vlmMsg}`;
    } else {
      diag.className = "banner err";
      diag.textContent = "Ollama sunucusuna (127.0.0.1:11434) ulaşılamıyor. Ollama uygulamasını veya 'ollama serve' komutunu başlatın.";
    }
  } catch (err) {
    $("#status-badges").innerHTML = `<span class="badge badge-err">Durum alınamadı</span>`;
  }
}

$("#btn-open-settings").addEventListener("click", () => {
  loadStatus();
  $("#settings-modal").classList.remove("hidden");
});
$("#btn-close-settings").addEventListener("click", () => $("#settings-modal").classList.add("hidden"));

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      llm_provider: $("#s-llm-provider").value,
      vlm_provider: $("#s-vlm-provider").value,
      ollama_llm_model: $("#s-ollama-llm").value,
      ollama_vlm_model: $("#s-ollama-vlm").value,
      gemini_api_key: $("#s-gemini-key").value,
      openai_api_key: $("#s-openai-key").value,
      openai_base_url: $("#s-openai-url").value,
    }),
  });
  $("#settings-modal").classList.add("hidden");
  await loadStatus();
});

// ------------------------------------------------------------------
// Dashboard
// ------------------------------------------------------------------
async function loadDashboard() {
  const d = await api("/api/dashboard");
  $("#kpi-total-spend").textContent = fmtMoney(d.total_spend);
  $("#kpi-month-spend").textContent = fmtMoney(d.month_spend);
  $("#kpi-doc-count").textContent = String(d.doc_count);
  $("#kpi-expiring").textContent = String(d.expiring_30_days);

  // Kategori barları
  const catEl = $("#chart-categories");
  if (!d.by_category.length) {
    catEl.innerHTML = `<p class="empty-msg">Henüz kayıtlı harcama yok.</p>`;
  } else {
    const maxCat = Math.max(...d.by_category.map((c) => c.total), 1);
    catEl.innerHTML = d.by_category
      .map((c) => {
        const pct = Math.round((c.total / maxCat) * 100);
        return `
          <div class="bar-row">
            <div class="bar-meta"><span>${c.category} (${c.count})</span><strong>${fmtMoney(c.total)}</strong></div>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
          </div>`;
      })
      .join("");
  }

  // Aylık barlar
  const monEl = $("#chart-months");
  if (!d.by_month.length) {
    monEl.innerHTML = `<p class="empty-msg">Henüz aylık veri yok.</p>`;
  } else {
    const maxMon = Math.max(...d.by_month.map((m) => m.total), 1);
    monEl.innerHTML = d.by_month
      .map((m) => {
        const pct = Math.round((m.total / maxMon) * 100);
        return `
          <div class="bar-row">
            <div class="bar-meta"><span>${m.month} (${m.count} belge)</span><strong>${fmtMoney(m.total)}</strong></div>
            <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
          </div>`;
      })
      .join("");
  }

  // Garanti tablosu
  const tbody = $("#warranty-tbody");
  if (!d.warranties.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-msg">Garanti bitiş tarihi girilmiş ürün bulunmuyor.</td></tr>`;
  } else {
    const statusMap = {
      expired: `<span class="badge badge-err">Süresi Dolmuş</span>`,
      expiring_soon: `<span class="badge badge-warn">Acil (<=30 gün)</span>`,
      watch: `<span class="badge badge-info">Yaklaşıyor</span>`,
      active: `<span class="badge badge-ok">Aktif</span>`,
    };
    tbody.innerHTML = d.warranties
      .map(
        (w) => `
      <tr>
        <td><strong>${esc(w.merchant_name)}</strong><br><span class="doc-card-meta">${esc(w.summary || w.file_name)}</span></td>
        <td>${esc(w.document_date || "-")}</td>
        <td>${w.warranty_months ? esc(w.warranty_months) + " ay" : "-"}</td>
        <td>${esc(w.warranty_end_date)}</td>
        <td>${w.days_left !== null ? esc(w.days_left) + " gün" : "-"}</td>
        <td>${statusMap[w.status] || ""}</td>
      </tr>`
      )
      .join("");
  }
}

// ------------------------------------------------------------------
// Belge Yükleme & Önizleme Formu
// ------------------------------------------------------------------
const dropzone = $("#dropzone");
const fileInput = $("#file-input");

$("#btn-choose-file").addEventListener("click", () => fileInput.click());
dropzone.addEventListener("click", (e) => {
  if (e.target.id !== "btn-choose-file") fileInput.click();
});
dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files[0]) handleUploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) handleUploadFile(fileInput.files[0]);
});

function renderItemRows(items = []) {
  const container = $("#items-list");
  container.innerHTML = "";
  items.forEach((it) => addItemRow(it));
}

function addItemRow(item = {}) {
  const row = document.createElement("div");
  row.className = "item-row";
  row.innerHTML = `
    <input type="text" class="it-name" placeholder="Ürün adı" value="${item.name || ""}" required />
    <input type="number" step="0.01" class="it-qty" placeholder="Adet" value="${item.quantity ?? 1}" />
    <input type="number" step="0.01" class="it-price" placeholder="Toplam" value="${item.total_price ?? item.unit_price ?? ""}" />
    <input type="number" class="it-warr" placeholder="Garanti(ay)" value="${item.warranty_months ?? ""}" />
    <button type="button" class="btn btn-sm btn-danger">Sil</button>
  `;
  row.querySelector("button").addEventListener("click", () => row.remove());
  $("#items-list").appendChild(row);
}

$("#btn-add-item").addEventListener("click", () => addItemRow());

async function handleUploadFile(file) {
  const banner = $("#extract-banner");
  banner.className = "banner";
  banner.textContent = "Dosya analiz ediliyor (VLM / PDF + LLM çıkarımı)...";
  banner.classList.remove("hidden");

  const fd = new FormData();
  fd.append("file", file);

  try {
    const res = await api("/api/documents/extract", { method: "POST", body: fd });
    if (res.status === "duplicate") {
      banner.className = "banner warn";
      banner.textContent = res.message;
    } else if (res.status === "needs_manual_review") {
      banner.className = "banner warn";
      banner.textContent = res.message;
    } else {
      banner.className = "banner ok";
      banner.textContent = res.message;
    }

    $("#preview-workspace").classList.remove("hidden");
    const savedBasename = res.file_path.split(/[\\/]/).pop();
    const previewUrl = `/api/uploads/${encodeURIComponent(savedBasename)}`;
    const previewBox = $("#file-preview-container");
    if (res.mime_type.includes("pdf") || res.file_name.toLowerCase().endsWith(".pdf")) {
      previewBox.innerHTML = `<iframe src="${previewUrl}"></iframe>`;
    } else {
      previewBox.innerHTML = `<img src="${previewUrl}" alt="Belge Önizleme" />`;
    }

    const ex = res.extracted;
    $("#f-file-name").value = res.file_name;
    $("#f-file-path").value = res.file_path;
    $("#f-file-hash").value = res.file_hash;
    $("#f-mime-type").value = res.mime_type;
    $("#f-extraction-method").value = res.extraction_method;

    $("#f-document-type").value = ex.document_type || "fis";
    $("#f-category").value = ex.category || "Diğer";
    $("#f-merchant-name").value = ex.merchant_name || "";
    $("#f-document-date").value = ex.document_date || "";
    $("#f-total-amount").value = ex.total_amount ?? "";
    $("#f-vat-amount").value = ex.vat_amount ?? "";
    $("#f-currency").value = ex.currency || "TRY";
    $("#f-warranty-months").value = ex.warranty_months ?? "";
    $("#f-warranty-end-date").value = ex.warranty_end_date || "";
    $("#f-summary").value = ex.summary || "";
    $("#f-warranty-terms").value = ex.warranty_terms || "";
    $("#f-raw-text").value = ex.raw_text || "";
    renderItemRows(ex.items || []);
  } catch (err) {
    banner.className = "banner err";
    banner.textContent = `Hata: ${err.message}`;
  }
}

$("#extract-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const items = $$("#items-list .item-row").map((r) => ({
    name: r.querySelector(".it-name").value,
    quantity: Number(r.querySelector(".it-qty").value || 1),
    total_price: r.querySelector(".it-price").value ? Number(r.querySelector(".it-price").value) : null,
    warranty_months: r.querySelector(".it-warr").value ? Number(r.querySelector(".it-warr").value) : null,
  }));

  const payload = {
    file_name: $("#f-file-name").value,
    file_path: $("#f-file-path").value,
    file_hash: $("#f-file-hash").value,
    mime_type: $("#f-mime-type").value,
    extraction_method: $("#f-extraction-method").value,
    document_type: $("#f-document-type").value,
    category: $("#f-category").value,
    merchant_name: $("#f-merchant-name").value,
    document_date: $("#f-document-date").value || null,
    total_amount: $("#f-total-amount").value ? Number($("#f-total-amount").value) : null,
    vat_amount: $("#f-vat-amount").value ? Number($("#f-vat-amount").value) : null,
    currency: $("#f-currency").value,
    warranty_months: $("#f-warranty-months").value ? Number($("#f-warranty-months").value) : null,
    warranty_end_date: $("#f-warranty-end-date").value || null,
    summary: $("#f-summary").value,
    warranty_terms: $("#f-warranty-terms").value,
    raw_text: $("#f-raw-text").value,
    items,
  };

  try {
    const res = await api("/api/documents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const banner = $("#extract-banner");
    banner.className = "banner ok";
    banner.textContent = `Belge #${res.document.id} (${res.document.merchant_name}) SQLite ve RAG indeksine kaydedildi!`;
    await loadStatus();
    await loadDashboard();
  } catch (err) {
    alert(`Kayıt hatası: ${err.message}`);
  }
});

// ------------------------------------------------------------------
// Belgeler Arşivi
// ------------------------------------------------------------------
async function loadDocuments() {
  const params = new URLSearchParams();
  if ($("#doc-search").value.trim()) params.set("search", $("#doc-search").value.trim());
  if ($("#doc-filter-category").value) params.set("category", $("#doc-filter-category").value);
  if ($("#doc-filter-type").value) params.set("document_type", $("#doc-filter-type").value);

  const data = await api(`/api/documents?${params.toString()}`);
  const grid = $("#documents-list");
  if (!data.documents.length) {
    grid.innerHTML = `<p class="empty-msg">Eşleşen belge bulunamadı.</p>`;
    return;
  }

  grid.innerHTML = data.documents
    .map(
      (doc) => `
    <div class="doc-card">
      <div class="doc-card-top">
        <div>
          <div class="doc-card-title">${esc(doc.merchant_name)}</div>
          <div class="doc-card-meta">${esc(doc.document_date || "Tarihsiz")} • ${esc(doc.document_type)}</div>
        </div>
        <span class="badge badge-info">${esc(doc.category)}</span>
      </div>
      <div><strong>${doc.total_amount !== null ? fmtMoney(doc.total_amount, doc.currency) : "-"}</strong></div>
      <div class="doc-card-meta">${esc(doc.summary || doc.file_name)}</div>
      ${doc.warranty_end_date ? `<div class="doc-card-meta">Garanti Bitiş: <strong>${esc(doc.warranty_end_date)}</strong></div>` : ""}
      <div class="doc-card-actions">
        <button class="btn btn-sm btn-secondary" onclick="openDocDetail(${Number(doc.id)})">İncele</button>
        <button class="btn btn-sm btn-danger" onclick="deleteDoc(${Number(doc.id)})">Sil</button>
      </div>
    </div>`
    )
    .join("");
}

window.openDocDetail = async (id) => {
  const doc = await api(`/api/documents/${id}`);
  $("#detail-title").textContent = `#${doc.id} — ${doc.merchant_name}`;
  const isImage = (doc.mime_type || "").startsWith("image/");
  const isPdf = (doc.mime_type || "").includes("pdf");
  const fileUrl = `/api/documents/${Number(id)}/file`;

  let leftHtml = `<pre class="sql-box" style="white-space:pre-wrap">${esc(doc.raw_text || "Ham metin yok")}</pre>`;
  if (isImage) leftHtml = `<img src="${fileUrl}" style="max-width:100%;border-radius:8px" />`;
  else if (isPdf) leftHtml = `<iframe src="${fileUrl}" style="width:100%;height:420px;border:none"></iframe>`;

  const itemsHtml = (doc.items || [])
    .map((it) => `<li>${esc(it.name)} (${esc(it.quantity)} adet) — ${esc(it.total_price ?? "-")} ${esc(doc.currency)}</li>`)
    .join("");

  $("#detail-body").innerHTML = `
    <div>${leftHtml}</div>
    <div>
      <p><b>Belge Tipi:</b> ${esc(doc.document_type)} | <b>Kategori:</b> ${esc(doc.category)}</p>
      <p><b>Tarih:</b> ${esc(doc.document_date || "-")} | <b>Toplam:</b> ${fmtMoney(doc.total_amount, doc.currency)}</p>
      <p><b>Garanti:</b> ${doc.warranty_months ? esc(doc.warranty_months) + " ay" : "-"} (Bitiş: ${esc(doc.warranty_end_date || "-")})</p>
      <p><b>Özet:</b> ${esc(doc.summary || "-")}</p>
      <p><b>Garanti Şartları:</b><br>${esc(doc.warranty_terms || "-")}</p>
      <p><b>Kalemler:</b></p>
      <ul>${itemsHtml || "<li>Kalem yok</li>"}</ul>
    </div>
  `;
  $("#doc-detail-modal").classList.remove("hidden");
};

window.deleteDoc = async (id) => {
  if (!confirm("Bu belgeyi veritabanından ve RAG indeksinden silmek istiyor musunuz?")) return;
  await api(`/api/documents/${id}`, { method: "DELETE" });
  await loadDocuments();
  await loadDashboard();
  await loadStatus();
};

$("#btn-close-detail").addEventListener("click", () => $("#doc-detail-modal").classList.add("hidden"));
$("#btn-refresh-docs").addEventListener("click", loadDocuments);
$("#doc-filter-category").addEventListener("change", loadDocuments);
$("#doc-filter-type").addEventListener("change", loadDocuments);

// ------------------------------------------------------------------
// Hibrit AI Sohbet
// ------------------------------------------------------------------
function appendChatMessage(role, content, meta = null) {
  const box = $("#chat-messages");
  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}`;

  const body = document.createElement("div");
  body.className = "msg-body";
  body.textContent = content;
  wrap.appendChild(body);

  if (meta && role === "assistant") {
    const m = document.createElement("div");
    m.className = "msg-meta";
    const routeBadge = `<span class="badge badge-info">Rota: ${esc((meta.route_used || "").toUpperCase())}</span>`;
    const timeBadge = `<span class="badge badge-muted">${esc(meta.latency_ms)} ms • ${esc(meta.model_used)}</span>`;
    m.innerHTML = `<div style="display:flex;gap:6px;flex-wrap:wrap">${routeBadge}${timeBadge}</div>`;

    if (meta.sql_query) {
      const det = document.createElement("details");
      det.innerHTML = `<summary style="cursor:pointer">Çalıştırılan Güvenli SQL Sorgusu</summary><div class="sql-box">${esc(meta.sql_query)}</div>`;
      m.appendChild(det);
    }

    if (meta.sources && meta.sources.length) {
      const srcDiv = document.createElement("div");
      srcDiv.className = "source-chips";
      meta.sources.forEach((s) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "source-chip";
        chip.textContent = `#${s.document_id} ${s.merchant_name} (${Math.round(s.score * 100)}%)`;
        chip.addEventListener("click", () => window.openDocDetail(s.document_id));
        srcDiv.appendChild(chip);
      });
      m.appendChild(srcDiv);
    }
    wrap.appendChild(m);
  }

  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
}

async function sendChat(question) {
  appendChatMessage("user", question);
  const btn = $("#btn-send-chat");
  btn.disabled = true;
  btn.textContent = "Düşünüyor...";

  try {
    const res = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    appendChatMessage("assistant", res.answer, res);
  } catch (err) {
    appendChatMessage("assistant", `Hata: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Gönder";
  }
}

$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("#chat-input").value.trim();
  if (!q) return;
  $("#chat-input").value = "";
  sendChat(q);
});

$$(".prompt-chip").forEach((chip) => {
  chip.addEventListener("click", () => sendChat(chip.dataset.q));
});

$("#btn-clear-chat").addEventListener("click", async () => {
  await api("/api/chat/history", { method: "DELETE" });
  $("#chat-messages").innerHTML = "";
});

$("#btn-seed-demo").addEventListener("click", async () => {
  const res = await api("/api/demo/seed", { method: "POST" });
  alert(`${res.inserted_count} yeni örnek belge SQLite ve RAG sistemine eklendi.`);
  await loadDashboard();
  await loadDocuments();
  await loadStatus();
});

// Başlangıç yüklemesi
loadStatus();
loadDashboard();
loadDocuments();
