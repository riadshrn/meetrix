@echo off
setlocal

echo.
echo  ==========================================
echo   Meetrix - Lancement hybride
echo   Backend : Docker   Frontend : Windows
echo  ==========================================
echo.

REM --- 1. Verifier que Docker est disponible ---
docker info >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Docker Desktop n'est pas demarre.
    echo Lancez Docker Desktop puis reessayez.
    pause
    exit /b 1
)

REM --- 2. Demarrer le backend en Docker ---
echo [1/3] Demarrage du backend (Docker)...
docker compose up backend -d --build
if %errorlevel% neq 0 (
    echo [ERREUR] Le backend n'a pas pu demarrer.
    pause
    exit /b 1
)

REM --- 3. Attendre que le backend soit pret ---
echo [2/3] Attente du backend (health check)...
:wait_loop
timeout /t 2 /nobreak >nul
curl -s http://localhost:8000/health >nul 2>&1
if %errorlevel% neq 0 goto wait_loop
echo [OK] Backend pret sur http://localhost:8000

REM --- 4. Verifier que streamlit est installe ---
python -m streamlit --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Streamlit non trouve. Installation des dependances frontend...
    pip install -r requirements-frontend.txt
    if %errorlevel% neq 0 (
        echo [ERREUR] Echec de l'installation. Verifiez que Python est installe.
        pause
        exit /b 1
    )
)

REM --- 5. Lancer le frontend sur Windows ---
echo [3/3] Demarrage du frontend Streamlit...
echo.
echo  --> App disponible sur http://localhost:8501
echo  --> Ctrl+C pour arreter le frontend
echo  --> "docker compose stop backend" pour arreter le backend
echo.

python -m streamlit run frontend/app.py --server.port=8501

REM --- Arreter le backend quand le frontend est ferme ---
echo.
echo [INFO] Frontend arrete. Arret du backend...
docker compose stop backend

endlocal
