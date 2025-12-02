async function loadEpisodes() {
    const res = await fetch("/episodes");
    const data = await res.json();
    const container = document.getElementById("episodes");

    container.innerHTML = "";

    data.episodes.forEach(ep => {
        const div = document.createElement("div");
        div.className = "episode";

        div.innerHTML = `
            <h3>${ep.title}</h3>
            <p><strong>Headlines:</strong></p>
            <ul>
            ${JSON.parse(ep.headlines).map(h => `<li>${h}</li>`).join("")}
            </ul>
            <audio controls src="/episodes/${ep.id}/audio"></audio>
        `;

        container.appendChild(div);
    });
}

document.getElementById("generateBtn").onclick = async () => {
    const status = document.getElementById("status");
    status.innerText = "Generating new episode... this usually takes 30-60 seconds.";

    const res = await fetch("/generate", { method: "POST" });
    const data = await res.json();
    
    const jobId = data.job_id;

    // Poll Redis through API every 15 seconds
    const interval = setInterval(async () => {
        const latest = await fetch("/latest").then(r => r.json());
        if (latest.id === jobId) {
            clearInterval(interval);
            status.innerText = "New episode ready!";
            loadEpisodes();   // refresh only the episode list
        }
    }, 15000);
};

loadEpisodes();