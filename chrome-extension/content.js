// ── Meetrix Content Script — Détection locuteur actif dans Google Meet ────────

// ── Label du participant ───────────────────────────────────────────────────────

function getParticipantLabel(video, index) {
  const container = video.closest('[data-participant-id]') || video.parentElement;
  if (container) {
    const nameEl = container.querySelector('[data-self-name], .display-name, [jsname="r4nke"]');
    if (nameEl && nameEl.textContent.trim()) return nameEl.textContent.trim();
  }
  return `Participant ${index + 1}`;
}

// ── Active speaker detection ───────────────────────────────────────────────────

let _lastActiveSpeaker = null;

function detectActiveSpeaker() {
  const tiles = document.querySelectorAll('[data-participant-id]');
  for (const tile of tiles) {
    const isTalking = (
      tile.getAttribute('data-is-talking') === 'true' ||
      tile.querySelector('[data-is-talking="true"]') !== null ||
      tile.querySelector('[data-ssrc]:not([hidden])') !== null
    );
    if (isTalking) {
      const video = tile.querySelector('video');
      const name  = getParticipantLabel(video, 0);
      if (name && name !== _lastActiveSpeaker) {
        _lastActiveSpeaker = name;
        chrome.runtime.sendMessage({ action: 'ACTIVE_SPEAKER', name }).catch(() => {});
      }
      return;
    }
  }
}

setInterval(detectActiveSpeaker, 500);
