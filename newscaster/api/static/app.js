document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("episodes-list")) {
        loadEpisodes();
    }
});

// ---------------------------------------------------------------------------
// Load all episodes
// ---------------------------------------------------------------------------
async function loadEpisodes() {
    const container = document.getElementById("episodes-list");
    container.innerHTML = "<p>Loading episodes...</p>";
    try {
        const res = await fetch("/episodes", {
            credentials: "include"
        });
        if (res.status === 401) {
            container.innerHTML = '<p><a href="/login">Login to view episodes</a></p>';
            return;
        }
        const data = await res.json();
        renderEpisodes(data.episodes, container);
    } catch (err) {
        container.innerHTML = `<p class="error-box">Failed to load episodes.</p>`;
    }
}

// ---------------------------------------------------------------------------
// Search episodes
// ---------------------------------------------------------------------------
async function searchEpisodes() {
    const q         = document.getElementById("search-query").value.trim();
    const fromDate  = document.getElementById("from-date").value;
    const toDate    = document.getElementById("to-date").value;
    const container = document.getElementById("episodes-list");
    const searchBtn = document.getElementById("search-btn");

    if (!q && !fromDate && !toDate) {
        loadEpisodes();
        return;
    }

    searchBtn.textContent = "⏳ Searching...";
    searchBtn.disabled = true;

    const params = new URLSearchParams();
    if (q)        params.append("q", q);
    if (fromDate) params.append("from_date", fromDate);
    if (toDate)   params.append("to_date", toDate);

    container.innerHTML = "<p>Searching...</p>";

    try {
        const res = await fetch(`/episodes/search?${params.toString()}`, {
            credentials: "include"
        });
        if (res.status === 401) {
            container.innerHTML = '<p><a href="/login">Login to search episodes</a></p>';
            return;
        }
        const data = await res.json();
        if (data.results.length === 0) {
            container.innerHTML = "<p>No episodes found matching your search.</p>";
            return;
        }
        renderEpisodes(data.results, container);
    } catch (err) {
        container.innerHTML = `<p class="error-box">Search failed. Please try again.</p>`;
    } finally {
        searchBtn.textContent = "🔍 Search";
        searchBtn.disabled = false;
    }
}

// ---------------------------------------------------------------------------
// Clear search
// ---------------------------------------------------------------------------
function clearSearch() {
    document.getElementById("search-query").value = "";
    document.getElementById("from-date").value = "";
    document.getElementById("to-date").value = "";
    loadEpisodes();
}

// ---------------------------------------------------------------------------
// Render episode cards
// ---------------------------------------------------------------------------
function renderEpisodes(episodes, container) {
    if (!episodes || episodes.length === 0) {
        container.innerHTML = "<p>No episodes yet. Generate your first one!</p>";
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

        return `
        <div class="episode-card">
            <div class="episode-header">
                <h3>${ep.title}</h3>
                <span class="episode-date">${date}</span>
            </div>
            ${headlines ? `<ul class="headlines">${headlines}</ul>` : ""}
            <audio controls src="/episodes/${ep.id}/audio" preload="none">
                Your browser does not support audio.
            </audio>
        </div>`;
    }).join("");
}

// ---------------------------------------------------------------------------
// Generate new episode
// ---------------------------------------------------------------------------
async function generateEpisode() {
    const status = document.getElementById("generate-status");
    const btn    = document.getElementById("generate-btn");

    btn.textContent = "⏳ Generating...";
    btn.disabled = true;
    status.textContent = "";

    try {
        const res = await fetch("/generate", {
            method: "POST",
            credentials: "include"
        });
        if (res.status === 401) {
            window.location.href = "/login";
            return;
        }
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
        btn.disabled = false;
    }
}