// ── Meetrix Background Service Worker ────────────────────────────────────────

// PAS d'ouverture auto — on gère tout dans onClicked pour garder le user gesture
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(console.error);

// ── Clic sur l'icône extension ────────────────────────────────────────────────
// C'est ici qu'on est dans un "user gesture" valide pour tabCapture

chrome.action.onClicked.addListener(async (tab) => {
  // 1. Ouvrir le side panel sur cet onglet
  try {
    await chrome.sidePanel.open({ tabId: tab.id });
  } catch (e) {
    console.warn('[Meetrix] sidePanel.open error:', e.message);
  }

  // 2. Si on est sur Google Meet, obtenir le streamId MAINTENANT (user gesture actif)
  if (tab.url && tab.url.includes('meet.google.com')) {
    chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id }, (streamId) => {
      if (chrome.runtime.lastError || !streamId) {
        console.warn('[Meetrix] tabCapture.getMediaStreamId failed:', chrome.runtime.lastError?.message);
        chrome.storage.session.set({ streamIdStatus: 'error', streamIdError: chrome.runtime.lastError?.message });
        return;
      }
      // Stocker le streamId pour que le side panel puisse l'utiliser
      chrome.storage.session.set({
        pendingStreamId: streamId,
        pendingTabId:    tab.id,
        capturedAt:      Date.now()
      });
      console.info('[Meetrix] streamId prêt ✓');
    });
  } else {
    // Pas sur Meet — effacer le streamId précédent
    chrome.storage.session.remove(['pendingStreamId', 'pendingTabId', 'capturedAt']);
  }
});

// ── Offscreen helpers ─────────────────────────────────────────────────────────

async function hasOffscreen() {
  const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
  return contexts.length > 0;
}

async function createOffscreen() {
  if (await hasOffscreen()) return;
  await chrome.offscreen.createDocument({
    url:          'offscreen.html',
    reasons:      ['USER_MEDIA'],
    justification:'Capture audio de l\'onglet Google Meet pour transcription'
  });
}

async function closeOffscreen() {
  if (!(await hasOffscreen())) return;
  await chrome.offscreen.closeDocument();
}

// ── Message router ────────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.action === 'START_CAPTURE') {
    handleStartCapture(msg)
      .then(sendResponse)
      .catch(e => sendResponse({ error: e.message }));
    return true;
  }

  if (msg.action === 'STOP_CAPTURE') {
    handleStopCapture(msg.backendUrl)
      .then(sendResponse)
      .catch(e => sendResponse({ error: e.message }));
    return true;
  }

  return false;
});

// ── Start capture ─────────────────────────────────────────────────────────────

async function handleStartCapture({ streamId, backendUrl }) {
  if (!streamId) {
    return { error: 'streamId manquant.' };
  }

  try {
    await createOffscreen();
    await new Promise(r => setTimeout(r, 500));
    chrome.runtime.sendMessage({ action: 'DO_CAPTURE', streamId, backendUrl }).catch(() => {});
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
}

// ── Stop capture ──────────────────────────────────────────────────────────────

async function handleStopCapture(backendUrl) {
  chrome.runtime.sendMessage({ action: 'STOP_STREAM' }).catch(() => {});
  await new Promise(r => setTimeout(r, 1500));

  try { await fetch(`${backendUrl}/flush`, { method: 'POST' }); } catch (e) {}
  try { await fetch(`${backendUrl}/stop`,  { method: 'POST' }); } catch (e) {}

  await closeOffscreen();
  return { success: true };
}
