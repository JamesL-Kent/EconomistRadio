(function () {
  const audio = document.getElementById("radio-player");
  const message = document.getElementById("player-message");
  const engineState = document.getElementById("engine-state");
  const lastTitle = document.getElementById("last-title");
  const bufferSeconds = document.getElementById("buffer-seconds");
  const contentItems = document.getElementById("content-items");
  const lastError = document.getElementById("last-error");

  let hls;
  let currentSource = null;

  function setMessage(text) {
    message.textContent = text;
  }

  function attachStream(streamUrl) {
    if (!streamUrl || streamUrl === currentSource) {
      return;
    }

    currentSource = streamUrl;
    if (hls) {
      hls.destroy();
      hls = null;
    }

    if (window.Hls && typeof window.Hls.isSupported === "function" && window.Hls.isSupported()) {
      hls = new window.Hls({ enableWorker: true });
      hls.loadSource(streamUrl);
      hls.attachMedia(audio);
      setMessage("Live stream ready.");
      return;
    }

    if (audio.canPlayType("application/vnd.apple.mpegurl")) {
      audio.src = streamUrl;
      setMessage("Live stream ready.");
      return;
    }

    setMessage("This browser cannot play the HLS stream.");
  }

  async function refreshStatus() {
    try {
      const response = await fetch("/status", { credentials: "same-origin" });
      if (!response.ok) {
        throw new Error("Status request failed.");
      }

      const payload = await response.json();
      engineState.textContent = payload.running ? "Running" : "Starting";
      lastTitle.textContent = payload.last_title || "Waiting for first programme block";
      bufferSeconds.textContent = `${Math.round(payload.buffer_seconds || 0)}s`;
      contentItems.textContent = `${payload.content_items || 0}`;
      lastError.textContent = payload.last_error || "No errors reported.";

      const absoluteUrl = new URL(payload.stream_url, window.location.origin).toString();
      attachStream(absoluteUrl);
    } catch (error) {
      engineState.textContent = "Unavailable";
      setMessage("Unable to load stream status.");
      lastError.textContent = error instanceof Error ? error.message : "Unknown error";
    }
  }

  refreshStatus();
  window.setInterval(refreshStatus, 15000);
})();
