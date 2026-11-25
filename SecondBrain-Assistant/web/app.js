const state = {
  inputMode: "url",
  notes: [],
  activeNote: null,
  status: null,
  allCardsRevealed: false,
};

const el = (id) => document.getElementById(id);

function resetPipelineUI(message) {
  ["ingestor", "synthesizer", "archivist"].forEach((stage) => {
    el(`node-${stage}`).dataset.state = "idle";
  });
  el("edge-1").dataset.state = "idle";
  el("edge-2").dataset.state = "idle";
  const statusEl = el("pipelineStatusText");
  statusEl.classList.remove("is-error");
  statusEl.textContent =
    message || "Hazır — bir YouTube linki, makale URL'si veya metin girerek ajanları çalıştır.";
}

function applyPipelineEvent(ev) {
  const statusEl = el("pipelineStatusText");
  statusEl.textContent = ev.message;

  if (ev.stage === "ingestor") {
    el("node-ingestor").dataset.state = ev.status;
    if (ev.status === "done") el("edge-1").dataset.state = "running";
  } else if (ev.stage === "synthesizer") {
    el("edge-1").dataset.state = "done";
    el("node-synthesizer").dataset.state = ev.status;
    if (ev.status === "done") el("edge-2").dataset.state = "running";
  } else if (ev.stage === "archivist") {
    el("edge-2").dataset.state = "done";
    el("node-archivist").dataset.state = ev.status;
  } else if (ev.stage === "complete") {
    el("edge-1").dataset.state = "done";
    el("edge-2").dataset.state = "done";
    el("node-archivist").dataset.state = "done";
  } else if (ev.stage === "error") {
    statusEl.classList.add("is-error");
    ["ingestor", "synthesizer", "archivist"].forEach((s) => {
      if (el(`node-${s}`).dataset.state === "running") {
        el(`node-${s}`).dataset.state = "error";
      }
    });
  }
}

async function fetchStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();
  state.status = data;

  const gemPill = el("geminiPill");
  if (data.gemini_configured) {
    gemPill.textContent = `Gemini: Hazır (${data.gemini_model})`;
    gemPill.className = "pill pill-ok";
  } else {
    gemPill.textContent = "Gemini: .env Anahtarı Gerekli";
    gemPill.className = "pill pill-warn";
  }

  const tgPill = el("telegramPill");
  if (data.telegram_running) {
    tgPill.textContent = "Telegram Bot: Aktif";
    tgPill.className = "pill pill-ok";
  } else if (data.telegram_configured) {
    tgPill.textContent = "Telegram Bot: Hata";
    tgPill.className = "pill pill-warn";
  } else {
    tgPill.textContent = "Telegram: Opsiyonel (Kapalı)";
    tgPill.className = "pill pill-muted";
  }

  const total = data.stats?.total_notes ?? 0;
  el("statsPill").textContent = `${total} Not`;
  el("modalPathsInfo").innerHTML = `<strong>Aktif Not Klasörü:</strong> <code>${escapeHtml(
    data.notes_dir
  )}</code>`;

  renderCategoryOptions(data.stats?.categories || []);
}

function renderCategoryOptions(categories) {
  const sel = el("categoryFilter");
  const prev = sel.value;
  sel.innerHTML = '<option value="">Tüm Kategoriler</option>';
  categories.forEach((cat) => {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = cat;
    sel.appendChild(opt);
  });
  sel.value = prev;
}

async function loadNotes() {
  const params = new URLSearchParams();
  const q = el("searchInput").value.trim();
  const sourceType = el("typeFilter").value;
  const category = el("categoryFilter").value;
  if (q) params.set("q", q);
  if (sourceType) params.set("source_type", sourceType);
  if (category) params.set("category", category);

  const res = await fetch(`/api/notes?${params.toString()}`);
  const data = await res.json();
  state.notes = data.notes || [];
  renderCategoryOptions(data.stats?.categories || []);
  el("statsPill").textContent = `${data.stats?.total_notes ?? state.notes.length} Not`;
  renderNotesList();
}

function sourceLabel(sourceType) {
  return { youtube: "YouTube", article: "Makale", text: "Metin" }[sourceType] || sourceType;
}

function renderNotesList() {
  const container = el("notesList");
  if (!state.notes.length) {
    container.innerHTML =
      '<p class="helper-text">Henüz eşleşen bir öğrenme notu bulunmuyor.</p>';
    return;
  }

  container.innerHTML = "";
  state.notes.forEach((note) => {
    const item = document.createElement("div");
    item.className =
      "note-item" + (state.activeNote && state.activeNote.id === note.id ? " active" : "");
    item.innerHTML = `
      <div class="note-item-title">${escapeHtml(note.title)}</div>
      <div class="note-item-meta">${escapeHtml(sourceLabel(note.source_type))} · ${escapeHtml(
      note.category
    )} · ${escapeHtml(note.created_at.slice(0, 10))}</div>
      <div class="note-item-tldr">${escapeHtml(note.tldr)}</div>
    `;
    item.addEventListener("click", () => selectNote(note));
    container.appendChild(item);
  });
}

function selectNote(note) {
  state.activeNote = note;
  state.allCardsRevealed = false;
  el("toggleAllCardsBtn").textContent = "Tüm Cevapları Göster";
  renderNotesList();

  el("emptyDetail").classList.add("hidden");
  el("noteDetail").classList.remove("hidden");

  el("detailTypeBadge").textContent = sourceLabel(note.source_type);
  el("detailCategoryBadge").textContent = note.category;
  el("detailReadBadge").textContent = `${note.estimated_read_minutes} dk okuma`;
  el("detailTitle").textContent = note.title;
  el("detailMeta").textContent = `${note.author || "Bilinmiyor"} · ${note.created_at}`;

  const srcLink = el("detailSourceLink");
  if (note.source_url) {
    srcLink.href = note.source_url;
    srcLink.classList.remove("hidden");
  } else {
    srcLink.classList.add("hidden");
  }
  el("detailDownloadBtn").href = `/api/notes/${note.id}/markdown`;

  const tagsRow = el("detailTags");
  tagsRow.innerHTML = "";
  (note.tags || []).forEach((tag) => {
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    chip.textContent = `#${tag}`;
    chip.title = "Bu etikete göre filtrele";
    chip.addEventListener("click", () => {
      el("searchInput").value = tag;
      loadNotes();
    });
    tagsRow.appendChild(chip);
  });

  el("detailTldr").textContent = note.tldr;

  const kpList = el("detailKeyPoints");
  kpList.innerHTML = "";
  (note.key_points || []).forEach((kp) => {
    const li = document.createElement("li");
    li.textContent = kp;
    kpList.appendChild(li);
  });

  const secContainer = el("detailSections");
  secContainer.innerHTML = "";
  (note.detailed_sections || []).forEach((sec) => {
    const card = document.createElement("div");
    card.className = "section-card";
    card.innerHTML = `<h4>${escapeHtml(sec.heading)}</h4><p>${escapeHtml(sec.content)}</p>`;
    secContainer.appendChild(card);
  });
  el("detailSectionsWrap").classList.toggle("hidden", !(note.detailed_sections || []).length);

  const actList = el("detailActionItems");
  actList.innerHTML = "";
  (note.action_items || []).forEach((act) => {
    const li = document.createElement("li");
    li.innerHTML = `<span>☐</span><span>${escapeHtml(act)}</span>`;
    actList.appendChild(li);
  });
  el("detailActionsWrap").classList.toggle("hidden", !(note.action_items || []).length);

  const toolsRow = el("detailTools");
  toolsRow.innerHTML = "";
  (note.code_or_tools || []).forEach((tool) => {
    const codeEl = document.createElement("code");
    codeEl.textContent = tool;
    toolsRow.appendChild(codeEl);
  });
  el("detailToolsWrap").classList.toggle("hidden", !(note.code_or_tools || []).length);

  const fcGrid = el("flashcardsGrid");
  fcGrid.innerHTML = "";
  (note.review_questions || []).forEach((qa, idx) => {
    const card = document.createElement("div");
    card.className = "flashcard";
    card.innerHTML = `
      <div class="flashcard-q">${idx + 1}. ${escapeHtml(qa.question)}</div>
      <div class="flashcard-a">${escapeHtml(qa.answer)}</div>
    `;
    card.addEventListener("click", () => card.classList.toggle("revealed"));
    fcGrid.appendChild(card);
  });

  el("markdownPathLabel").textContent = note.markdown_path;
  el("markdownPreview").textContent = note.markdown_content;

  renderTranscript(note);

  el("chatMessages").innerHTML =
    '<div class="chat-msg assistant">Bu notla ilgili aklına takılan bir detayı veya örnek senaryoyu sorabilirsin.</div>';
}

function renderTranscript(note) {
  const container = el("transcriptContent");
  const statsEl = el("transcriptStatsLabel");
  const dlBtn = el("downloadTranscriptBtn");
  const copyBtn = el("copyTranscriptBtn");
  const raw = (note.cleaned_transcript || "").trim();

  if (!raw) {
    statsEl.textContent = "Düzenlenmiş transkript yok (eski kayıt olabilir).";
    dlBtn.classList.add("hidden");
    copyBtn.classList.add("hidden");
    container.innerHTML =
      '<p class="helper-text">Bu not için düzenlenmiş transkript kaydedilmemiş.</p>';
    return;
  }

  const wordCount = raw.split(/\s+/).filter(Boolean).length;
  statsEl.textContent = `Yaklaşık ${wordCount} kelime · ${raw.length} karakter`;
  dlBtn.href = `/api/notes/${note.id}/transcript`;
  dlBtn.classList.remove("hidden");
  copyBtn.classList.remove("hidden");

  const blocks = raw.split(/\n{2,}/);
  container.innerHTML = blocks
    .map((block) => {
      const trimmed = block.trim();
      if (trimmed.startsWith("### ")) {
        return `<h3>${escapeHtml(trimmed.slice(4))}</h3>`;
      }
      if (trimmed.startsWith("## ")) {
        return `<h3>${escapeHtml(trimmed.slice(3))}</h3>`;
      }
      return `<p>${escapeHtml(trimmed).replaceAll("\n", "<br />")}</p>`;
    })
    .join("");
}

async function runSummarizeStream(payload) {
  const btn = el("submitBtn");
  btn.disabled = true;
  btn.textContent = "Ajanlar Çalışıyor...";
  resetPipelineUI("İşlem başlatılıyor...");

  try {
    const res = await fetch("/api/summarize/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok || !res.body) {
      throw new Error(`Sunucu hatası (${res.status})`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.slice(5).trim();
        if (!jsonStr) continue;
        const ev = JSON.parse(jsonStr);
        applyPipelineEvent(ev);
        if (ev.stage === "complete" && ev.data?.note) {
          await loadNotes();
          selectNote(ev.data.note);
          await fetchStatus();
        }
      }
    }
  } catch (err) {
    applyPipelineEvent({ stage: "error", status: "error", message: String(err) });
  } finally {
    btn.disabled = false;
    btn.textContent = "Ajanları Çalıştır";
  }
}

async function loadChannels() {
  const res = await fetch("/api/channels");
  const data = await res.json();
  const list = el("channelsList");
  list.innerHTML = "";
  (data.channels || []).forEach((ch) => {
    const row = document.createElement("div");
    row.className = "channel-row";
    row.innerHTML = `
      <div>
        <div style="font-weight:600;font-size:0.86rem;">${escapeHtml(ch.title)}</div>
        <div style="font-size:0.74rem;color:var(--muted);">${escapeHtml(ch.handle_or_url)}</div>
      </div>
      <div style="display:flex;gap:6px;">
        <button class="btn btn-secondary btn-sm" data-videos="${ch.id}" type="button">Videolar</button>
        <button class="btn btn-danger btn-sm" data-del-ch="${ch.id}" type="button">Sil</button>
      </div>
    `;
    row.querySelector(`[data-videos="${ch.id}"]`).addEventListener("click", () =>
      loadChannelVideos(ch)
    );
    row.querySelector(`[data-del-ch="${ch.id}"]`).addEventListener("click", async () => {
      await fetch(`/api/channels/${ch.id}`, { method: "DELETE" });
      await loadChannels();
    });
    list.appendChild(row);
  });
}

async function loadChannelVideos(channel) {
  const box = el("channelVideosBox");
  const list = el("channelVideosList");
  el("channelVideosTitle").textContent = `${channel.title} — Son Videolar`;
  box.classList.remove("hidden");
  list.innerHTML = '<p class="helper-text">RSS akışı okunuyor...</p>';

  const res = await fetch(`/api/channels/${channel.id}/videos`);
  const data = await res.json();
  if (!res.ok) {
    list.innerHTML = `<p class="helper-text">${escapeHtml(data.detail || "Alınamadı")}</p>`;
    return;
  }

  list.innerHTML = "";
  (data.videos || []).forEach((v) => {
    const item = document.createElement("div");
    item.className = "video-item";
    item.innerHTML = `
      <div class="video-item-title">${escapeHtml(v.title)}</div>
      <button class="btn btn-primary btn-sm" style="flex:0 0 auto;" type="button">Özetle</button>
    `;
    item.querySelector("button").addEventListener("click", () => {
      switchInputMode("url");
      el("sourceUrl").value = v.url;
      runSummarizeStream({
        url: v.url,
        focus: el("focusInput").value.trim() || null,
      });
    });
    list.appendChild(item);
  });
}

function switchInputMode(mode) {
  state.inputMode = mode;
  document.querySelectorAll("[data-input-mode]").forEach((b) => {
    b.classList.toggle("active", b.dataset.inputMode === mode);
  });
  el("urlInputGroup").classList.toggle("hidden", mode !== "url");
  el("textInputGroup").classList.toggle("hidden", mode !== "text");
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setupEventListeners() {
  document.querySelectorAll("[data-input-mode]").forEach((btn) => {
    btn.addEventListener("click", () => switchInputMode(btn.dataset.inputMode));
  });

  document.querySelectorAll("[data-side-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.sideTab;
      document.querySelectorAll("[data-side-tab]").forEach((b) => {
        b.classList.toggle("active", b.dataset.sideTab === target);
      });
      el("archivePane").classList.toggle("hidden", target !== "archive");
      el("channelsPane").classList.toggle("hidden", target !== "channels");
      if (target === "channels") loadChannels();
    });
  });

  document.querySelectorAll("[data-detail-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.detailTab;
      document.querySelectorAll("[data-detail-tab]").forEach((b) => {
        b.classList.toggle("active", b.dataset.detailTab === target);
      });
      ["summary", "transcript", "flashcards", "markdown", "chat"].forEach((pane) => {
        el(`tab-${pane}`).classList.toggle("hidden", pane !== target);
      });
    });
  });

  el("summarizeForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const focus = el("focusInput").value.trim() || null;
    if (state.inputMode === "url") {
      const url = el("sourceUrl").value.trim();
      if (!url) return;
      runSummarizeStream({ url, focus });
    } else {
      const text = el("sourceText").value.trim();
      const title = el("sourceTitle").value.trim() || null;
      if (!text) return;
      runSummarizeStream({ text, title, focus });
    }
  });

  el("sampleBtn").addEventListener("click", () => {
    switchInputMode("text");
    el("sourceTitle").value = "AI Agent Otomasyon Mimarisi — Hızlı Tekrar";
    el("sourceText").value =
      "Modern AI ajan sistemleri üç temel katmandan oluşur: veri toplama (ingestor), yapılandırılmış akıl yürütme (synthesizer) ve dış sisteme yazma (archivist). " +
      "Structured Outputs sayesinde LLM çıktıları doğrudan Pydantic şemalarına bağlanır, böylece ajanlar arası veri aktarımı bozulmaz. " +
      "Aktif hatırlama (active recall) soruları öğrenilen bilginin uzun süreli belleğe geçmesini hızlandırır.";
    el("focusInput").value = "Günlük hayatta uygulanabilir öğrenme adımlarına odaklan";
  });

  el("searchInput").addEventListener("input", () => loadNotes());
  el("typeFilter").addEventListener("change", () => loadNotes());
  el("categoryFilter").addEventListener("change", () => loadNotes());

  el("toggleAllCardsBtn").addEventListener("click", () => {
    state.allCardsRevealed = !state.allCardsRevealed;
    document.querySelectorAll("#flashcardsGrid .flashcard").forEach((c) => {
      c.classList.toggle("revealed", state.allCardsRevealed);
    });
    el("toggleAllCardsBtn").textContent = state.allCardsRevealed
      ? "Tüm Cevapları Gizle"
      : "Tüm Cevapları Göster";
  });

  el("copyMarkdownBtn").addEventListener("click", async () => {
    if (!state.activeNote) return;
    await navigator.clipboard.writeText(state.activeNote.markdown_content);
    el("copyMarkdownBtn").textContent = "Kopyalandı!";
    setTimeout(() => {
      el("copyMarkdownBtn").textContent = "Markdown Kopyala";
    }, 1500);
  });

  el("copyTranscriptBtn").addEventListener("click", async () => {
    if (!state.activeNote || !state.activeNote.cleaned_transcript) return;
    await navigator.clipboard.writeText(state.activeNote.cleaned_transcript);
    el("copyTranscriptBtn").textContent = "Kopyalandı!";
    setTimeout(() => {
      el("copyTranscriptBtn").textContent = "Transkripti Kopyala";
    }, 1500);
  });

  el("detailDeleteBtn").addEventListener("click", async () => {
    if (!state.activeNote) return;
    if (!confirm("Bu notu ve .md dosyasını silmek istediğine emin misin?")) return;
    await fetch(`/api/notes/${state.activeNote.id}`, { method: "DELETE" });
    state.activeNote = null;
    el("noteDetail").classList.add("hidden");
    el("emptyDetail").classList.remove("hidden");
    await loadNotes();
    await fetchStatus();
  });

  el("askForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.activeNote) return;
    const question = el("askInput").value.trim();
    if (!question) return;

    const messagesEl = el("chatMessages");
    const userMsg = document.createElement("div");
    userMsg.className = "chat-msg user";
    userMsg.textContent = question;
    messagesEl.appendChild(userMsg);
    el("askInput").value = "";

    const botMsg = document.createElement("div");
    botMsg.className = "chat-msg assistant";
    botMsg.textContent = "Düşünüyor...";
    messagesEl.appendChild(botMsg);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const res = await fetch(`/api/notes/${state.activeNote.id}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Yanıt alınamadı");
      botMsg.textContent = data.answer;
    } catch (err) {
      botMsg.textContent = `Hata: ${err.message}`;
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  });

  el("channelForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const val = el("channelInput").value.trim();
    if (!val) return;
    const res = await fetch("/api/channels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url_or_id: val }),
    });
    const data = await res.json();
    if (!res.ok) {
      alert(data.detail || "Kanal eklenemedi");
      return;
    }
    el("channelInput").value = "";
    await loadChannels();
  });

  el("setupGuideBtn").addEventListener("click", () =>
    el("setupModal").classList.remove("hidden")
  );
  el("closeModalBtn").addEventListener("click", () =>
    el("setupModal").classList.add("hidden")
  );
  el("setupModal").addEventListener("click", (e) => {
    if (e.target === el("setupModal")) el("setupModal").classList.add("hidden");
  });
}

(async function init() {
  setupEventListeners();
  await fetchStatus();
  await loadNotes();
})();
