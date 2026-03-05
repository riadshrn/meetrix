# Meetrix

> Transcription temps réel · Diarisation ECAPA-TDNN · Analyse IA Mistral · Compte-rendu automatique · Extension Chrome Google Meet

Application complète de support de réunion tournant **en local** sur votre machine. Aucun bot ne rejoint Google Meet — vous capturez l'audio via une extension Chrome et/ou un micro virtuel.

---

## 🏗️ Architecture

Deux interfaces utilisateur **complètes et indépendantes** — chacune permet de piloter une session et d'en consulter les résultats. Elles partagent le même backend et la même base de données.

```
        Interface 1                              Interface 2
┌───────────────────────────┐        ┌──────────────────────────────────────┐
│   CHROME EXTENSION (MV3)  │        │         STREAMLIT FRONTEND            │
│                           │        │                                       │
│  • Capture audio via      │        │  • Capture audio via micro physique  │
│    tabCapture (onglet      │        │    et/ou câble virtuel               │
│    navigateur directement)│        │    (VB-Audio / BlackHole)            │
│  • Panneau latéral :      │        │    → Google Meet aussi capturé       │
│    contrôles + résultats  │        │      si Meet routé vers le câble     │
│    (transcription, stats, │        │  • Pages :                            │
│     compte rendu, Q&A)    │        │    Accueil · Transcription · Stats    │
│                           │        │    Compte rendu · Q&A                 │
└──────┬─────────┬──────────┘        └──────┬──────────────────┬────────────┘
       │ audio   │ HTTP REST                 │ audio            │ HTTP REST
       │ WS      │ (résultats)               │ WS               │ (résultats)
       ▼         ▼                           ▼                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           FASTAPI BACKEND                                 │
│  /start  /stop  /flush  /reset  /state  /report  /qa                     │
│  /calendar/create  /tasks/create                                          │
│                                                                           │
│  ┌────────────────┐  ┌───────────────────────────────────────────┐       │
│  │ MeetingManager │  │              ASR Service                   │       │
│  │ (orchestrateur)│  │  Groq Whisper large-v3-turbo (STT)         │       │
│  │                │  │  ECAPA-TDNN speechbrain (diarisation)      │       │
│  └────────────────┘  └───────────────────────────────────────────┘       │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────┐           │
│  │   LLM Service  │  │  Stats Service  │  │  Export Service  │           │
│  │  (Mistral API) │  │ (speaker/kw)    │  │   (MD + PDF)     │           │
│  └────────────────┘  └─────────────────┘  └──────────────────┘           │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────┐       │
│  │                    Base de données SQLite                      │       │
│  │  Historique de tous les comptes rendus (toutes interfaces)     │       │
│  └───────────────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────────┘
```

### Pages

| Page | Rôle |
|------|------|
| 🏠 Accueil | Dashboard de présentation |
| 🎙️ Transcription | Transcription live, renommage intervenants, contrôles enregistrement |
| 📊 Statistiques | Temps de parole, mots clés, timeline |
| 🤖 Compte rendu | Résumé IA, décisions, points d'action, export PDF/MD, Google Tasks, planification Calendar |
| ❓ Q&A | Assistant question-réponse sur la réunion |

---

## 📁 Structure du repo

```
meetrix/
├── backend/
│   ├── api/
│   │   └── main.py              # FastAPI + WebSocket /ws/audio
│   ├── models/
│   │   └── meeting.py           # Pydantic models
│   └── services/
│       ├── asr_service.py       # STT Groq Whisper + diarisation ECAPA-TDNN
│       ├── llm_service.py       # Mistral AI (résumé, actions, Q&A)
│       ├── stats_service.py     # Speaker stats, mots-clés
│       ├── meeting_manager.py   # Orchestrateur
│       └── export_service.py    # MD + PDF
├── frontend/
│   ├── app.py                   # Streamlit home + navigation
│   ├── assets/                  # Logos et ressources statiques
│   └── pages/
│       ├── 1_transcription.py   # Live transcription + audio
│       ├── 2_stats.py           # Graphiques
│       ├── 3_Compte_rendu.py    # Compte rendu IA
│       └── 4_qa.py              # Q&A chatbot
├── chrome-extension/
│   ├── manifest.json            # MV3
│   ├── background.js            # tabCapture + offscreen lifecycle
│   ├── offscreen.js             # Capture audio + resampling 16kHz + WebSocket
│   ├── sidepanel.js             # UI panneau latéral
│   ├── sidepanel.html
│   └── offscreen.html
├── pretrained_models/           # Modèle ECAPA-TDNN (téléchargé au 1er lancement)
├── requirements.txt
├── .env                         # Variables d'environnement (non commité)
└── README.md
```

---

## 🚀 Installation

### 1. Prérequis

- Python 3.11+
- Git
- macOS / Windows / Linux
- Clés API Groq et Mistral (voir section Variables d'environnement)
- Docker Desktop (uniquement pour le lancement via Docker) : https://www.docker.com/products/docker-desktop/

### 2. Cloner et installer

```bash
git clone <repo>
cd meetrix

# Créer l'environnement virtuel
python -m venv venv
source venv/bin/activate       # macOS/Linux
# venv\Scripts\activate        # Windows

# Installer les dépendances
pip install -r requirements.txt
```

> **Note macOS** : si l'installation de `torchaudio` échoue, installez d'abord `torch` :
> ```bash
> pip install torch==2.2.2 torchaudio==2.2.2
> pip install -r requirements.txt
> ```

### 3. Configurer les clés API

Créer un fichier `.env` à la racine :

```env
MISTRAL_API_KEY=sk-...       # https://console.mistral.ai/
GROQ_API_KEY=gsk_...         # https://console.groq.com/ (gratuit)
LOG_LEVEL=INFO
```

- **Groq** : transcription Whisper large-v3-turbo (~500ms de latence, gratuit jusqu'à 20 req/min)
- **Mistral** : génération des comptes rendus, résumés et réponses Q&A

### 4. Lancer

**macOS / Linux**

Terminal 1 — Backend :
```bash
source venv/bin/activate
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

Terminal 2 — Frontend :
```bash
source venv/bin/activate
streamlit run frontend/app.py --server.port 8501
```

**Windows (PowerShell)**

Terminal 1 — Backend :
```powershell
venv\Scripts\Activate.ps1
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

Terminal 2 — Frontend :
```powershell
venv\Scripts\Activate.ps1
streamlit run frontend/app.py --server.port 8501
```

> **Note Windows PowerShell** : si l'exécution de scripts est bloquée, lancer d'abord :
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

> Le backend charge automatiquement le fichier `.env` au démarrage — aucune commande d'export manuelle n'est nécessaire.

> Au premier lancement, le modèle ECAPA-TDNN (~150 Mo) est téléchargé depuis HuggingFace dans `pretrained_models/`. Ce téléchargement se fait en arrière-plan — le serveur répond immédiatement, la diarisation démarre dès que le modèle est prêt.

**Accès :**
- 🌐 Interface : http://localhost:8501
- 📚 API Docs : http://localhost:8000/docs

---

## 🔌 Extension Chrome

> Prérequis : **Google Chrome** — https://www.google.com/chrome/

L'extension capture l'audio de l'onglet Google Meet directement dans le navigateur et l'envoie au backend via WebSocket.

### Installation

1. Ouvrir Chrome → `chrome://extensions/`
2. Activer le **Mode développeur** (coin supérieur droit)
3. Cliquer **Charger l'extension non empaquetée**
4. Sélectionner le dossier `chrome-extension/`

### Utilisation

1. Rejoindre une réunion Google Meet
2. Cliquer sur l'icône Meetrix dans la barre d'extensions
3. Dans le panneau latéral, configurer l'URL backend (`http://localhost:8000`)
4. Cliquer **▶ Démarrer** dans la page Transcription de Streamlit
5. Cliquer **▶ Lancer la capture** dans le panneau Chrome

> L'extension utilise `tabCapture` (MV3) — le streamId est généré au clic sur l'icône et expire après 25 secondes.

---

## 🎤 Micro virtuel (alternative à l'extension Chrome)

Pour capturer l'audio de Google Meet sans l'extension, utilisez un câble audio virtuel.

### macOS — BlackHole

```bash
brew install blackhole-2ch
```

1. Ouvrir **Audio MIDI Setup** (Applications → Utilitaires)
2. Créer un **Aggregate Device** : BlackHole 2ch + votre micro physique
3. Créer un **Multi-Output Device** : BlackHole 2ch + vos haut-parleurs/casque
4. Dans Google Meet → Paramètres → Sortie audio = Multi-Output Device
5. Dans Meetrix → la source Meet "BlackHole" est détectée automatiquement

### Windows — VB-Audio Virtual Cable

1. Télécharger et installer : https://vb-audio.com/Cable/
2. Dans Google Meet → Paramètres → Sortie audio = **CABLE Input (VB-Audio)**
3. Dans Meetrix → CABLE Output est détecté automatiquement comme source Meet

Pour continuer à entendre la réunion dans vos écouteurs :
1. Clic droit sur l'icône son (barre des tâches) → **Paramètres du son** (ou **Sons**)
2. Onglet **Enregistrement** — repère le périphérique **CABLE Output (VB-Audio Virtual Cable)**
3. Clic droit sur **CABLE Output** → **Propriétés**
4. Onglet **Écouter** → cocher **Écouter ce périphérique**
5. Menu déroulant **Lire sur ce périphérique** → sélectionner ton casque / tes haut-parleurs
6. **Appliquer** → OK

---

## 📋 Variables d'environnement

| Variable | Obligatoire | Description |
|----------|-------------|-------------|
| `MISTRAL_API_KEY` | ✅ | Clé API Mistral (comptes rendus, Q&A) |
| `GROQ_API_KEY` | ✅ | Clé API Groq (transcription Whisper) |
| `BACKEND_URL` | ❌ | URL backend vue du frontend (défaut: http://localhost:8000) |
| `LOG_LEVEL` | ❌ | Niveau de log (défaut: INFO) |

---

## 🔄 Pipeline audio détaillé

```
Micro physique  ─┐
                 ├─ mixage numpy → PCM int16 16kHz mono → WebSocket /ws/audio
Source Meet     ─┘   (sounddevice streams, ou extension Chrome)
(BlackHole/CABLE)
                                    │
                                    ▼
                     Backend accumule des chunks de 0.5s
                     Flush déclenché par :
                       - timer toutes les 4s (limite Groq 20 RPM)
                       - silence détecté (RMS < 0.004 sur 2 chunks)
                                    │
                                    ▼
                    ┌─── Groq Whisper large-v3-turbo ───┐
                    │  Transcription speech-to-text      │
                    │  Langue : fr (forcé)               │
                    │  Latence : ~500ms                  │
                    │  Filtrage hallucinations Whisper   │
                    └───────────────────────────────────┘
                                    │
                                    ▼
                    ┌─── ECAPA-TDNN (speechbrain) ───────┐
                    │  Diarisation : qui parle ?          │
                    │  Embeddings voix 192-dim            │
                    │  Cosine similarity ≥ 0.75 = même   │
                    │  locuteur                           │
                    │  Chargement en arrière-plan (≈30s) │
                    └────────────────────────────────────┘
                                    │
                                    ▼
                    Segment stocké (speaker, text, start, end)
                    + affiché live dans Streamlit (refresh 2s)
                                    │
                                    ▼
                    ┌─── Mistral AI ─────────────────────┐
                    │  À la demande (page Compte rendu)  │
                    │  - Résumé exécutif                 │
                    │  - Décisions prises                │
                    │  - Points d'action                 │
                    │  - Q&A sur la réunion              │
                    └────────────────────────────────────┘
```

---

## 📦 Dépendances principales

| Package | Version | Rôle |
|---------|---------|------|
| `fastapi` | 0.115.5 | Backend HTTP + WebSocket |
| `uvicorn` | 0.32.1 | Serveur ASGI |
| `httpx` | 0.27.2 | Appels API Groq (ASR) et Mistral (LLM) |
| `groq` | 1.0.0 | SDK Groq — Whisper large-v3-turbo |
| `faster-whisper` | 1.0.3 | Fallback ASR local (si pas de clé Groq) |
| `speechbrain` | 1.0.3 | Modèle ECAPA-TDNN pour diarisation |
| `torch` | 2.10.0 | Inférence ECAPA-TDNN |
| `torchaudio` | 2.10.0 | Traitement audio PyTorch |
| `sounddevice` | 0.5.1 | Capture micro + CABLE virtuel |
| `streamlit` | 1.40.0 | Interface web |
| `reportlab` | 4.2.5 | Export PDF |

---

## 🐳 Docker

> Prérequis : **Docker Desktop** installé et démarré — https://www.docker.com/products/docker-desktop/

C'est la méthode recommandée pour lancer l'application sans installer Python ni les dépendances manuellement.

### Lancement rapide

**1. Créer le fichier `.env` avec vos clés API :**

```bash
cp .env.example .env          # macOS/Linux
copy .env.example .env        # Windows CMD
Copy-Item .env.example .env   # Windows PowerShell
```

Puis éditer `.env` et renseigner `GROQ_API_KEY` et `MISTRAL_API_KEY`.

**2. Lancer :**

```bash
docker-compose up --build
```

> Le premier build télécharge torch (~500 Mo) et les dépendances — prévoir 5 à 10 minutes.
> Le modèle ECAPA-TDNN (~150 Mo) est téléchargé au premier démarrage du backend et mis en cache dans un volume Docker.

> **Limitations Docker (audio)** : les conteneurs n'ont pas accès aux périphériques audio de la machine hôte.
> - ❌ La transcription via **micro virtuel** (VB-Audio/BlackHole) dans Streamlit ne fonctionne pas
> - ✅ Le **mode Démo** fonctionne pour tester l'UI sans audio

**3. Accéder à l'application :**
- 🌐 Interface Streamlit : http://localhost:8501
- 📚 API Docs : http://localhost:8000/docs

### Autres commandes utiles

```bash
# En arrière-plan
docker-compose up -d --build

# Logs en temps réel
docker-compose logs -f backend
docker-compose logs -f frontend

# Arrêt
docker-compose down

# Arrêt + suppression des volumes (repart de zéro)
docker-compose down -v
```

### Google Calendar / Tasks (optionnel)

Sans `client_secret.json`, l'application fonctionne entièrement **sauf** deux boutons de la page Compte rendu :
- ❌ "Planifier la prochaine réunion" (Google Calendar)
- ❌ "Ajouter à Google Tasks"

Pour les activer dans Docker :

1. Suivre la section [Google Calendar (OAuth)](#-google-calendar-oauth-optionnel) pour obtenir `client_secret.json`
2. Décommenter les lignes suivantes dans `docker-compose.yml` :

```yaml
- ./client_secret.json:/app/client_secret.json:ro
- ./token.json:/app/token.json
```

> ⚠️ Ne monter ces fichiers que s'ils existent sur le disque — Docker créerait un dossier à la place si le fichier est absent.

---

## ✅ Google Tasks (OAuth, optionnel)

Les points d'action extraits par Mistral peuvent être envoyés directement dans **Google Tasks** en un clic depuis la page Compte rendu.

- Chaque action item affiche un bouton **"Ajouter à Google Tasks"**
- La tâche est créée dans la liste "My Tasks" de l'utilisateur connecté
- L'assigné et la date d'échéance sont inclus si disponibles
- Utilise la même authentification OAuth que Google Calendar (`client_secret.json`)

> Nécessite d'activer **Google Tasks API** dans Google Cloud Console (même projet que Calendar).

---

## 📅 Google Calendar (OAuth, optionnel)

L'intégration Google Calendar permet de planifier la prochaine réunion depuis la page Compte rendu.

1. Aller sur https://console.cloud.google.com/
2. Créer un projet → **APIs & Services → Library** → activer **Google Calendar API** et **Google Tasks API**
3. **Credentials → Create Credentials → OAuth client ID** → type : Desktop application
4. Télécharger le JSON → renommer en `client_secret.json` → placer à la racine du projet
5. **OAuth consent screen → Audience → Test users** → ajouter votre adresse Gmail
6. Au premier lancement, un navigateur s'ouvrira pour autoriser l'accès → `token.json` créé automatiquement

> ⚠️ Ne jamais committer `client_secret.json` ni `token.json` (déjà dans `.gitignore`)

---

## 🧪 Mode Démo

Cliquez sur **🎭 Démo** dans la page Transcription pour injecter des segments fictifs sans micro ni extension. Idéal pour tester l'UI et le compte rendu sans matériel audio.

---

## 📄 Licence

MIT — Projet développé dans le cadre d'un challenge Web Mining (M2 SISE).
