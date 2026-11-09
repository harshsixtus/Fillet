# Fillet - one-command local start on Windows (PowerShell):  .\run.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment (Python 3.11)..."
    py -3.11 -m venv .venv
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -r requirements.txt
}
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env - add your GROQ_API_KEY and/or MISTRAL_API_KEY, then run this again." -ForegroundColor Yellow
    exit 1
}
.\.venv\Scripts\streamlit run app.py
