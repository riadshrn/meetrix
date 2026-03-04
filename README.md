# 🎙️ Meeting AI Assistant

> Transcription temps réel • Analyse IA Mistral • Compte-rendu automatique • Google Calendar

Application complète de support de réunion tournant **en local** sur votre PC. Aucun bot ne rejoint Google Meet — vous capturez l'audio via votre micro ou un micro virtuel.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      NAVIGATEUR / STREAMLIT                      │
│  Page 1: Transcription  │ Page 2: Stats │ Page 3: Rapport       │
│  Page 4: Q&A            │ Page 5: Calendar                      │
└────────────────┬──────────────────────────┬────────────────────┘
                 │ HTTP REST                │ WebSocket /ws/audio
                 ▼                          ▼
┌────────────────────────────────────────────────────────────────┐
│                     FASTAPI BACKEND                             │
│  /start  /stop  /report  /qa  /state  /calendar                │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  MeetingManager  │  │  ASR Service │  │   LLM Service    │  │
│  │  (orchestrateur) │  │ faster-whis- │  │   (Mistral API)  │  │
│  │                  │  │ per streaming│  │                  │  │
│  └─────────────────┘  └──────────────┘  └──────────────────┘  │
│  ┌─────────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Stats Service   │  │Export Service│  │ Calendar Service │  │
│  │ (speaker/kw/km) │  │  (MD + PDF)  │  │  (Google OAuth)  │  │
│  └─────────────────┘  └──────────────┘  └──────────────────┘  │
└────────────────────────────────────────────────────────────────┘
         │ audio chunks (PCM 16kHz)
         ▼
┌────────────────────┐
│   MICRO / SYSTÈME  │
│  sounddevice       │
│  (ou micro virtuel)│
└────────────────────┘
```

### Modules principaux

| Module | Rôle |
|--------|------|
| `backend/api/main.py` | FastAPI app, WebSocket, endpoints REST |
| `backend/models/meeting.py` | Modèles Pydantic (TranscriptSegment, MeetingState...) |
| `backend/services/asr_service.py` | ASR streaming avec faster-whisper |
| `backend/services/llm_service.py` | Mistral API (résumé, action items, Q&A) |
| `backend/services/stats_service.py` | Temps de parole, mots clés, moments clés |
| `backend/services/meeting_manager.py` | Orchestrateur central |
| `backend/services/export_service.py` | Export Markdown + PDF |
| `backend/services/calendar_service.py` | Google Calendar OAuth |
| `frontend/pages/1_transcription.py` | UI transcription live |
| `frontend/pages/2_stats.py` | Graphiques (bar, mots, timeline) |
| `frontend/pages/3_Compte_rendu.py` | Compte rendu IA, historique, Google Tasks |
| `frontend/pages/4_qa.py` | Assistant Q&A chat |
| `frontend/pages/5_calendar.py` | Création événement Calendar |

---

## 📁 Structure du repo

```
meeting-ai-assistant/
├── backend/
│   ├── __init__.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── main.py              # FastAPI + WebSocket
│   ├── models/
│   │   ├── __init__.py
│   │   └── meeting.py           # Pydantic models
│   └── services/
│       ├── __init__.py
│       ├── asr_service.py       # faster-whisper streaming
│       ├── llm_service.py       # Mistral AI (3 prompts)
│       ├── stats_service.py     # Speaker stats, keywords
│       ├── meeting_manager.py   # Orchestrateur
│       ├── export_service.py    # MD + PDF
│       └── calendar_service.py  # Google Calendar
├── frontend/
│   ├── app.py                   # Streamlit home
│   ├── components/              # Composants réutilisables
│   └── pages/
│       ├── 1_transcription.py   # Live transcription + audio
│       ├── 2_stats.py           # Graphiques
│       ├── 3_Compte_rendu.py    # Compte rendu IA + Google Tasks
│       ├── 4_qa.py              # Q&A chatbot
│       └── 5_calendar.py        # Google Calendar
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── docker-compose.yml
├── scripts/
│   └── start.sh                 # Script lancement local
├── exports/                     # Rapports générés (MD + PDF)
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Démarrage rapide (local)

### 1. Prérequis

```bash
Python 3.11+
ffmpeg  # pour faster-whisper
```

**Ubuntu/Debian :**
```bash
sudo apt install ffmpeg
```

**macOS :**
```bash
brew install ffmpeg
```

**Windows :**
```
Télécharger ffmpeg depuis https://ffmpeg.org/download.html
Ajouter au PATH système
```

### 2. Installation

```bash
# Cloner le projet
git clone <repo>
cd meeting-ai-assistant

# Environnement virtuel (recommandé)
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Installation dépendances
pip install -r requirements.txt
```

### 3. Configuration MISTRAL_API_KEY

```bash
cp .env.example .env
nano .env  # ou votre éditeur préféré
```

Dans `.env` :
```
MISTRAL_API_KEY=sk-...votre-clé-mistral...
```

Obtenez votre clé sur https://console.mistral.ai/

### 4. Lancement

**Option A — Script automatique :**
```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

**Option B — Manuel :**
```bash
# Terminal 1 : Backend
export MISTRAL_API_KEY=sk-...
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 : Frontend
streamlit run frontend/app.py --server.port 8501
```

**Accès :**
- 🌐 Frontend Streamlit : http://localhost:8501
- 📚 API Docs (Swagger) : http://localhost:8000/docs
- 🔌 WebSocket test : http://localhost:8000/health

---

## 🐳 Docker

```bash
# Créer le .env avec votre clé
cp .env.example .env
echo "MISTRAL_API_KEY=sk-..." >> .env

# Lancer avec docker-compose
cd docker
docker-compose up --build

# Ou en arrière-plan
docker-compose up -d --build
```

**Logs :**
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
```

**Arrêt :**
```bash
docker-compose down
```

---

## 📅 Activer Google Calendar & Google Tasks (OAuth)

Ces deux intégrations partagent les mêmes credentials OAuth. Les étapes suivantes les activent toutes les deux.

### Étapes

1. Allez sur https://console.cloud.google.com/
2. Créez un projet (ou sélectionnez un existant)
3. Activez les deux APIs dans **APIs & Services → Library** :
   - **Google Calendar API**
   - **Google Tasks API**
4. Créez des credentials OAuth 2.0 :
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Type : **Desktop application**
   - Téléchargez le JSON
5. Renommez-le `client_secret.json` et copiez-le à la **racine du projet**
6. Installez les dépendances :
   ```bash
   pip install google-api-python-client google-auth-oauthlib
   ```
7. L'application est en mode **Test** par défaut — ajoutez votre compte Gmail comme testeur :
   - APIs & Services → **OAuth consent screen** → **Audience** → **Test users** → Add users
8. Supprimez `token.json` si il existe déjà (pour forcer la ré-authentification avec les nouveaux scopes)
9. Au prochain lancement, un navigateur s'ouvrira pour l'autorisation
10. Le token est sauvegardé dans `token.json` (renouvellement automatique)

> ⚠️ Ne committez jamais `client_secret.json` ni `token.json` (déjà dans le `.gitignore`)

---

## 🎤 Micro virtuel (pour capturer Google Meet)

### Windows — VB-Audio Virtual Cable

**1. Installation et configuration de la capture**

```
1. Télécharger : https://vb-audio.com/Cable/
2. Installer et redémarrer
3. Dans Google Meet → Paramètres → Sortie audio → "CABLE Input (VB-Audio Virtual Cable)"
   (Meet envoie ainsi son audio dans le câble virtuel)
4. Dans Meetrix → sélectionner votre micro physique dans "🎙️ Mon Micro"
   (CABLE Output est détecté automatiquement comme source Meet)
```

**2. Monitoring — Pour entendre la réunion dans vos écouteurs**

Par défaut, router la sortie audio vers CABLE Input coupe le son dans vos écouteurs.
Pour continuer à entendre la réunion tout en capturant l'audio :

```
1. Ouvrir : Paramètres de son → Panneau de configuration Son → onglet Enregistrement
2. Clic droit sur "CABLE Output" → Propriétés → onglet Écouter
3. Cocher "Écouter ce périphérique"
4. Dans "Lire sur ce périphérique", sélectionner votre casque ou vos enceintes
5. Valider → vous entendez à nouveau la réunion, et Meetrix capture toujours l'audio
```

### macOS — BlackHole

```bash
brew install blackhole-2ch
```
```
1. Ouvrir "Audio MIDI Setup" (Applications → Utilitaires)
2. Créer un "Aggregate Device" avec BlackHole + votre micro
3. Créer un "Multi-Output Device" avec BlackHole + vos haut-parleurs
4. Dans Meet → Sortie audio = Multi-Output
5. Dans Meeting AI → Micro = BlackHole
```

### Linux — PulseAudio

```bash
# Créer un micro virtuel
pactl load-module module-null-sink sink_name=virtual_mic sink_properties=device.description="Virtual_Mic"
pactl load-module module-loopback source=virtual_mic.monitor

# Avec pavucontrol, router l'audio de Meet vers virtual_mic.monitor
pavucontrol
```

---

## 🔌 Protocole WebSocket

**Client → Serveur :**
```
bytes bruts : PCM int16, 16kHz, mono
JSON : {"type": "audio_base64", "data": "<base64>"}
JSON : {"type": "command", "cmd": "ping"|"status"}
```

**Serveur → Client (WSEvent JSON) :**
```json
{"type": "partial_transcript", "data": {"text": "...", "start": 12.5}}
{"type": "final_segment", "data": {"id": "...", "speaker": "...", "text": "...", ...}}
{"type": "stats_update", "data": {"speakers": {...}, "total_duration": 45.2}}
{"type": "llm_answer", "data": {"answer": "..."}}
{"type": "error", "data": {"message": "..."}}
{"type": "status", "data": {"message": "..."}}
```

---

## 🤖 Modèles Whisper disponibles

| Modèle | RAM | Vitesse | Qualité |
|--------|-----|---------|---------|
| `tiny` | ~1 GB | ⚡⚡⚡ | ★★☆☆☆ |
| `base` | ~1 GB | ⚡⚡ | ★★★☆☆ |
| `small` | ~2 GB | ⚡ | ★★★★☆ |
| `medium` | ~5 GB | 🐢 | ★★★★★ |
| `large-v3` | ~10 GB | 🐢🐢 | ★★★★★ |

Configurez dans `.env` :
```
WHISPER_MODEL=base
WHISPER_DEVICE=cpu  # ou cuda si GPU disponible
```

---

## 🧪 Test sans micro

L'application inclut un **mode simulation** qui génère des segments fictifs si `sounddevice` n'est pas installé ou si aucun micro n'est détecté. Idéal pour tester l'UI.

---

## 📋 Variables d'environnement

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `MISTRAL_API_KEY` | ✅ | Clé API Mistral |
| `BACKEND_URL` | ❌ | URL backend (défaut: http://localhost:8000) |
| `WHISPER_MODEL` | ❌ | Modèle Whisper (défaut: base) |
| `WHISPER_DEVICE` | ❌ | cpu ou cuda (défaut: cpu) |
| `LOG_LEVEL` | ❌ | Niveau de log (défaut: INFO) |

---

## 🛠️ Développement

```bash
# Linter
pip install ruff
ruff check backend/ frontend/

# Tests rapides API
curl http://localhost:8000/health
curl -X POST http://localhost:8000/start -H "Content-Type: application/json" \
     -d '{"title": "Test meeting"}'
```

---

## 📄 Licence

MIT — Projet développé pour un challenge IA 24h.
