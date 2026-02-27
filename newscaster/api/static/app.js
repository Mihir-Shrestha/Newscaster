// ===========================================================================
// STATE
// ===========================================================================
let currentPlaylistId  = null;
let dragSrcItemId      = null;
let currentEpisodeId   = null;
let currentTranscript  = null;
let customPollInterval = null;
let activeView         = "home";
let openPickerBtn      = null;
let plDragSrcId        = null;
let currentGenreFilter = "custom"; // tracks filter in custom section

const audio = document.getElementById("global-audio");

// ===========================================================================
// INIT
// ===========================================================================
// Call once on DOMContentLoaded
function initTooltips() {
  document.querySelectorAll(".rs-info-wrap").forEach(wrap => {
    const btn     = wrap.querySelector(".rs-info-btn");
    const tooltip = wrap.querySelector(".rs-tooltip");
    if (!btn || !tooltip) return;

    btn.addEventListener("mouseenter", () => {
      const rect = btn.getBoundingClientRect();

      // Position tooltip to the left of the icon, vertically centered
      const tooltipWidth  = 230;
      const left = rect.left - tooltipWidth - 10;   // 10px gap to the left
      const top  = rect.top + (rect.height / 2);    // vertically centered on icon

      tooltip.style.left = `${Math.max(8, left)}px`; // never go off left edge
      tooltip.style.top  = `${top}px`;
      tooltip.style.transform = "translateY(-50%)";
      tooltip.style.display   = "block";
    });

    btn.addEventListener("mouseleave", () => {
      tooltip.style.display = "none";
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  if (!document.getElementById("home-view")) return;

  loadDailyEpisodes();
  loadCustomEpisodes("custom");
  loadPlaylists();
  loadDailyLimit();
  setupAudioListeners();

  document.addEventListener("click", e => {
    const profileWrap = document.getElementById("profile-menu-wrap");
    if (profileWrap && !profileWrap.contains(e.target))
      document.getElementById("profile-dropdown").classList.remove("open");

    const dateWrap = document.getElementById("date-filter-wrap");
    if (dateWrap && !dateWrap.contains(e.target)) {
      document.getElementById("date-filter-dropdown").classList.remove("open");
      document.getElementById("date-filter-btn").classList.remove("active");
    }

    if (openPickerBtn && !e.target.closest(".playlist-picker-popup") &&
        !e.target.closest(".ep-card-btn"))
      closeAllPickers();
    initTooltips();
  });
});

// ===========================================================================
// VIEW MANAGEMENT
// ===========================================================================
function showHome() {
  hideAllViews();
  document.getElementById("home-view").style.display = "block";
  activeView = "home";
  if (customPollInterval) { clearInterval(customPollInterval); customPollInterval = null; }
}

function hideAllViews() {
  ["home-view","search-results-view","show-all-view","transcript-view","playlist-view"]
    .forEach(id => { const el = document.getElementById(id); if (el) el.style.display = "none"; });
}

function showAllEpisodes(type) {
  hideAllViews();
  const view  = document.getElementById("show-all-view");
  const title = document.getElementById("show-all-title");
  const list  = document.getElementById("show-all-list");
  view.style.display = "block";
  activeView = "show-all";

  if (type === "daily") {
    title.textContent = "All Daily Episodes";
    fetchAndRender("/episodes/daily?limit=100", list, false, false);
  } else {
    title.textContent = `All ${currentGenreFilter === "custom" ? "Custom" : currentGenreFilter.charAt(0).toUpperCase() + currentGenreFilter.slice(1)} Episodes`;

    // Fetch all and filter client-side, same logic as loadCustomEpisodes
    list.innerHTML = '<p class="loading-text">Loading...</p>';
    fetch("/episodes/custom?limit=100", { credentials: "include" })
      .then(r => r.json())
      .then(data => {
        let episodes = Array.isArray(data) ? data : data.episodes || data.results || data.items || [];

        if (currentGenreFilter === "custom") {
          episodes = episodes.filter(ep => {
            const cp = ep.custom_params || {};
            return cp.keywords && cp.keywords.trim() !== "";
          });
        } else {
          episodes = episodes.filter(ep => {
            const cp = ep.custom_params || {};
            return (cp.genre || "").toLowerCase() === currentGenreFilter.toLowerCase()
                && (!cp.keywords || cp.keywords.trim() === "");
          });
        }

        renderEpisodeCards(episodes, list, false, true);
      })
      .catch(() => { list.innerHTML = '<p class="empty-text">Failed to load.</p>'; });
  }
}

// ===========================================================================
// PROFILE DROPDOWN
// ===========================================================================
function toggleProfileMenu() {
  document.getElementById("profile-dropdown").classList.toggle("open");
}

// ===========================================================================
// DATE FILTER
// ===========================================================================
function toggleDateFilter() {
  const dd  = document.getElementById("date-filter-dropdown");
  const btn = document.getElementById("date-filter-btn");
  const isOpen = dd.classList.contains("open");
  dd.classList.toggle("open");
  btn.classList.toggle("active", !isOpen);
}

function updateDateFilterLabel() {
  const from = document.getElementById("from-date").value;
  const to   = document.getElementById("to-date").value;
  const lbl  = document.getElementById("date-filter-label");
  if (from && to)    lbl.textContent = `${from} → ${to}`;
  else if (from)     lbl.textContent = `From ${from}`;
  else if (to)       lbl.textContent = `To ${to}`;
  else               lbl.textContent = "Date";
}

function applyDateFilter() {
  document.getElementById("date-filter-dropdown").classList.remove("open");
  document.getElementById("date-filter-btn").classList.remove("active");
  searchEpisodes();
}

function clearDateFilter() {
  document.getElementById("from-date").value = "";
  document.getElementById("to-date").value   = "";
  document.getElementById("date-filter-label").textContent = "Date";
  document.getElementById("date-filter-dropdown").classList.remove("open");
  document.getElementById("date-filter-btn").classList.remove("active");
}

// ===========================================================================
// SEARCH BAR CLEAR
// ===========================================================================
function toggleSearchClear() {
  const val = document.getElementById("search-query").value;
  document.getElementById("search-clear-btn").style.display = val ? "flex" : "none";
}

function clearSearchInput() {
  document.getElementById("search-query").value = "";
  document.getElementById("search-clear-btn").style.display = "none";
  document.getElementById("search-query").focus();
}

// ===========================================================================
// EPISODES — LOAD
// ===========================================================================
async function loadDailyEpisodes() {
  await fetchAndRender("/episodes/daily?limit=8",
    document.getElementById("daily-episodes-list"), false, false);
}

async function loadCustomEpisodes(genre = "custom") {
  currentGenreFilter = genre;
  const container = document.getElementById("custom-episodes-list");
  if (!container) return;

  container.innerHTML = '<p class="loading-text">Loading...</p>';

  try {
    // Always fetch all custom episodes — filter client-side because
    // the backend stores genre in custom_params.genre, not the top-level
    // genre column (which is always "general")
    const res  = await fetch("/episodes/custom?limit=100", { credentials: "include" });
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    let episodes = Array.isArray(data) ? data : data.episodes || data.results || data.items || [];

    if (genre === "custom") {
      // "Custom" tab — show only keyword-based episodes (keywords not empty)
      episodes = episodes.filter(ep => {
        const cp = ep.custom_params || {};
        return cp.keywords && cp.keywords.trim() !== "";
      });
    } else {
      // Genre tab (technology, entertainment, etc.) — match custom_params.genre
      episodes = episodes.filter(ep => {
        const cp = ep.custom_params || {};
        return (cp.genre || "").toLowerCase() === genre.toLowerCase()
            && (!cp.keywords || cp.keywords.trim() === "");
      });
    }

    // Only show 8 most recent after filtering
    episodes = episodes.slice(0, 8);

    renderEpisodeCards(episodes, container, false, true);
  } catch {
    container.innerHTML = '<p class="empty-text">Failed to load.</p>';
  }
}

function switchCustomFilter(genre, btn) {
  // Update active tab styling
  document.querySelectorAll(".custom-genre-tab").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");

  // Load filtered episodes
  loadCustomEpisodes(genre);
}

// ===========================================================================
// FETCH + RENDER
// ===========================================================================
async function fetchAndRender(url, container, inPlaylist, isCustom = false) {
  container.innerHTML = '<p class="loading-text">Loading...</p>';
  try {
    const res  = await fetch(url, { credentials: "include" });
    if (res.status === 401) { window.location.href = "/login"; return; }
    const data = await res.json();
    const episodes = Array.isArray(data) ? data
      : data.episodes || data.results || data.items || [];
    renderEpisodeCards(episodes, container, inPlaylist, isCustom);
  } catch {
    container.innerHTML = '<p class="empty-text">Failed to load.</p>';
  }
}

// ===========================================================================
// RENDER EPISODE CARDS
// ===========================================================================
function renderEpisodeCards(episodes, container, inPlaylist = false, isCustom = false) {
  if (!episodes || episodes.length === 0) {
    container.innerHTML = inPlaylist
      ? '<p class="empty-text">No episodes in this playlist.</p>'
      : isCustom
        ? '<p class="empty-text">No custom episodes yet. Generate one →</p>'
        : '<p class="empty-text">No episodes yet.</p>';
    return;
  }

  container.innerHTML = episodes.map(ep => {
    const d       = ep.published_at ? new Date(ep.published_at) : new Date();
    const month   = d.toLocaleString("en-US", { month: "short" }).toUpperCase();
    const day     = d.getDate();
    const year    = d.getFullYear();
    const dayName = d.toLocaleString("en-US", { weekday: "long" });
    const dateStr = d.toLocaleDateString("en-US", { month:"short", day:"numeric", year:"numeric" });

    // ── Card title / subtitle ──────────────────────────────────────
    let cardTitle, cardSubtitle;
    if (isCustom) {
      const cp = ep.custom_params || {};
      const hasKeywords = cp.keywords && cp.keywords.trim() !== "";

      if (hasKeywords) {
        // True custom search — show keywords as title
        const parts = [];
        if (cp.keywords)  parts.push(cp.keywords);
        if (cp.from_date) parts.push(cp.from_date);
        if (cp.to_date)   parts.push(cp.to_date);
        if (cp.domains)   parts.push(cp.domains);
        cardTitle    = parts.join(" – ");
        cardSubtitle = "custom";
      } else {
        // Genre-based — cp.genre is the truth, ep.genre is always "general" (backend bug)
        const g = cp.genre || "general";
        cardTitle    = ep.title || (g.charAt(0).toUpperCase() + g.slice(1));
        cardSubtitle = g.toLowerCase();
      }
    } else {
      // Daily
      cardTitle    = dayName;
      cardSubtitle = "daily";
    }

    // Truncate long titles for display
    const displayTitle = cardTitle.length > 32
      ? cardTitle.slice(0, 30) + "…"
      : cardTitle;

    const thumbClass = isCustom ? "ep-card-thumb custom-ep" : "ep-card-thumb";
    const dragAttrs  = inPlaylist
      ? `draggable="true" data-item-id="${ep.item_id || ep.id}"`
      : "";

    // ── Action buttons ─────────────────────────────────────────────
    // Transcript button only in bottom navbar — never on custom cards
    // In playlist view keep Remove; elsewhere keep + Playlist only
    let actionBtns;
    if (inPlaylist) {
      actionBtns = `<button class="ep-card-btn" onclick="removeFromPlaylist('${ep.item_id || ep.id}',event)">Remove</button>`;
    } else {
      actionBtns = `<button class="ep-card-btn" id="pl-btn-${ep.id}" onclick="showAddToPlaylist('${ep.id}',event)">+ Playlist</button>`;
    }

    // Player title: "Thursday (Feb 26, 2026)" style
    const playerTitle = isCustom
      ? `${cardTitle} (${dateStr})`
      : `${dayName} (${dateStr})`;

    return `
    <div class="ep-card ${inPlaylist ? 'draggable' : ''}"
         ${dragAttrs}
         data-episode-id="${ep.id}"
         onclick="playEpisode('${ep.id}','${escHtml(playerTitle)}','${escHtml(cardSubtitle)}',event)">
      <div class="${thumbClass}">
        <span class="ep-card-month">${month}</span>
        <span class="ep-card-day">${day}</span>
        <span class="ep-card-year">${year}</span>
        <div class="ep-card-play-overlay">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5v14l11-7z"/>
          </svg>
        </div>
      </div>
      <div class="ep-card-info">
        <div class="ep-card-title" title="${escHtml(cardTitle)}">${escHtml(displayTitle)}</div>
        <div class="ep-card-meta">${escHtml(cardSubtitle)}</div>
        <div class="ep-card-actions" onclick="event.stopPropagation()">
          ${actionBtns}
        </div>
      </div>
    </div>`;
  }).join("");

  if (inPlaylist) setupDragAndDrop();
}

// ===========================================================================
// PLAYLIST PICKER POPUP — fixed, right of button, sorted alpha
// ===========================================================================
let pickerPopup = null;

function closeAllPickers() {
  if (pickerPopup) { pickerPopup.remove(); pickerPopup = null; }
  openPickerBtn = null;
}

async function showAddToPlaylist(episodeId, event) {
  event.stopPropagation();
  const btn = document.getElementById(`pl-btn-${episodeId}`);
  if (openPickerBtn === btn) { closeAllPickers(); return; }
  closeAllPickers();
  openPickerBtn = btn;

  const popup = document.createElement("div");
  popup.className = "playlist-picker-popup";
  popup.innerHTML = '<p class="picker-empty">Loading...</p>';
  document.body.appendChild(popup);
  pickerPopup = popup;

  // Position to the right of the button
  const rect = btn.getBoundingClientRect();
  popup.style.position = "fixed";
  popup.style.top      = `${rect.top}px`;
  popup.style.left     = `${rect.right + 8}px`;

  // After render — clamp to viewport
  requestAnimationFrame(() => {
    const popW = popup.offsetWidth;
    const popH = popup.offsetHeight;
    const winW = window.innerWidth;
    const winH = window.innerHeight;

    // If popup goes off right edge → flip to left
    if (rect.right + 8 + popW > winW - 8) {
      popup.style.left = `${Math.max(8, rect.left - popW - 8)}px`;
    }
    // Clamp bottom
    if (rect.top + popH > winH - 8) {
      popup.style.top = `${Math.max(8, winH - popH - 8)}px`;
    }
  });

  try {
    const res  = await fetch("/playlists", { credentials: "include" });
    const data = await res.json();
    // Sort alphabetically
    const sorted = (data.playlists || []).slice().sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    );
    popup.innerHTML = sorted.length === 0
      ? '<p class="picker-empty">No playlists. Create one first.</p>'
      : sorted.map(p => `
          <div class="picker-item"
               onclick="addToPlaylist('${p.id}','${episodeId}','${escHtml(p.name)}',event)">
            🎵 ${escHtml(p.name)}
          </div>`).join("");
  } catch {
    popup.innerHTML = '<p class="picker-empty">Failed to load.</p>';
  }
}

async function addToPlaylist(playlistId, episodeId, playlistName, event) {
  event?.stopPropagation();
  closeAllPickers();
  try {
    const res = await fetch(`/playlists/${playlistId}/items`, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ episode_id: episodeId })
    });
    if (res.status === 409) { alert("Already in playlist."); return; }
    if (!res.ok)            { alert("Failed to add."); return; }
    alert(`✅ Added to "${playlistName}"`);
  } catch { alert("Failed to add episode."); }
}

// ===========================================================================
// AUDIO PLAYER
// ===========================================================================
function setupAudioListeners() {
  if (!audio) return;
  audio.addEventListener("timeupdate", () => {
    const prog = document.getElementById("player-progress");
    const cur  = document.getElementById("player-current");
    if (!prog || !audio.duration) return;
    prog.max   = audio.duration;
    prog.value = audio.currentTime;
    cur.textContent = fmtTime(audio.currentTime);
  });
  audio.addEventListener("loadedmetadata", () => {
    document.getElementById("player-duration").textContent = fmtTime(audio.duration);
    document.getElementById("player-progress").max = audio.duration;
  });
  audio.addEventListener("play",  () => setPlayIcon(true));
  audio.addEventListener("pause", () => setPlayIcon(false));
  audio.addEventListener("ended", () => setPlayIcon(false));
}

async function playEpisode(id, title, subtitle, event) {
  if (event && event.target.closest("button")) return;
  currentEpisodeId = id;
  document.getElementById("player-title").textContent    = title;
  document.getElementById("player-subtitle").textContent = subtitle;  // daily / custom / genre
  audio.src = `/episodes/${id}/audio`;
  audio.load();
  audio.play().catch(console.error);

  document.getElementById("transcript-btn").style.display = "none";
  currentTranscript = null;
  try {
    const res = await fetch(`/episodes/${id}/transcript`, { credentials: "include" });
    if (res.ok) {
      const data = await res.json();
      if (data.transcript) {
        currentTranscript = data.transcript;
        document.getElementById("transcript-btn").style.display = "flex";
      }
    }
  } catch (_) {}
}

function togglePlay() {
  if (!audio.src) return;
  audio.paused ? audio.play() : audio.pause();
}

function seekRelative(secs) {
  if (!audio.src) return;
  audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + secs));
}

function seekTo(val)    { if (audio.src) audio.currentTime = val; }
function setVolume(val) {
  audio.volume = val;
  if (audio.muted && val > 0) {
    audio.muted = false;
    document.getElementById("vol-icon").style.display  = "block";
    document.getElementById("mute-icon").style.display = "none";
  }
}

function toggleMute() {
  audio.muted = !audio.muted;
  document.getElementById("vol-icon").style.display  = audio.muted ? "none"  : "block";
  document.getElementById("mute-icon").style.display = audio.muted ? "block" : "none";
}

function setPlayIcon(playing) {
  document.getElementById("play-icon").style.display  = playing ? "none"  : "block";
  document.getElementById("pause-icon").style.display = playing ? "block" : "none";
}

function fmtTime(secs) {
  if (!secs || isNaN(secs)) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

// ===========================================================================
// TRANSCRIPT — toggle on/off
// ===========================================================================
function toggleTranscript() {
  activeView === "transcript" ? closeTranscript() : showTranscript();
}

function showTranscript() {
  if (!currentTranscript) return;
  hideAllViews();
  document.getElementById("transcript-view").style.display = "block";
  document.getElementById("transcript-content").textContent = currentTranscript;
  activeView = "transcript";
}

function showTranscriptFor(id, transcript, event) {
  if (event) event.stopPropagation();
  currentTranscript = transcript;
  hideAllViews();
  document.getElementById("transcript-view").style.display = "block";
  document.getElementById("transcript-content").textContent = transcript || "No transcript available.";
  activeView = "transcript";
}

function closeTranscript() { showHome(); }

// ===========================================================================
// SEARCH
// ===========================================================================
async function searchEpisodes() {
  const q        = document.getElementById("search-query").value.trim();
  const fromDate = document.getElementById("from-date").value;
  const toDate   = document.getElementById("to-date").value;

  if (!q && !fromDate && !toDate) { showHome(); return; }

  hideAllViews();
  const view      = document.getElementById("search-results-view");
  const titleEl   = document.getElementById("search-results-title");
  const container = document.getElementById("search-results-list");
  view.style.display = "block";
  activeView = "search";
  titleEl.textContent = q ? `Results for "${q}"` : "Search Results";
  container.innerHTML = '<p class="loading-text">Searching...</p>';

  const params = new URLSearchParams();
  if (q)        params.append("q", q);
  if (fromDate) params.append("from_date", fromDate);
  if (toDate)   params.append("to_date", toDate);

  try {
    const res  = await fetch(`/episodes/search?${params}`, { credentials: "include" });
    const data = await res.json();
    renderEpisodeCards(data.results || [], container, false);
  } catch {
    container.innerHTML = '<p class="empty-text">Search failed.</p>';
  }
}

// ===========================================================================
// PLAYLISTS — SIDEBAR
// ===========================================================================
async function loadPlaylists() {
  const container = document.getElementById("playlist-list");
  try {
    const res  = await fetch("/playlists", { credentials: "include" });
    if (!res.ok) return;
    const data = await res.json();
    if (!data.playlists || !data.playlists.length) {
      container.innerHTML = '<p class="sidebar-empty">No playlists yet.</p>';
      return;
    }
    container.innerHTML = data.playlists.map(p => `
      <div class="playlist-item ${currentPlaylistId === p.id ? 'active' : ''}"
           id="pl-${p.id}"
           draggable="true"
           data-pl-id="${p.id}"
           data-pl-name="${escHtml(p.name)}"
           onclick="openPlaylist('${p.id}','${escHtml(p.name)}')">
        <span class="pl-drag-handle" title="Drag to reorder" onmousedown="event.stopPropagation()">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <path d="M11 18c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2 2 .9 2 2zm-2-8c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0-6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm6 4c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
          </svg>
        </span>
        <span class="pl-name">${escHtml(p.name)}</span>
      </div>
    `).join("");
    setupSidebarDrag();
  } catch (err) { console.error("loadPlaylists", err); }
}

function setupSidebarDrag() {
  const items = document.querySelectorAll(".playlist-item[draggable]");
  items.forEach(item => {
    item.addEventListener("dragstart", e => {
      plDragSrcId = item.dataset.plId;
      item.classList.add("dragging-pl");
      e.dataTransfer.effectAllowed = "move";
    });
    item.addEventListener("dragend", () => {
      item.classList.remove("dragging-pl");
      document.querySelectorAll(".playlist-item").forEach(i => i.classList.remove("drag-over-pl"));
    });
    item.addEventListener("dragover", e => {
      e.preventDefault();
      document.querySelectorAll(".playlist-item").forEach(i => i.classList.remove("drag-over-pl"));
      item.classList.add("drag-over-pl");
    });
    item.addEventListener("dragleave", () => item.classList.remove("drag-over-pl"));
    item.addEventListener("drop", e => {
      e.preventDefault();
      item.classList.remove("drag-over-pl");
      if (plDragSrcId === item.dataset.plId) return;
      const container = document.getElementById("playlist-list");
      const srcEl     = container.querySelector(`[data-pl-id="${plDragSrcId}"]`);
      const allItems  = [...container.querySelectorAll(".playlist-item")];
      const srcIdx    = allItems.indexOf(srcEl);
      const destIdx   = allItems.indexOf(item);
      srcIdx < destIdx ? item.after(srcEl) : item.before(srcEl);
    });
  });
}

function showCreatePlaylist() {
  document.getElementById("create-playlist-form").style.display = "block";
  document.getElementById("new-playlist-name").focus();
}

function hideCreatePlaylist() {
  document.getElementById("create-playlist-form").style.display = "none";
  document.getElementById("new-playlist-name").value = "";
}

async function createPlaylist() {
  const name = document.getElementById("new-playlist-name").value.trim();
  if (!name) return;
  try {
    const res = await fetch("/playlists", {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    if (!res.ok) { alert("Failed to create playlist."); return; }
    hideCreatePlaylist();
    loadPlaylists();
  } catch { alert("Failed to create playlist."); }
}

async function openPlaylist(pid, name) {
  currentPlaylistId = pid;
  document.querySelectorAll(".playlist-item").forEach(el => el.classList.remove("active"));
  document.getElementById(`pl-${pid}`)?.classList.add("active");

  hideAllViews();
  document.getElementById("playlist-view").style.display = "block";
  activeView = "playlist";
  document.getElementById("playlist-view-title").textContent = name;
  document.getElementById("share-box").style.display = "none";

  const container = document.getElementById("playlist-episodes-list");
  container.innerHTML = '<p class="loading-text">Loading...</p>';

  try {
    const res  = await fetch(`/playlists/${pid}/items`, { credentials: "include" });
    if (!res.ok) { container.innerHTML = "<p>Failed to load.</p>"; return; }
    const data = await res.json();
    renderEpisodeCards(data.items, container, true);
  } catch { container.innerHTML = '<p class="empty-text">Failed to load.</p>'; }
}

async function renamePlaylistPrompt() {
  if (!currentPlaylistId) return;
  const newName = prompt("New playlist name:");
  if (!newName?.trim()) return;
  try {
    const res = await fetch(`/playlists/${currentPlaylistId}`, {
      method: "PATCH", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() })
    });
    if (!res.ok) { alert("Failed to rename."); return; }
    document.getElementById("playlist-view-title").textContent = newName.trim();
    loadPlaylists();
  } catch { alert("Failed to rename."); }
}

async function deletePlaylist() {
  if (!currentPlaylistId || !confirm("Delete this playlist?")) return;
  try {
    await fetch(`/playlists/${currentPlaylistId}`, { method: "DELETE", credentials: "include" });
    currentPlaylistId = null;
    loadPlaylists();
    showHome();
  } catch { alert("Failed to delete."); }
}

async function removeFromPlaylist(itemId, event) {
  event?.stopPropagation();
  if (!currentPlaylistId || !confirm("Remove from playlist?")) return;
  try {
    await fetch(`/playlists/${currentPlaylistId}/items/${itemId}`, {
      method: "DELETE", credentials: "include"
    });
    openPlaylist(currentPlaylistId,
      document.getElementById("playlist-view-title").textContent);
  } catch { alert("Failed to remove."); }
}

// ===========================================================================
// SHARE
// ===========================================================================
async function sharePlaylist() {
  if (!currentPlaylistId) return;
  const shareBox = document.getElementById("share-box");
  if (shareBox.style.display === "flex") { shareBox.style.display = "none"; return; }
  try {
    const res  = await fetch(`/playlists/${currentPlaylistId}/share`, { method: "POST", credentials: "include" });
    const data = await res.json();
    const url  = `${window.location.origin}${data.share_url}`;
    document.getElementById("share-url").textContent = url;
    shareBox.dataset.url = url;
    shareBox.style.display = "flex";
  } catch { alert("Failed to generate share link."); }
}

function copyShareLink() {
  navigator.clipboard.writeText(document.getElementById("share-box").dataset.url)
    .then(() => alert("Link copied!"));
}

async function revokeShare() {
  if (!currentPlaylistId || !confirm("Revoke share link?")) return;
  try {
    await fetch(`/playlists/${currentPlaylistId}/share`, { method: "DELETE", credentials: "include" });
    document.getElementById("share-box").style.display = "none";
  } catch { alert("Failed to revoke."); }
}

// ===========================================================================
// DRAG AND DROP — playlist item reorder
// ===========================================================================
function setupDragAndDrop() {
  const cards = document.querySelectorAll(".ep-card.draggable");
  cards.forEach(card => {
    card.addEventListener("dragstart", e => {
      dragSrcItemId = card.dataset.itemId;
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragend", () => {
      card.classList.remove("dragging");
      document.querySelectorAll(".ep-card").forEach(c => c.classList.remove("drag-over"));
    });
    card.addEventListener("dragover", e => { e.preventDefault(); card.classList.add("drag-over"); });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", async e => {
      e.preventDefault();
      card.classList.remove("drag-over");
      if (dragSrcItemId === card.dataset.itemId) return;
      const container = document.getElementById("playlist-episodes-list");
      const srcCard   = container.querySelector(`[data-item-id="${dragSrcItemId}"]`);
      const allCards  = [...container.querySelectorAll(".ep-card.draggable")];
      const srcIdx    = allCards.indexOf(srcCard);
      const destIdx   = allCards.indexOf(card);
      srcIdx < destIdx ? card.after(srcCard) : card.before(srcCard);
      const newOrder = [...container.querySelectorAll(".ep-card.draggable")].map(c => c.dataset.itemId);
      try {
        await fetch(`/playlists/${currentPlaylistId}/items/reorder`, {
          method: "PUT", credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: newOrder })
        });
      } catch (err) { console.error("Reorder failed", err); }
    });
  });
}

// ===========================================================================
// GENERATE CUSTOM EPISODE — right sidebar
// ===========================================================================
async function loadDailyLimit() {
  try {
    const res  = await fetch("/generate/limit", { credentials: "include" });
    const data = await res.json();
    updateLimitUI(data.used, data.limit);
  } catch { /* silent */ }
}

function updateLimitUI(used, limit) {
  const remaining = limit - used;
  const pct       = (used / limit) * 100;
  const textEl    = document.getElementById("rs-limit-text");
  const fillEl    = document.getElementById("rs-limit-fill");
  const btn       = document.getElementById("rs-generate-btn");
  if (textEl) textEl.textContent = `${remaining} / ${limit} left today`;
  if (fillEl) { fillEl.style.width = `${pct}%`; fillEl.style.background = remaining <= 1 ? "#e74c3c" : "#6c63ff"; }
  if (btn)    btn.disabled = remaining <= 0;
}

// Toggle between "custom params" mode and "genre" mode in right sidebar
function switchGenerateMode(mode) {
  const customFields = document.getElementById("rs-custom-fields");
  const genreFields  = document.getElementById("rs-genre-fields");
  document.querySelectorAll(".rs-mode-tab").forEach(b => b.classList.remove("active"));
  document.querySelector(`.rs-mode-tab[data-mode="${mode}"]`).classList.add("active");
  if (mode === "custom") {
    customFields.style.display = "flex";
    genreFields.style.display  = "none";
  } else {
    customFields.style.display = "none";
    genreFields.style.display  = "flex";
  }
}

async function generateCustomEpisode() {
  const btn      = document.getElementById("rs-generate-btn");
  const statusEl = document.getElementById("rs-status");

  const activeTab = document.querySelector(".rs-mode-tab.active");
  const mode = activeTab ? activeTab.dataset.mode : "custom";

  let body;
  if (mode === "custom") {
    const keywords = document.getElementById("rs-keywords").value.trim();
    if (!keywords) {
      document.getElementById("rs-keywords").classList.add("rs-input-error");
      showRsStatus("Keywords / Phrases is required.", "error", statusEl);
      document.getElementById("rs-keywords").focus();
      return;
    }
    document.getElementById("rs-keywords").classList.remove("rs-input-error");
    body = {
      keywords,
      from_date:       document.getElementById("rs-from-date").value,
      to_date:         document.getElementById("rs-to-date").value,
      domains:         document.getElementById("rs-domains").value.trim(),
      exclude_domains: document.getElementById("rs-exclude-domains").value.trim(),
      genre:           "custom",
    };
  } else {
    body = {
      keywords:        "",
      from_date:       "",
      to_date:         "",
      domains:         "",
      exclude_domains: "",
      genre:           document.getElementById("rs-genre-select").value,
    };
  }

  btn.disabled    = true;
  btn.textContent = "Generating…";
  showRsStatus("This will take ~60 seconds…", "info", statusEl);

  try {
    const res  = await fetch("/generate/custom", {
      method:      "POST",
      credentials: "include",
      headers:     { "Content-Type": "application/json" },
      body:        JSON.stringify(body),
    });
    const data = await res.json();

    if (res.status === 429) {
      showRsStatus("Daily limit reached. Try again tomorrow.", "error", statusEl);
      btn.disabled    = false;
      btn.textContent = "Generate";
      return;
    }
    if (!res.ok) {
      showRsStatus(`Error: ${data.error || "Generation failed."}`, "error", statusEl);
      btn.disabled    = false;
      btn.textContent = "Generate";
      return;
    }

    // Reload limit bar immediately after queuing
    await loadDailyLimit();

    // ── Poll until the new episode appears, then stop ──────────────
    // Snapshot how many custom episodes exist right now
    const beforeRes  = await fetch("/episodes/custom?limit=100", { credentials: "include" });
    const beforeData = await beforeRes.json();
    const beforeIds  = new Set((beforeData.episodes || beforeData || []).map(e => e.id));

    let attempts = 0;
    const maxAttempts = 2;

    const poll = setInterval(async () => {
      attempts++;

      const afterRes  = await fetch("/episodes/custom?limit=100", { credentials: "include" });
      const afterData = await afterRes.json();
      const afterEps  = afterData.episodes || afterData || [];

      // Check if a new episode appeared that wasn't there before
      const newEp = afterEps.find(e => !beforeIds.has(e.id));

      if (newEp) {
        // New episode found — refresh the visible section once and stop
        clearInterval(poll);
        await loadCustomEpisodes(currentGenreFilter);

        // Show "ready" message then fade it out after 3s
        showRsStatus("Your podcast is ready!", "success", statusEl);
        setTimeout(() => fadeOutStatus(statusEl), 3000);

        btn.disabled    = false;
        btn.textContent = "Generate";
        return;
      }

      if (attempts >= maxAttempts) {
        // Timed out — do one final refresh and show a neutral message
        clearInterval(poll);
        await loadCustomEpisodes(currentGenreFilter);
        showRsStatus("Generation may still be processing. Check back soon.", "info", statusEl);
        setTimeout(() => fadeOutStatus(statusEl), 5000);
        btn.disabled    = false;
        btn.textContent = "Generate";
      }
    }, 60000); // poll every 60s

  } catch (err) {
    console.error("[generate]", err);
    showRsStatus("Network error. Please try again.", "error", statusEl);
    btn.disabled    = false;
    btn.textContent = "Generate";
  }
}

// Fade out and hide the status message
function fadeOutStatus(el) {
  if (!el) return;
  el.style.transition = "opacity 1s ease";
  el.style.opacity    = "0";
  setTimeout(() => {
    el.style.display  = "none";
    el.style.opacity  = "1";
    el.style.transition = "";
  }, 1000);
}

function showRsStatus(msg, type, el) {
  if (!el) return;
  el.textContent     = msg;
  el.className       = `rs-status ${type}`;
  el.style.display   = "block";
  el.style.opacity   = "1";
  el.style.transition = "";
}

// ===========================================================================
// UTILS
// ===========================================================================
function escHtml(str) {
  if (!str) return "";
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
            .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
}