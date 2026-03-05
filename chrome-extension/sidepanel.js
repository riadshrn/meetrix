// ── Meetrix Side Panel ────────────────────────────────────────────────────────

const SPEAKER_COLORS = ['#6366f1','#ec4899','#10b981','#f59e0b','#3b82f6','#8b5cf6','#ef4444','#06b6d4'];
const MOMENT_COLORS  = { decision:'#10B981', action:'#F59E0B', question:'#3B82F6', risk:'#EF4444' };
const MOMENT_LABELS  = { decision:'✅ Décision', action:'📌 Action', question:'❓ Question', risk:'⚠️ Risque' };
const PRIO_LABELS    = { high:'Haute', medium:'Moyenne', low:'Faible' };
const PRIO_CLASS     = { high:'prio-high', medium:'prio-medium', low:'prio-low' };
const EMOTION_EMOJI  = { happy:'😄', sad:'😢', angry:'😠', fearful:'😨', disgusted:'🤢', surprised:'😲', neutral:'😐' };
const EMOTION_COLORS = { happy:'#10b981', sad:'#3b82f6', angry:'#ef4444', fearful:'#8b5cf6', disgusted:'#f59e0b', surprised:'#ec4899', neutral:'#9ca3af' };

// ── State ─────────────────────────────────────────────────────────────────────

let state = {
  recording:    false,
  backendUrl:   'http://localhost:8000',
  segments:     [],
  speakersStats:{},
  keywords:     [],
  keyMoments:   [],
  totalDuration: 0,
  report:       null,
  qaHistory:    [],
  emotions:     {},
  tasksSent:    {},
  wsStatus:     'disconnected',
  pollTimer:    null,
  settingsOpen: false,
};

// ── DOM ───────────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);

const el = {
  wsDot:         $('ws-dot'),
  recBadge:      $('rec-badge'),
  settingsPanel: $('settings-panel'),
  backendUrl:    $('backend-url'),
  saveSettings:  $('btn-save-settings'),
  btnSettings:   $('btn-settings'),
  meetingTitle:  $('meeting-title'),
  btnStart:      $('btn-start'),
  btnStop:       $('btn-stop'),
  btnReset:      $('btn-reset'),
  errorBox:      $('error-box'),
  partialBar:    $('partial-bar'),
  transcript:    $('transcript'),
  emptyLive:     $('empty-live'),
  statsContent:  $('stats-content'),
  btnGenerate:   $('btn-generate'),
  rapportEmpty:  $('rapport-empty'),
  rapportContent:$('rapport-content'),
  qaMessages:    $('qa-messages'),
  qaInput:       $('qa-input'),
  qaSend:        $('qa-send'),
  emotionsContent:$('emotions-content'),
};

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  // Charger le backend URL depuis le storage
  const stored = await chrome.storage.local.get(['backendUrl', 'meetingTitle']);
  if (stored.backendUrl)    { state.backendUrl = stored.backendUrl; el.backendUrl.value = stored.backendUrl; }
  if (stored.meetingTitle)  { el.meetingTitle.value = stored.meetingTitle; }

  setupTabs();
  setupListeners();
  setupMessageListener();

  // Vérifier si le streamId est disponible
  await checkStreamIdReady();

  // Récupérer l'état actuel du backend
  await syncState();
  startPolling();
});

// ── Stream ID check ───────────────────────────────────────────────────────────

async function checkStreamIdReady() {
  const stored = await chrome.storage.session.get(['pendingStreamId', 'streamIdStatus']);
  if (!stored.pendingStreamId && stored.streamIdStatus !== 'error') {
    // Pas encore de streamId — afficher un guide
    showError('⚠️ Pour activer la capture : allez sur l\'onglet Google Meet et recliquez sur l\'icône Meetrix dans la barre d\'outils Chrome.');
  } else if (stored.pendingStreamId) {
    showError(null); // streamId prêt
  }
}

// ── Tabs ──────────────────────────────────────────────────────────────────────

function setupTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      $('tab-' + btn.dataset.tab).classList.add('active');
    });
  });
}

// ── Listeners ─────────────────────────────────────────────────────────────────

function setupListeners() {
  // Settings
  el.btnSettings.addEventListener('click', () => {
    state.settingsOpen = !state.settingsOpen;
    el.settingsPanel.classList.toggle('hidden', !state.settingsOpen);
  });
  el.saveSettings.addEventListener('click', () => {
    state.backendUrl = el.backendUrl.value.trim().replace(/\/$/, '');
    chrome.storage.local.set({ backendUrl: state.backendUrl });
    el.settingsPanel.classList.add('hidden');
    showError(null);
  });

  // Controls
  el.btnStart.addEventListener('click', startRecording);
  el.btnStop.addEventListener('click',  stopRecording);
  el.btnReset.addEventListener('click', resetMeeting);

  el.meetingTitle.addEventListener('change', () => {
    chrome.storage.local.set({ meetingTitle: el.meetingTitle.value });
  });

  // Rapport
  el.btnGenerate.addEventListener('click', generateReport);

  // Q&A
  el.qaSend.addEventListener('click', sendQuestion);
  el.qaInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendQuestion(); });
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      el.qaInput.value = chip.dataset.q;
      sendQuestion();
    });
  });
}

// ── Message listener (offscreen + content) ────────────────────────────────────

function setupMessageListener() {
  chrome.runtime.onMessage.addListener((msg) => {
    switch (msg.action) {
      case 'WS_STATUS':
        setWsStatus(msg.status);
        if (msg.status === 'error' && msg.message) showError(`Audio: ${msg.message}`);
        if (msg.status === 'capturing') showError(null);
        break;
      case 'NEW_SEGMENT':
        addSegment(msg.segment);
        break;
      case 'PARTIAL_SEGMENT':
        showPartial(msg.text);
        break;
      case 'EMOTIONS_UPDATE':
        updateEmotions(msg.emotions);
        break;
    }
  });
}

// ── Recording controls ────────────────────────────────────────────────────────

async function startRecording() {
  const title      = el.meetingTitle.value.trim() || 'Réunion Meet';
  const backendUrl = state.backendUrl;

  showError(null);
  el.btnStart.disabled = true;
  el.btnStart.innerHTML = '<span class="spinner"></span>';

  try {
    // 1. Vérifier que le backend répond
    try {
      const health = await fetch(`${backendUrl}/health`, { signal: AbortSignal.timeout(3000) });
      if (!health.ok) throw new Error('Backend non disponible');
    } catch (e) {
      throw new Error(`Backend inaccessible (${backendUrl}) — Lancez start.bat d'abord.`);
    }

    // 2. Récupérer le streamId obtenu lors du clic sur l'icône extension
    const stored = await chrome.storage.session.get(['pendingStreamId', 'capturedAt', 'streamIdStatus', 'streamIdError']);

    if (stored.streamIdStatus === 'error') {
      throw new Error(`Capture audio impossible : ${stored.streamIdError || 'permission refusée'}. Rechargez la page Meet et recliquez sur l'icône Meetrix.`);
    }
    if (!stored.pendingStreamId) {
      throw new Error('⚠️ Fermez ce panel, allez sur l\'onglet Google Meet, puis recliquez sur l\'icône Meetrix pour activer la capture audio.');
    }

    const streamId = stored.pendingStreamId;

    // 3. Démarrer la réunion sur le backend
    const r = await fetch(`${backendUrl}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
      signal: AbortSignal.timeout(5000)
    });
    if (!r.ok && r.status !== 409) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Backend /start erreur ${r.status}`);
    }

    // 4. Passer le streamId au background pour créer l'offscreen
    const resp = await chrome.runtime.sendMessage({
      action: 'START_CAPTURE',
      streamId,
      backendUrl
    });

    if (resp && resp.error) throw new Error(resp.error);

    state.recording = true;
    setRecordingUI(true);
    startPolling();

  } catch (e) {
    showError(e.message);
    el.btnStart.disabled = false;
    el.btnStart.innerHTML = '▶ Démarrer';
  }
}

async function stopRecording() {
  el.btnStop.disabled = true;
  el.btnStop.innerHTML = '<span class="spinner"></span>';

  await chrome.runtime.sendMessage({
    action: 'STOP_CAPTURE',
    backendUrl: state.backendUrl
  });

  state.recording = false;
  setRecordingUI(false);
  setWsStatus('stopped');
  await syncState();
}

async function resetMeeting() {
  try {
    await fetch(`${state.backendUrl}/reset`, { method: 'POST' });
  } catch (e) { /* ignore */ }

  state.segments = [];
  state.speakersStats = {};
  state.keywords = [];
  state.keyMoments = [];
  state.totalDuration = 0;
  state.report = null;
  state.tasksSent = {};
  state.recording = false;

  setRecordingUI(false);
  renderTranscript();
  renderStats({});
  el.rapportContent.classList.add('hidden');
  el.rapportEmpty.classList.remove('hidden');
  el.qaMessages.innerHTML = '';
  showError(null);
}

function setRecordingUI(recording) {
  el.btnStart.disabled  =  recording;
  el.btnStop.disabled   = !recording;
  el.btnStart.innerHTML = '▶ Démarrer';
  el.btnStop.innerHTML  = '⏹ Arrêter';
  el.recBadge.classList.toggle('hidden', !recording);
}

// ── WebSocket status ──────────────────────────────────────────────────────────

function setWsStatus(status) {
  el.wsDot.className = 'ws-dot ' + (status === 'connected' || status === 'capturing' ? status : '');
  el.wsDot.title = status;
}

// ── Polling ───────────────────────────────────────────────────────────────────

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(syncState, 3000);
}

function stopPolling() {
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
}

async function syncState() {
  try {
    const r = await fetch(`${state.backendUrl}/state`, { signal: AbortSignal.timeout(4000) });
    if (!r.ok) return;
    const data = (await r.json()).state;
    if (!data) return;

    state.segments      = data.segments || [];
    state.speakersStats = data.speakers_stats || {};
    state.keywords      = data.keywords || [];
    state.keyMoments    = data.key_moments || [];
    state.totalDuration = data.total_duration || 0;
    state.recording     = !!data.is_recording;

    renderTranscript();
    renderStats(data);
    setRecordingUI(state.recording);
    setWsStatus(state.recording ? 'capturing' : 'connected');

  } catch (e) {
    setWsStatus('error');
  }
}

// ── Segment handling ──────────────────────────────────────────────────────────

function addSegment(seg) {
  // Éviter les doublons
  if (state.segments.find(s => s.id === seg.id)) return;
  state.segments.push(seg);
  appendSegmentCard(seg);
  hideEmpty();
}

function showPartial(text) {
  el.partialBar.textContent = text;
  el.partialBar.classList.remove('hidden');
  setTimeout(() => el.partialBar.classList.add('hidden'), 3000);
}

// ── Transcript render ─────────────────────────────────────────────────────────

function renderTranscript() {
  const segs = state.segments.filter(s => !s.is_partial);
  if (segs.length === 0) {
    hideEmpty(false);
    el.transcript.innerHTML = '';
    return;
  }
  hideEmpty(true);

  // Ne re-render que si le nombre a changé
  const current = el.transcript.querySelectorAll('.seg-card').length;
  if (current === segs.length) return;

  el.transcript.innerHTML = '';
  segs.forEach(s => appendSegmentCard(s, false));
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

function appendSegmentCard(seg, scroll = true) {
  const mt    = seg.moment_type || '';
  const color = MOMENT_COLORS[mt] || SPEAKER_COLORS[speakerIndex(seg.speaker) % SPEAKER_COLORS.length];
  const emoji = mt ? { decision:'✅', action:'📌', question:'❓', risk:'⚠️' }[mt] : '';
  const ts    = formatTime(seg.start || 0);

  const card = document.createElement('div');
  card.className = `seg-card ${mt}`;
  card.style.borderLeftColor = color;
  card.innerHTML = `
    <div class="seg-meta">
      <span class="seg-ts">[${ts}]</span>
      <span class="seg-speaker" style="color:${color}">${esc(seg.speaker || '?')}</span>
      ${emoji ? `<span class="seg-emoji">${emoji}</span>` : ''}
    </div>
    <div class="seg-text">${esc(seg.text || '')}</div>`;

  el.transcript.appendChild(card);
  if (scroll) el.transcript.scrollTop = el.transcript.scrollHeight;
}

function hideEmpty(hasData) {
  if (hasData === undefined) hasData = state.segments.filter(s => !s.is_partial).length > 0;
  el.emptyLive.classList.toggle('hidden', hasData);
}

// ── Stats render ──────────────────────────────────────────────────────────────

function renderStats(data) {
  const spk  = data.speakers_stats || {};
  const kw   = data.keywords || [];
  const km   = data.key_moments || [];
  const dur  = data.total_duration || 0;

  if (!Object.keys(spk).length && !kw.length && !km.length) {
    el.statsContent.innerHTML = '<div class="empty-state"><p>Aucune donnée — démarrez une réunion.</p></div>';
    return;
  }

  let html = '';

  // Durée
  html += `<div class="stats-section"><h3>⏱ Durée totale : ${formatTime(dur)}</h3></div>`;

  // Temps de parole
  if (Object.keys(spk).length) {
    html += '<div class="stats-section"><h3>🗣 Temps de parole</h3>';
    Object.entries(spk)
      .sort((a,b) => b[1].total_seconds - a[1].total_seconds)
      .forEach(([name, d], i) => {
        const color = SPEAKER_COLORS[i % SPEAKER_COLORS.length];
        html += `
          <div class="speaker-row">
            <div class="speaker-info">
              <span class="speaker-name" style="color:${color}">${esc(name)}</span>
              <span class="speaker-pct">${formatTime(d.total_seconds)} — ${d.percentage?.toFixed(0)}%</span>
            </div>
            <div class="progress-bar">
              <div class="progress-fill" style="width:${d.percentage||0}%;background:${color}"></div>
            </div>
          </div>`;
      });
    html += '</div>';
  }

  // Mots-clés
  if (kw.length) {
    html += '<div class="stats-section"><h3>🔤 Mots-clés</h3><div class="kw-cloud">';
    kw.slice(0, 25).forEach(k => {
      html += `<span class="kw-tag ${k.is_bigram ? 'bigram' : ''}">${esc(k.term)} <small>(${k.count})</small></span>`;
    });
    html += '</div></div>';
  }

  // Moments clés
  if (km.length) {
    html += '<div class="stats-section"><h3>⚡ Moments clés</h3>';
    km.forEach(m => {
      const cls   = MOMENT_COLORS[m.moment_type] ? `badge-${m.moment_type}` : '';
      const label = MOMENT_LABELS[m.moment_type] || m.moment_type;
      html += `
        <div class="moment-item">
          <span class="moment-badge ${cls}">${label}</span>
          <span class="moment-text">${esc((m.text||'').slice(0, 80))}</span>
          <span class="moment-ts">${formatTime(m.timestamp)}</span>
        </div>`;
    });
    html += '</div>';
  }

  el.statsContent.innerHTML = html;
}

// ── Rapport ───────────────────────────────────────────────────────────────────

async function generateReport() {
  el.btnGenerate.disabled = true;
  el.btnGenerate.innerHTML = '<span class="spinner"></span> Analyse Mistral AI…';

  try {
    const r = await fetch(`${state.backendUrl}/report`, {
      method: 'POST',
      signal: AbortSignal.timeout(120000)
    });

    if (r.status === 404) {
      showError('Aucune réunion disponible. Démarrez et arrêtez une réunion d\'abord.');
      return;
    }
    if (!r.ok) throw new Error(`Erreur ${r.status}`);

    const data = await r.json();
    state.report = data.report;
    renderReport(data.report);

  } catch (e) {
    showError(`Erreur génération : ${e.message}`);
  } finally {
    el.btnGenerate.disabled = false;
    el.btnGenerate.innerHTML = '🤖 Générer le compte rendu IA';
  }
}

function renderReport(report) {
  if (!report) return;
  el.rapportEmpty.classList.add('hidden');
  el.rapportContent.classList.remove('hidden');
  el.rapportContent.innerHTML = '';

  const dur   = Math.round(report.duration_minutes || 0);
  const parts = report.participants || [];
  const decs  = report.decisions || [];
  const acts  = report.action_items || [];
  const opens = report.open_points || [];
  const discs = report.discussed_points || [];

  // Hero
  el.rapportContent.innerHTML += `
    <div class="hero-card">
      <div class="hero-title">${esc(report.title || 'Réunion')}</div>
      <div class="hero-meta">Généré le ${formatDate(report.generated_at)}</div>
      <div class="hero-pills">
        <span class="pill">⏱ ${dur} min</span>
        <span class="pill">👥 ${parts.length} participant(s)</span>
        <span class="pill">✅ ${decs.length} décision(s)</span>
        <span class="pill">📌 ${acts.length} next step(s)</span>
      </div>
    </div>`;

  // Contexte
  if (report.context) {
    el.rapportContent.innerHTML += `
      <div class="report-section">
        <h4>🎯 Contexte</h4>
        <p style="font-size:12px;line-height:1.6">${esc(report.context)}</p>
      </div>`;
  }

  // Points discutés
  if (discs.length) {
    let items = discs.map(d => `<div class="report-item"><span>›</span><span>${esc(d)}</span></div>`).join('');
    el.rapportContent.innerHTML += `<div class="report-section"><h4>🗣 Points discutés</h4>${items}</div>`;
  }

  // Décisions
  if (decs.length) {
    let items = decs.map(d => `<div class="report-item"><span class="report-check">✓</span><span>${esc(d)}</span></div>`).join('');
    el.rapportContent.innerHTML += `<div class="report-section"><h4>✅ Décisions</h4>${items}</div>`;
  }

  // Next Steps
  if (acts.length) {
    const taskCards = acts.map((a, i) => {
      const tid  = a.id || `task_${i}`;
      const prio = a.priority || 'medium';
      const done = state.tasksSent[tid];
      return `
        <div class="task-card" id="task_${i}">
          <div class="task-title">${esc(a.task || '')}</div>
          <div class="task-meta">
            <span class="badge-prio ${PRIO_CLASS[prio]}">${PRIO_LABELS[prio]}</span>
            <span class="task-assignee">👤 ${esc(a.assignee || '?')}</span>
            ${a.due_date ? `<span class="task-due">📅 ${a.due_date}</span>` : ''}
          </div>
          <button class="btn-gtask ${done ? 'done' : ''}"
            onclick="addToTasks('${esc(tid)}', ${i})"
            ${done ? 'disabled' : ''}>
            ${done ? '✓ Ajouté' : '+ Google Tasks'}
          </button>
        </div>`;
    }).join('');
    el.rapportContent.innerHTML += `<div class="report-section"><h4>📌 Next Steps</h4>${taskCards}</div>`;
  }

  // Points ouverts
  if (opens.length) {
    let items = opens.map(p => `<div class="report-item"><span class="report-warn">⚠</span><span>${esc(p)}</span></div>`).join('');
    el.rapportContent.innerHTML += `<div class="report-section"><h4>❓ Points ouverts</h4>${items}</div>`;
  }

  // Exports
  el.rapportContent.innerHTML += `
    <div class="export-row">
      <button class="btn-export" onclick="exportMarkdown()">⬇ Markdown</button>
      <a class="btn-export" href="${buildMailto(report)}" target="_blank">✉ Envoyer par mail</a>
    </div>`;

  // Formulaire Calendar
  el.rapportContent.innerHTML += buildCalendarForm();
}

// ── Google Tasks ──────────────────────────────────────────────────────────────

window.addToTasks = async function(tid, index) {
  if (!state.report) return;
  const item = state.report.action_items[index];
  if (!item) return;

  try {
    const r = await fetch(`${state.backendUrl}/tasks/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        task:          item.task,
        assignee:      item.assignee,
        due_date:      item.due_date,
        meeting_title: state.report.title
      })
    });
    if (!r.ok) throw new Error(`Erreur ${r.status}`);
    state.tasksSent[tid] = true;
    const btn = document.querySelector(`#task_${index} .btn-gtask`);
    if (btn) { btn.textContent = '✓ Ajouté'; btn.classList.add('done'); btn.disabled = true; }
  } catch (e) {
    showError(`Tâche : ${e.message}`);
  }
};

// ── Calendar form ─────────────────────────────────────────────────────────────

function buildCalendarForm() {
  const nextWeek = new Date(Date.now() + 7 * 86400000);
  const d = nextWeek.toISOString().split('T')[0];
  return `
    <div class="cal-section mt-2">
      <h4>📅 Planifier la prochaine réunion</h4>
      <div class="cal-row">
        <input id="cal-title" class="input" placeholder="Titre" value="Suite — ${esc(state.report?.title || 'Réunion')}">
      </div>
      <div class="cal-row">
        <input id="cal-date" class="input" type="date" value="${d}">
        <input id="cal-time" class="input" type="time" value="14:00">
        <input id="cal-dur"  class="input" type="number" value="60" min="15" step="15" style="width:70px">
      </div>
      <div class="cal-row">
        <textarea id="cal-attendees" class="input" rows="2" placeholder="Emails (un par ligne)"></textarea>
      </div>
      <button class="btn btn-primary btn-sm" onclick="createCalendarEvent()">📅 Créer l'événement</button>
      <div id="cal-result" style="margin-top:6px;font-size:11px"></div>
    </div>`;
}

window.createCalendarEvent = async function() {
  const title    = $('cal-title')?.value.trim() || 'Prochaine réunion';
  const date     = $('cal-date')?.value;
  const time     = $('cal-time')?.value || '14:00';
  const dur      = parseInt($('cal-dur')?.value || 60);
  const rawAtts  = $('cal-attendees')?.value || '';
  const attendees= rawAtts.split('\n').map(e => e.trim()).filter(e => e.includes('@'));
  const dt       = `${date}T${time}:00`;

  const result   = $('cal-result');
  if (result) result.textContent = '⏳ Création…';

  try {
    const r = await fetch(`${state.backendUrl}/calendar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        meeting_id:           state.report?.meeting_id || 'ext',
        next_meeting_title:   title,
        next_meeting_datetime:dt,
        duration_minutes:     dur,
        attendees,
        timezone:             'Europe/Paris'
      })
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || `Erreur ${r.status}`);

    if (result) {
      result.innerHTML = `✅ Créé !
        ${data.html_link ? `<br><a href="${data.html_link}" target="_blank">Voir dans Google Calendar</a>` : ''}
        ${data.meet_link ? `<br><a href="${data.meet_link}" target="_blank">Lien Google Meet</a>` : ''}`;
    }
  } catch (e) {
    if (result) result.textContent = `❌ ${e.message}`;
  }
};

// ── Mailto helper ─────────────────────────────────────────────────────────────

function buildMailto(report) {
  const lines = [`Compte rendu — ${report.title || 'Réunion'}`, ''];
  if (report.context) lines.push('CONTEXTE', report.context, '');
  if (report.decisions?.length) {
    lines.push('DÉCISIONS');
    report.decisions.forEach(d => lines.push(`• ${d}`));
    lines.push('');
  }
  if (report.action_items?.length) {
    lines.push('NEXT STEPS');
    report.action_items.forEach(a => lines.push(`• [${a.assignee}] ${a.task}`));
    lines.push('');
  }
  return `mailto:?subject=${encodeURIComponent(`Compte rendu : ${report.title}`)}&body=${encodeURIComponent(lines.join('\n'))}`;
}

// ── Export Markdown ───────────────────────────────────────────────────────────

window.exportMarkdown = function() {
  const r = state.report;
  if (!r) return;
  const lines = [`# ${r.title}`, '', `> Généré le ${formatDate(r.generated_at)}`, ''];
  if (r.context) { lines.push('## Contexte', r.context, ''); }
  if (r.discussed_points?.length) { lines.push('## Points discutés'); r.discussed_points.forEach(p => lines.push(`- ${p}`)); lines.push(''); }
  if (r.decisions?.length)        { lines.push('## Décisions');       r.decisions.forEach(d => lines.push(`- ${d}`)); lines.push(''); }
  if (r.action_items?.length)     {
    lines.push('## Next Steps');
    r.action_items.forEach(a => lines.push(`- **[${a.assignee}]** ${a.task}${a.due_date ? ` — ${a.due_date}` : ''}`));
    lines.push('');
  }
  if (r.open_points?.length)      { lines.push('## Points ouverts'); r.open_points.forEach(p => lines.push(`- ${p}`)); }

  const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(blob);
  a.download = `${(r.title || 'rapport').replace(/\s+/g, '_')}.md`;
  a.click();
};

// ── Q&A ───────────────────────────────────────────────────────────────────────

async function sendQuestion() {
  const question = el.qaInput.value.trim();
  if (!question) return;

  el.qaInput.value = '';
  appendBubble('user', question);

  const typingId = appendBubble('assistant', '<span class="spinner"></span>');

  try {
    let meetingId = 'unknown';
    try {
      const sr = await fetch(`${state.backendUrl}/state`, { signal: AbortSignal.timeout(3000) });
      meetingId = ((await sr.json()).state || {}).meeting_id || 'unknown';
    } catch (e) { /* ignore */ }

    const r = await fetch(`${state.backendUrl}/qa`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, meeting_id: meetingId }),
      signal: AbortSignal.timeout(60000)
    });
    const data  = await r.json();
    const answer= r.ok ? (data.answer || 'Pas de réponse.') : `Erreur ${r.status}`;

    updateBubble(typingId, answer);
    state.qaHistory.push({ question, answer });

  } catch (e) {
    updateBubble(typingId, `❌ ${e.message}`);
  }
}

let bubbleCounter = 0;
function appendBubble(role, content) {
  const id  = `bubble_${bubbleCounter++}`;
  const div = document.createElement('div');
  div.id        = id;
  div.className = `qa-bubble qa-${role}`;
  div.innerHTML = content;
  el.qaMessages.appendChild(div);
  el.qaMessages.scrollTop = el.qaMessages.scrollHeight;
  return id;
}
function updateBubble(id, content) {
  const el2 = document.getElementById(id);
  if (el2) { el2.innerHTML = content; el.qaMessages.scrollTop = el.qaMessages.scrollHeight; }
}

// ── Emotions ──────────────────────────────────────────────────────────────────

function updateEmotions(emotions) {
  if (!emotions || !emotions.length) return;

  emotions.forEach(p => { state.emotions[p.id] = p; });

  const grid = document.createElement('div');
  grid.className = 'emotions-grid';

  Object.values(state.emotions).forEach(p => {
    const emoji = EMOTION_EMOJI[p.dominant] || '😐';
    const scores = p.scores || {};
    const bars = Object.entries(scores)
      .sort((a,b) => b[1] - a[1])
      .map(([emo, pct]) => `
        <div class="emo-row">
          <span class="emo-label">${EMOTION_EMOJI[emo]||''} ${emo}</span>
          <div class="emo-bar">
            <div class="emo-fill" style="width:${pct}%;background:${EMOTION_COLORS[emo]||'#9ca3af'}"></div>
          </div>
          <span class="emo-pct">${pct}%</span>
        </div>`).join('');

    grid.innerHTML += `
      <div class="emotion-card">
        <div class="emotion-header">
          <span class="emotion-emoji">${emoji}</span>
          <div>
            <div class="emotion-name">${esc(p.label || p.id)}</div>
            <div class="emotion-dominant">${p.dominant} (${p.score}%)</div>
          </div>
        </div>
        <div class="emotion-bars">${bars}</div>
      </div>`;
  });

  el.emotionsContent.innerHTML = '';
  el.emotionsContent.appendChild(grid);
}

// ── Error display ─────────────────────────────────────────────────────────────

function showError(msg) {
  if (msg) {
    el.errorBox.textContent = msg;
    el.errorBox.classList.remove('hidden');
  } else {
    el.errorBox.classList.add('hidden');
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTime(secs) {
  if (!secs && secs !== 0) return '0s';
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return m > 0 ? `${m}m${s.toString().padStart(2,'0')}s` : `${s}s`;
}

function formatDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString('fr-FR', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' }); }
  catch (e) { return iso; }
}

const speakerMap = {};
function speakerIndex(name) {
  if (!(name in speakerMap)) speakerMap[name] = Object.keys(speakerMap).length;
  return speakerMap[name];
}

function esc(str) {
  if (typeof str !== 'string') return '';
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
