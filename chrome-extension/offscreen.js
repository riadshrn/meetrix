// ── Meetrix Offscreen — Capture audio + WebSocket ────────────────────────────

const SAMPLE_RATE    = 16000;
const CHUNK_SAMPLES  = 8000;   // 0.5s par chunk

let audioContext    = null;
let scriptProcessor = null;
let mediaStream     = null;
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

    // Connexion WebSocket
    connectWebSocket(backendUrl);

    // Traitement audio
    audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
    const source = audioContext.createMediaStreamSource(mediaStream);
    scriptProcessor = audioContext.createScriptProcessor(CHUNK_SAMPLES, 1, 1);

    scriptProcessor.onaudioprocess = (e) => {
      if (!wsConnection || wsConnection.readyState !== WebSocket.OPEN) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const int16   = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
      }
      wsConnection.send(int16.buffer);
    };

    source.connect(scriptProcessor);
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
  if (wsConnection)    { wsConnection.close(); wsConnection = null; }

  notify('WS_STATUS', { status: 'stopped' });
}

// ── Utilitaire ────────────────────────────────────────────────────────────────

function notify(action, payload) {
  chrome.runtime.sendMessage({ action, ...payload }).catch(() => {});
}
