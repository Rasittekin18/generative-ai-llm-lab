const state = {
  lectures: [],
  activeId: null,
  activeDetail: null,
  pollTimer: null,
  forceAudioPlayer: false,
};

const el = (id) => document.getElementById(id);

function formatTs(seconds) {
  const total = Math.max(0, Math.round(seconds || 0));
  const hrs = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return hrs > 0 ? `${pad(hrs)}:${pad(mins)}:${pad(secs)}` : `${pad(mins)}:${pad(secs)}`;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function seekPlayer(seconds) {
  const sec = Math.max(0, Math.floor(seconds || 0));
  const ytContainer = el("yt-container");
  const ytFrame = el("yt-frame");
  const audio = el("audio-player");

  if (!ytContainer.classList.contains("hidden") && ytFrame.contentWindow) {
    ytFrame.contentWindow.postMessage(
      JSON.stringify({ event: "command", func: "seekTo", args: [sec, true] }),
      "*"
    );
    ytFrame.contentWindow.postMessage(
      JSON.stringify({ event: "command", func: "playVideo", args: [] }),
      "*"
    );
    return;
  }
  if (audio && audio.src) {
    audio.currentTime = sec;
    audio.play().catch(() => {});
  }
}

async function fetchHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    const gpuText = data.cuda_available ? "GPU (CUDA) Aktif" : "CPU Modu";
    const llmText = data.llm_provider === "local" ? "Yerel RAG" : `LLM: ${data.llm_provider}`;
    el("system-badge").textContent = `${gpuText} · ${llmText}`;
  } catch {
    el("system-badge").textContent = "Sunucu bağlantısı kontrol ediliyor...";
  }
}

async function loadLectures() {
  const res = await fetch("/api/lectures");
  state.lectures = await res.json();
  renderLectureList();
}

function renderLectureList() {
  const list = el("lecture-list");
  if (!state.lectures.length) {
    list.innerHTML = '<div class="empty-hint">Henüz analiz edilmiş ders yok.</div>';
    return;
  }
  list.innerHTML = state.lectures
    .map((lec) => {
      const isActive = lec.id === state.activeId ? "active" : "";
      let statusCls = "status-processing";
      let statusText = `%${lec.progress_pct}`;
      if (lec.status === "completed") {
        statusCls = "status-completed";
        statusText = "Hazır";
      } else if (lec.status === "failed") {
        statusCls = "status-failed";
        statusText = "Hata";
      }
      const dur = lec.duration_sec ? formatTs(lec.duration_sec) : "--:--";
      return `
        <div class="lecture-item ${isActive}" data-id="${lec.id}">
          <div class="lecture-item-top">
            <div class="lecture-item-title">${escapeHtml(lec.title)}</div>
            <button class="delete-btn" data-del="${lec.id}" title="Sil">✕</button>
          </div>
          <div class="lecture-item-meta">
            <span>${escapeHtml(lec.platform || lec.source_type)} · ${dur}</span>
            <span class="status-pill ${statusCls}">${statusText}</span>
          </div>
        </div>
      `;
    })
    .join("");

  list.querySelectorAll(".lecture-item").forEach((node) => {
    node.addEventListener("click", (e) => {
      if (e.target.dataset.del) return;
      selectLecture(node.dataset.id);
    });
  });

  list.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.del;
      await fetch(`/api/lectures/${id}`, { method: "DELETE" });
      if (state.activeId === id) {
        state.activeId = null;
        el("workspace").classList.add("hidden");
        el("empty-state").classList.remove("hidden");
      }
      await loadLectures();
    });
  });
}

async function selectLecture(lectureId) {
  state.activeId = lectureId;
  state.forceAudioPlayer = false;
  renderLectureList();
  await refreshActiveLecture();
}

async function refreshActiveLecture() {
  if (!state.activeId) return;
  const res = await fetch(`/api/lectures/${state.activeId}`);
  if (!res.ok) return;
  const detail = await res.json();
  state.activeDetail = detail;
  renderWorkspace(detail);

  const status = detail.lecture.status;
  if (status !== "completed" && status !== "failed") {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(async () => {
      await loadLectures();
      await refreshActiveLecture();
    }, 1800);
  }
}

function renderWorkspace(detail) {
  const { lecture, chapters, segments, qa_history } = detail;
  el("empty-state").classList.add("hidden");
  el("workspace").classList.remove("hidden");

  el("lecture-title").textContent = lecture.title;
  el("lecture-meta").innerHTML = `
    <span class="meta-badge">Platform: ${escapeHtml(lecture.platform || lecture.source_type)}</span>
    <span class="meta-badge">Dil: ${escapeHtml((lecture.language || "-").toUpperCase())}</span>
    <span class="meta-badge">Süre: ${formatTs(lecture.duration_sec)}</span>
    <span class="meta-badge">Model: ${escapeHtml(lecture.whisper_model || "-")}</span>
  `;

  el("export-md").href = `/api/lectures/${lecture.id}/export?fmt=md`;
  el("export-txt").href = `/api/lectures/${lecture.id}/export?fmt=txt`;
  el("export-srt").href = `/api/lectures/${lecture.id}/export?fmt=srt`;

  if (lecture.status !== "completed") {
    el("progress-panel").classList.remove("hidden");
    el("studio-grid").classList.add("hidden");
    el("progress-label").textContent = lecture.status_message || "İşleniyor...";
    el("progress-pct").textContent = `${lecture.progress_pct}%`;
    el("progress-bar").style.width = `${lecture.progress_pct}%`;
    if (lecture.status === "failed") {
      el("error-box").classList.remove("hidden");
      el("error-box").textContent = lecture.error_message || "Bilinmeyen hata.";
    } else {
      el("error-box").classList.add("hidden");
    }
    return;
  }

  el("progress-panel").classList.add("hidden");
  el("studio-grid").classList.remove("hidden");

  setupPlayer(lecture);

  // Genel Özet
  const summary = lecture.summary || {};
  el("overview-content").innerHTML = formatClickableTimestamps(escapeHtml(summary.overview || "Özet çıkarılamadı."));

  // Konu Bölümleri
  el("chapters-list").innerHTML = chapters.length
    ? chapters
        .map(
          (ch) => `
        <div class="chapter-card">
          <div class="chapter-top">
            <span class="chapter-title">${escapeHtml(ch.title)}</span>
            <button class="ts-btn" data-seek="${ch.start_sec}">${formatTs(ch.start_sec)} – ${formatTs(ch.end_sec)}</button>
          </div>
          <div class="kw-row">
            ${(ch.keywords || []).map((k) => `<span class="kw-tag">${escapeHtml(k)}</span>`).join("")}
          </div>
          <div class="hint-text">${escapeHtml(ch.summary || "")}</div>
        </div>
      `
        )
        .join("")
    : '<div class="empty-hint">Konu bölümü bulunamadı.</div>';

  // Sınav & Ödev Vurguları
  const hl = summary.highlights || {};
  const renderHlGroup = (title, items) => {
    if (!items || !items.length) return "";
    return `
      <div class="highlight-group">
        <h4>${title}</h4>
        ${items
          .map(
            (it) => `
          <div class="citation-item">
            <button class="ts-btn" data-seek="${it.start_sec}">${escapeHtml(it.timestamp)}</button>
            ${escapeHtml(it.text)}
          </div>
        `
          )
          .join("")}
      </div>
    `;
  };
  const hlHtml =
    renderHlGroup("Sınav / Değerlendirme Vurguları", hl.exams) +
    renderHlGroup("Ödev / Proje / Teslimler", hl.assignments) +
    renderHlGroup("Kritik Kavram ve Özet Vurguları", hl.keypoints);
  el("highlights-content").innerHTML =
    hlHtml || '<div class="empty-hint">Bu kayıtta belirgin sınav/ödev veya anahtar uyarı ifadesi tespit edilmedi.</div>';

  // Transkript
  el("transcript-list").innerHTML = segments
    .map(
      (s) => `
      <div class="transcript-line" data-seek="${s.start_sec}">
        <span class="ts-btn">${formatTs(s.start_sec)}</span>
        <span>${escapeHtml(s.text)}</span>
      </div>
    `
    )
    .join("");

  // QA Geçmişi
  renderQaHistory(qa_history);
  bindTimestampClicks(document);
}

function setupPlayer(lecture) {
  const ytContainer = el("yt-container");
  const ytFrame = el("yt-frame");
  const audioContainer = el("audio-container");
  const audioPlayer = el("audio-player");
  const modeBar = el("player-mode-bar");
  const toggleBtn = el("toggle-audio-btn");

  const useYt = Boolean(lecture.youtube_id) && !state.forceAudioPlayer;
  if (useYt) {
    const targetSrc = `https://www.youtube.com/embed/${lecture.youtube_id}?enablejsapi=1`;
    if (ytFrame.src !== targetSrc) ytFrame.src = targetSrc;
    ytContainer.classList.remove("hidden");
    audioContainer.classList.add("hidden");
    modeBar.classList.remove("hidden");
    toggleBtn.classList.remove("hidden");
    toggleBtn.textContent = "Ses oynatıcıya geç";
  } else {
    ytContainer.classList.add("hidden");
    audioContainer.classList.remove("hidden");
    const audioUrl = `/api/lectures/${lecture.id}/audio`;
    if (!audioPlayer.src.endsWith(audioUrl)) audioPlayer.src = audioUrl;
    modeBar.classList.remove("hidden");
    if (lecture.youtube_id) {
      toggleBtn.classList.remove("hidden");
      toggleBtn.textContent = "YouTube oynatıcıya dön";
    } else {
      toggleBtn.classList.add("hidden");
    }
  }
}

function formatClickableTimestamps(htmlText) {
  return htmlText.replace(/\[(\d{2}:\d{2}(?::\d{2})?)\]/g, (match, ts) => {
    const parts = ts.split(":").map(Number);
    const secs = parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2] : parts[0] * 60 + parts[1];
    return `<button class="ts-btn" data-seek="${secs}">${ts}</button>`;
  });
}

function renderQaHistory(items) {
  const feed = el("qa-feed");
  if (!items || !items.length) {
    feed.innerHTML = '<div class="empty-hint">Yukarıdan ders içeriği hakkında zaman damgalı soru sorabilirsiniz.</div>';
    return;
  }
  feed.innerHTML = items
    .map((item) => {
      const ans = item.answer || {};
      const cites = (ans.citations || [])
        .map(
          (c) => `
          <div class="citation-item">
            <button class="ts-btn" data-seek="${c.start_sec}">${escapeHtml(c.timestamp)}</button>
            <strong>${escapeHtml(c.chapter_title)}</strong> — ${escapeHtml(c.text)}
          </div>
        `
        )
        .join("");
      return `
        <div class="qa-card">
          <div class="qa-question">Soru: ${escapeHtml(item.question)}</div>
          <div class="qa-answer">${formatClickableTimestamps(escapeHtml(ans.answer || ""))}</div>
          <div class="citations-row">${cites}</div>
        </div>
      `;
    })
    .join("");
}

function bindTimestampClicks(root) {
  root.querySelectorAll("[data-seek]").forEach((node) => {
    node.addEventListener("click", () => {
      const sec = Number(node.dataset.seek || 0);
      seekPlayer(sec);
    });
  });
}

// Event Listeners
document.querySelectorAll(".ingest-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".ingest-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const isUrl = tab.dataset.mode === "url";
    el("url-form").classList.toggle("hidden", !isUrl);
    el("upload-form").classList.toggle("hidden", isUrl);
  });
});

document.querySelectorAll(".study-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".study-tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    el(tab.dataset.tab).classList.add("active");
  });
});

el("url-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const res = await fetch("/api/lectures/url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: el("url-input").value.trim(),
      language: el("url-lang").value,
      whisper_model: el("url-model").value,
    }),
  });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || "Bağlantı başlatılamadı.");
    return;
  }
  const lec = await res.json();
  el("url-input").value = "";
  await loadLectures();
  await selectLecture(lec.id);
});

el("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = el("file-input").files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("language", el("file-lang").value);
  fd.append("whisper_model", el("file-model").value);

  const res = await fetch("/api/lectures/upload", { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.json();
    alert(err.detail || "Dosya yüklenemedi.");
    return;
  }
  const lec = await res.json();
  el("file-input").value = "";
  await loadLectures();
  await selectLecture(lec.id);
});

el("qa-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.activeId) return;
  const q = el("qa-input").value.trim();
  if (!q) return;
  el("qa-input").value = "";
  const res = await fetch(`/api/lectures/${state.activeId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question: q, top_k: 5 }),
  });
  if (res.ok) {
    await refreshActiveLecture();
  }
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    el("qa-input").value = chip.dataset.q;
    el("qa-form").requestSubmit();
  });
});

el("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.activeId) return;
  const q = el("search-input").value.trim();
  if (q.length < 2) return;
  const res = await fetch(`/api/lectures/${state.activeId}/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) return;
  const data = await res.json();
  const box = el("search-results");
  box.classList.remove("hidden");
  el("clear-search-btn").classList.remove("hidden");
  box.innerHTML = data.results.length
    ? data.results
        .map(
          (r) => `
        <div class="citation-item" style="margin-bottom:8px;">
          <button class="ts-btn" data-seek="${r.start_sec}">${escapeHtml(r.timestamp)}</button>
          <span class="meta-badge">Skor: ${r.score}</span>
          <div style="margin-top:4px;">${escapeHtml(r.text)}</div>
        </div>
      `
        )
        .join("")
    : '<div class="empty-hint">Eşleşen sonuç bulunamadı.</div>';
  bindTimestampClicks(box);
});

el("clear-search-btn").addEventListener("click", () => {
  el("search-input").value = "";
  el("search-results").classList.add("hidden");
  el("clear-search-btn").classList.add("hidden");
});

el("toggle-audio-btn").addEventListener("click", () => {
  state.forceAudioPlayer = !state.forceAudioPlayer;
  if (state.activeDetail) setupPlayer(state.activeDetail.lecture);
});

el("refresh-btn").addEventListener("click", loadLectures);

// Başlangıç
fetchHealth();
loadLectures();
