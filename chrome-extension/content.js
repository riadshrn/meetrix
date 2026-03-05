// ── Meetrix Content Script — Détection émotions dans Google Meet ──────────────

const EMOTION_EMOJI = {
  happy:     '😄',
  sad:       '😢',
  angry:     '😠',
  fearful:   '😨',
  disgusted: '🤢',
  surprised: '😲',
  neutral:   '😐'
};

const MODELS_URL = 'https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/weights';

let faceApiReady   = false;
let detectInterval = null;

// ── Chargement de face-api.js ─────────────────────────────────────────────────

function loadFaceApiScript() {
  return new Promise((resolve) => {
    const existing = document.querySelector('[data-meetrix-faceapi]');
    if (existing) { resolve(typeof faceapi !== 'undefined'); return; }

    const script = document.createElement('script');
    script.src = chrome.runtime.getURL('libs/face-api.min.js');
    script.dataset.meetrixFaceapi = '1';
    script.onload  = () => resolve(true);
    script.onerror = () => resolve(false);
    (document.head || document.documentElement).appendChild(script);
  });
}

async function initFaceApi() {
  const loaded = await loadFaceApiScript();
  if (!loaded || typeof faceapi === 'undefined') {
    console.info('[Meetrix] face-api.js non trouvé — émotions désactivées. Placez face-api.min.js dans chrome-extension/libs/');
    return false;
  }

  try {
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(MODELS_URL),
      faceapi.nets.faceExpressionNet.loadFromUri(MODELS_URL)
    ]);
    faceApiReady = true;
    console.info('[Meetrix] face-api.js prêt ✓');
    return true;
  } catch (e) {
    console.warn('[Meetrix] Chargement modèles échoué:', e.message);
    return false;
  }
}

// ── Observation des vidéos ────────────────────────────────────────────────────

function observeVideos() {
  const tryStart = () => {
    const videos = document.querySelectorAll('video');
    if (videos.length > 0 && !detectInterval) {
      startDetection();
    }
  };

  tryStart();

  const observer = new MutationObserver(tryStart);
  observer.observe(document.body, { childList: true, subtree: true });
}

// ── Détection ─────────────────────────────────────────────────────────────────

function startDetection() {
  if (detectInterval) return;
  detectInterval = setInterval(runDetection, 2500);
}

async function runDetection() {
  if (!faceApiReady || typeof faceapi === 'undefined') return;

  const videos  = Array.from(document.querySelectorAll('video'))
    .filter(v => v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0)
    .slice(0, 8); // max 8 participants

  const results = [];

  for (let i = 0; i < videos.length; i++) {
    const video = videos[i];
    try {
      const canvas = document.createElement('canvas');
      canvas.width  = Math.min(video.videoWidth,  320);
      canvas.height = Math.min(video.videoHeight, 240);
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);

      const detection = await faceapi
        .detectSingleFace(canvas, new faceapi.TinyFaceDetectorOptions({ scoreThreshold: 0.3 }))
        .withFaceExpressions();

      if (!detection) continue;

      const expressions = detection.expressions;
      const dominant    = Object.entries(expressions).sort((a, b) => b[1] - a[1])[0];
      const scores      = Object.fromEntries(
        Object.entries(expressions).map(([k, v]) => [k, Math.round(v * 100)])
      );

      // Overlay emoji sur la vidéo
      placeOverlay(video, dominant[0]);

      results.push({
        id:       `participant_${i}`,
        label:    getParticipantLabel(video, i),
        dominant: dominant[0],
        score:    Math.round(dominant[1] * 100),
        scores
      });

    } catch (e) { /* skip cette vidéo */ }
  }

  if (results.length > 0) {
    chrome.runtime.sendMessage({ action: 'EMOTIONS_UPDATE', emotions: results }).catch(() => {});
  }
}

// ── Overlay emoji ─────────────────────────────────────────────────────────────

function placeOverlay(video, emotion) {
  const container = video.closest('[data-participant-id]') || video.parentElement;
  if (!container) return;

  let overlay = container.querySelector('.meetrix-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.className = 'meetrix-overlay';
    if (getComputedStyle(container).position === 'static') {
      container.style.position = 'relative';
    }
    container.appendChild(overlay);
  }
  overlay.textContent = EMOTION_EMOJI[emotion] || '😐';
  overlay.title = emotion;
}

// ── Label du participant ───────────────────────────────────────────────────────

function getParticipantLabel(video, index) {
  const container = video.closest('[data-participant-id]') || video.parentElement;
  if (container) {
    const nameEl = container.querySelector('[data-self-name], .display-name, [jsname="r4nke"]');
    if (nameEl && nameEl.textContent.trim()) return nameEl.textContent.trim();
  }
  return `Participant ${index + 1}`;
}

// ── Init ──────────────────────────────────────────────────────────────────────

(async () => {
  const ok = await initFaceApi();
  if (ok) observeVideos();
})();
