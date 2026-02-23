// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentPlaylistId = null;
let dragSrcItemId     = null;

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("episodes-list")) {
        loadEpisodes();
        loadPlaylists();
    }
});

// ===========================================================================
// EPISODES
// ===========================================================================
async function loadEpisodes() {
    currentPlaylistId = null;
    document.getElementById("content-title").textContent = "All Episodes";
    document.getElementById("playlist-actions").style.display = "none";
    document.getElementById("share-box").style.display = "none";

    const container = document.getElementById("episodes-list");
    container.innerHTML = "<p>Loading episodes...</p>";
    try {
        const res = await fetch("/episodes", { credentials: "include" });
        if (res.status === 401) {
            container.innerHTML = '<p><a href="/login">Login to view episodes</a></p>';
            return;
        }
        const data = await res.json();
        renderEpisodes(data.episodes, container, false);
    } catch (err) {
        container.innerHTML = `<p class="error-box">Failed to load episodes.</p>`;
    }
}

async function searchEpisodes() {
    const q         = document.getElementById("search-query").value.trim();
    const fromDate  = document.getElementById("from-date").value;
    const toDate    = document.getElementById("to-date").value;
    const container = document.getElementById("episodes-list");
    const searchBtn = document.getElementById("search-btn");

    if (!q && !fromDate && !toDate) { loadEpisodes(); return; }

    searchBtn.textContent = "⏳ Searching...";
    searchBtn.disabled    = true;
    container.innerHTML   = "<p>Searching...</p>";

    const params = new URLSearchParams();
    if (q)        params.append("q", q);
    if (fromDate) params.append("from_date", fromDate);
    if (toDate)   params.append("to_date", toDate);

    try {
        const res = await fetch(`/episodes/search?${params.toString()}`, {
            credentials: "include"
        });
        if (res.status === 401) {
            container.innerHTML = '<p><a href="/login">Login to search</a></p>';
            return;
        }
        const data = await res.json();
        if (data.results.length === 0) {
            container.innerHTML = "<p>No episodes found.</p>";
            return;
        }
        renderEpisodes(data.results, container, false);
    } catch (err) {
        container.innerHTML = `<p class="error-box">Search failed.</p>`;
    } finally {
        searchBtn.textContent = "🔍 Search";
        searchBtn.disabled    = false;
    }
}

function clearSearch() {
    document.getElementById("search-query").value = "";
    document.getElementById("from-date").value    = "";
    document.getElementById("to-date").value      = "";
    loadEpisodes();
}

// ---------------------------------------------------------------------------
// Render episodes — inPlaylist=true enables drag-to-reorder + remove button
// ---------------------------------------------------------------------------
function renderEpisodes(episodes, container, inPlaylist) {
    if (!episodes || episodes.length === 0) {
        container.innerHTML = inPlaylist
            ? "<p>No episodes in this playlist yet.</p>"
            : "<p>No episodes yet. Generate your first one!</p>";
        return;
    }

    container.innerHTML = episodes.map(ep => {
        const date = ep.published_at
            ? new Date(ep.published_at).toLocaleDateString("en-US", {
                year: "numeric", month: "long", day: "numeric"
              })
            : "Unknown date";

        const headlines = Array.isArray(ep.headlines)
            ? ep.headlines.map(h => `<li>${h}</li>`).join("")
            : "";

        const dragAttrs = inPlaylist
            ? `draggable="true" data-item-id="${ep.item_id}"`
            : "";

        const actionBtn = inPlaylist
            ? `<button class="btn-small btn-danger"
                onclick="removeFromPlaylist('${ep.item_id}')">
                Remove
               </button>`
            : `<button class="btn-small btn-add-playlist"
                onclick="showAddToPlaylist('${ep.id}', this)">
                ＋ Add to Playlist
               </button>`;

        return `
        <div class="episode-card ${inPlaylist ? 'draggable' : ''}"
             ${dragAttrs}
             data-episode-id="${ep.id}">
            <div class="episode-header">
                ${inPlaylist ? '<span class="drag-handle">⠿</span>' : ''}
                <h3>${ep.title}</h3>
                <span class="episode-date">${date}</span>
            </div>
            ${headlines ? `<ul class="headlines">${headlines}</ul>` : ""}
            <div class="episode-footer">
                <audio controls src="/episodes/${ep.id}/audio" preload="none">
                    Your browser does not support audio.
                </audio>
                ${actionBtn}
            </div>
            <!-- Playlist picker (hidden) -->
            <div class="playlist-picker" id="picker-${ep.id}" style="display:none;"></div>
        </div>`;
    }).join("");

    if (inPlaylist) setupDragAndDrop();
}

// ===========================================================================
// PLAYLISTS — SIDEBAR
// ===========================================================================
async function loadPlaylists() {
    const container = document.getElementById("playlist-list");
    try {
        const res = await fetch("/playlists", { credentials: "include" });
        if (!res.ok) return;
        const data = await res.json();
        if (data.playlists.length === 0) {
            container.innerHTML = '<p class="sidebar-empty">No playlists yet.</p>';
            return;
        }
        container.innerHTML = data.playlists.map(p => `
            <div class="playlist-item ${currentPlaylistId === p.id ? 'active' : ''}"
                 id="pl-${p.id}"
                 onclick="openPlaylist('${p.id}', '${escHtml(p.name)}')">
                <span class="pl-icon">🎙️</span>
                <span class="pl-name">${escHtml(p.name)}</span>
            </div>
        `).join("");
    } catch (err) {
        console.error("Failed to load playlists", err);
    }
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
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name })
        });
        if (!res.ok) { alert("Failed to create playlist."); return; }
        hideCreatePlaylist();
        loadPlaylists();
    } catch (err) {
        alert("Failed to create playlist.");
    }
}

async function openPlaylist(pid, name) {
    currentPlaylistId = pid;

    // Highlight in sidebar
    document.querySelectorAll(".playlist-item").forEach(el => el.classList.remove("active"));
    const el = document.getElementById(`pl-${pid}`);
    if (el) el.classList.add("active");

    document.getElementById("content-title").textContent = name;
    document.getElementById("playlist-actions").style.display = "flex";
    document.getElementById("share-box").style.display = "none";

    const container = document.getElementById("episodes-list");
    container.innerHTML = "<p>Loading...</p>";

    try {
        const res = await fetch(`/playlists/${pid}/items`, { credentials: "include" });
        if (!res.ok) { container.innerHTML = "<p>Failed to load playlist.</p>"; return; }
        const data = await res.json();
        renderEpisodes(data.items, container, true);
    } catch (err) {
        container.innerHTML = "<p class='error-box'>Failed to load playlist.</p>";
    }
}

async function renamePlaylistPrompt() {
    if (!currentPlaylistId) return;
    const newName = prompt("New playlist name:");
    if (!newName || !newName.trim()) return;

    try {
        const res = await fetch(`/playlists/${currentPlaylistId}`, {
            method: "PATCH",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName.trim() })
        });
        if (!res.ok) { alert("Failed to rename."); return; }
        document.getElementById("content-title").textContent = newName.trim();
        loadPlaylists();
    } catch (err) {
        alert("Failed to rename playlist.");
    }
}

async function deletePlaylist() {
    if (!currentPlaylistId) return;
    if (!confirm("Delete this playlist? Episodes will not be deleted.")) return;

    try {
        await fetch(`/playlists/${currentPlaylistId}`, {
            method: "DELETE",
            credentials: "include"
        });
        currentPlaylistId = null;
        loadPlaylists();
        loadEpisodes();
    } catch (err) {
        alert("Failed to delete playlist.");
    }
}

// ===========================================================================
// ADD TO PLAYLIST
// ===========================================================================
async function showAddToPlaylist(episodeId, btn) {
    const picker = document.getElementById(`picker-${episodeId}`);

    // Toggle off
    if (picker.style.display === "block") {
        picker.style.display = "none";
        return;
    }

    // Load playlists into picker
    try {
        const res  = await fetch("/playlists", { credentials: "include" });
        const data = await res.json();

        if (data.playlists.length === 0) {
            picker.innerHTML = '<p class="picker-empty">No playlists. Create one first.</p>';
        } else {
            picker.innerHTML = data.playlists.map(p => `
                <div class="picker-item"
                     onclick="addToPlaylist('${p.id}', '${episodeId}', '${escHtml(p.name)}')">
                    🎵 ${escHtml(p.name)}
                </div>
            `).join("");
        }
        picker.style.display = "block";
    } catch (err) {
        picker.innerHTML = '<p class="picker-empty">Failed to load playlists.</p>';
        picker.style.display = "block";
    }
}

async function addToPlaylist(playlistId, episodeId, playlistName) {
    try {
        const res = await fetch(`/playlists/${playlistId}/items`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ episode_id: episodeId })
        });
        const data = await res.json();
        if (res.status === 409) {
            alert("Episode already in playlist.");
        } else if (!res.ok) {
            alert("Failed to add episode.");
        } else {
            // Hide picker and show brief confirmation
            document.getElementById(`picker-${episodeId}`).style.display = "none";
            alert(`✅ Added to "${playlistName}"`);
        }
    } catch (err) {
        alert("Failed to add episode.");
    }
}

async function removeFromPlaylist(itemId) {
    if (!currentPlaylistId) return;
    if (!confirm("Remove this episode from the playlist?")) return;

    try {
        await fetch(`/playlists/${currentPlaylistId}/items/${itemId}`, {
            method: "DELETE",
            credentials: "include"
        });
        openPlaylist(currentPlaylistId,
            document.getElementById("content-title").textContent);
    } catch (err) {
        alert("Failed to remove episode.");
    }
}

// ===========================================================================
// SHARE
// ===========================================================================
async function sharePlaylist() {
    if (!currentPlaylistId) return;
    const shareBox = document.getElementById("share-box");

    // Toggle off
    if (shareBox.style.display === "block") {
        shareBox.style.display = "none";
        return;
    }

    try {
        const res  = await fetch(`/playlists/${currentPlaylistId}/share`, {
            method: "POST",
            credentials: "include"
        });
        const data = await res.json();
        const url  = `${window.location.origin}${data.share_url}`;
        document.getElementById("share-url").textContent = url;
        shareBox.dataset.url = url;
        shareBox.style.display = "block";
    } catch (err) {
        alert("Failed to generate share link.");
    }
}

function copyShareLink() {
    const url = document.getElementById("share-box").dataset.url;
    navigator.clipboard.writeText(url).then(() => alert("Link copied!"));
}

async function revokeShare() {
    if (!currentPlaylistId) return;
    if (!confirm("Revoke this share link?")) return;

    try {
        await fetch(`/playlists/${currentPlaylistId}/share`, {
            method: "DELETE",
            credentials: "include"
        });
        document.getElementById("share-box").style.display = "none";
        alert("Share link revoked.");
    } catch (err) {
        alert("Failed to revoke share link.");
    }
}

// ===========================================================================
// DRAG AND DROP (reorder)
// ===========================================================================
function setupDragAndDrop() {
    const cards = document.querySelectorAll(".episode-card.draggable");

    cards.forEach(card => {
        card.addEventListener("dragstart", e => {
            dragSrcItemId = card.dataset.itemId;
            card.classList.add("dragging");
            e.dataTransfer.effectAllowed = "move";
        });

        card.addEventListener("dragend", () => {
            card.classList.remove("dragging");
            document.querySelectorAll(".episode-card").forEach(c =>
                c.classList.remove("drag-over")
            );
        });

        card.addEventListener("dragover", e => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            card.classList.add("drag-over");
        });

        card.addEventListener("dragleave", () => {
            card.classList.remove("drag-over");
        });

        card.addEventListener("drop", async e => {
            e.preventDefault();
            card.classList.remove("drag-over");
            if (dragSrcItemId === card.dataset.itemId) return;

            // Get new order from DOM
            const container = document.getElementById("episodes-list");
            const allCards  = [...container.querySelectorAll(".episode-card.draggable")];

            // Swap in DOM
            const srcCard  = container.querySelector(`[data-item-id="${dragSrcItemId}"]`);
            const destCard = card;
            const srcIdx   = allCards.indexOf(srcCard);
            const destIdx  = allCards.indexOf(destCard);

            if (srcIdx < destIdx) {
                destCard.after(srcCard);
            } else {
                destCard.before(srcCard);
            }

            // Send new order to API
            const newOrder = [...container.querySelectorAll(".episode-card.draggable")]
                .map(c => c.dataset.itemId);

            try {
                await fetch(`/playlists/${currentPlaylistId}/items/reorder`, {
                    method: "PUT",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ items: newOrder })
                });
            } catch (err) {
                console.error("Reorder failed", err);
            }
        });
    });
}

// ===========================================================================
// GENERATE EPISODE
// ===========================================================================
async function generateEpisode() {
    const status = document.getElementById("generate-status");
    const btn    = document.getElementById("generate-btn");

    btn.textContent = "⏳ Generating...";
    btn.disabled    = true;
    status.textContent = "";

    try {
        const res = await fetch("/generate", {
            method: "POST",
            credentials: "include"
        });
        if (res.status === 401) { window.location.href = "/login"; return; }
        const data = await res.json();
        status.textContent = `✅ Started! Job: ${data.job_id}. Refreshing in 15s...`;
        setTimeout(() => {
            status.textContent = "";
            loadEpisodes();
        }, 15000);
    } catch (err) {
        status.textContent = "❌ Failed to start generation.";
    } finally {
        btn.textContent = "🎙️ Generate New Episode";
        btn.disabled    = false;
    }
}

// ===========================================================================
// UTILS
// ===========================================================================
function escHtml(str) {
    return str.replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#39;");
}