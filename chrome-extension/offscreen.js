// ── Meetrix Offscreen — Capture audio + WebSocket ────────────────────────────

const SAMPLE_RATE    = 16000;
const CHUNK_SAMPLES  = 8192;   // ~0.512s par chunk (doit être une puissance de 2)

let audioContext    = null;
let scriptProcessor = null;
let mediaStream     = null;
let micStream       = null;
let wsConnection    = null;
let reconnectTimer  = null;
let currentBackend  = null;
let capturing       = false;
let currentSpeaker  = null;

// ── Écoute des messages ───────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === 'DO_CAPTURE') {
    startCapture(msg.streamId, msg.backendUrl);
  }
  if (msg.action === 'STOP_STREAM') {
    stopCapture();
  }
  if (msg.action === 'SET_SPEAKER' && msg.name !== currentSpeaker) {
    currentSpeaker = msg.name;
    if (wsConnection && wsConnection.readyState === WebSocket.OPEN) {
      wsConnection.send(JSON.stringify({ type: 'speaker', name: msg.name }));
    }
  }
});

// ── Démarrage ─────────────────────────────────────────────────────────────────

async function startCapture(streamId, backendUrl) {
  if (capturing) stopCapture();
  capturing = true;
  currentBackend = backendUrl;

  try {
    // Récupérer le flux audio de l'onglet Meet
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: streamId
        }
      },
      video: false
    });

    // Récupérer le micro de l'utilisateur (best effort)
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
      micStream = null; // micro non disponible, on continue sans
    }

    // Connexion WebSocket
    connectWebSocket(backendUrl);

    // Traitement audio — taux natif du système + rééchantillonnage à 16kHz
    audioContext = new AudioContext(); // taux natif (44100 sur macOS, 48000 sur Windows)
    await audioContext.resume();
    const nativeRate = audioContext.sampleRate;

    const summer = audioContext.createGain();
    const tabSource = audioContext.createMediaStreamSource(mediaStream);
    tabSource.connect(summer);
    if (micStream) {
      const micSource = audioContext.createMediaStreamSource(micStream);
      micSource.connect(summer);
    }

    // Taille du buffer adaptée au taux natif (~0.5s)
    const nativeChunk = Math.min(16384, Math.pow(2, Math.round(Math.log2(nativeRate * 0.5))));
    scriptProcessor = audioContext.createScriptProcessor(nativeChunk, 1, 1);

    scriptProcessor.onaudioprocess = (e) => {
      if (!wsConnection || wsConnection.readyState !== WebSocket.OPEN) return;
      const native  = e.inputBuffer.getChannelData(0);
      const resampled = downsample(native, nativeRate, SAMPLE_RATE);
      const int16   = new Int16Array(resampled.length);
      for (let i = 0; i < resampled.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, Math.round(resampled[i] * 32767)));
      }
      wsConnection.send(int16.buffer);
    };

    summer.connect(scriptProcessor);
    scriptProcessor.connect(audioContext.destination);

    notify('WS_STATUS', { status: 'capturing' });

  } catch (e) {
    notify('WS_STATUS', { status: 'error', message: e.message });
    capturing = false;
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function connectWebSocket(backendUrl) {
  const wsUrl = backendUrl.replace('http://', 'ws://').replace('https://', 'wss://') + '/ws/audio';

  try {
    wsConnection = new WebSocket(wsUrl);
  } catch (e) {
    notify('WS_STATUS', { status: 'error', message: e.message });
    scheduleReconnect(backendUrl);
    return;
  }

  wsConnection.onopen = () => {
    clearTimeout(reconnectTimer);
    notify('WS_STATUS', { status: 'connected' });
  };

  wsConnection.onclose = () => {
    notify('WS_STATUS', { status: 'disconnected' });
    if (capturing) scheduleReconnect(backendUrl);
  };

  wsConnection.onerror = (e) => {
    notify('WS_STATUS', { status: 'error', message: 'WebSocket error' });
  };

  wsConnection.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'final_segment') {
        notify('NEW_SEGMENT', { segment: data.data });
      } else if (data.type === 'partial_transcript') {
        notify('PARTIAL_SEGMENT', { text: data.data.text, start: data.data.start });
      }
    } catch (e) { /* ignore */ }
  };
}

function scheduleReconnect(backendUrl) {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    if (capturing) connectWebSocket(backendUrl);
  }, 2000);
}

// ── Arrêt ─────────────────────────────────────────────────────────────────────

function stopCapture() {
  capturing = false;
  clearTimeout(reconnectTimer);

  if (scriptProcessor) { scriptProcessor.disconnect(); scriptProcessor = null; }
  if (audioContext)    { audioContext.close().catch(() => {}); audioContext = null; }
  if (mediaStream)     { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
  if (micStream)       { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (wsConnection)    { wsConnection.close(); wsConnection = null; }

  notify('WS_STATUS', { status: 'stopped' });
}

// ── Rééchantillonnage linéaire ────────────────────────────────────────────────

function downsample(buffer, fromRate, toRate) {
  if (fromRate === toRate) return buffer;
  const ratio     = fromRate / toRate;
  const newLength = Math.round(buffer.length / ratio);
  const result    = new Float32Array(newLength);
  for (let i = 0; i < newLength; i++) {
    const src  = i * ratio;
    const low  = Math.floor(src);
    const high = Math.min(low + 1, buffer.length - 1);
    result[i]  = buffer[low] + (buffer[high] - buffer[low]) * (src - low);
  }
  return result;
}

// ── Utilitaire ────────────────────────────────────────────────────────────────

function notify(action, payload) {
  chrome.runtime.sendMessage({ action, ...payload }).catch(() => {});
}
