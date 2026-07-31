# Start InsightHub - backend (FastAPI :8010) + frontend (Vite :5173).
# Loads .env if present. Close the two windows (or Ctrl+C in each) to stop.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# load .env into the environment
if (Test-Path ".env") {
  Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
      [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim())
    }
  }
}

if (-not $env:IH_SECRET_KEY) {
  Write-Host "[run] IH_SECRET_KEY not set - using an insecure dev secret. Set one in .env for real use."
  $env:IH_SECRET_KEY = "dev-only-insecure-change-me-0000000000000000"
}

$py = "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "[run] backend venv not found. First-time setup:"
  Write-Host "      python -m venv backend\.venv"
  Write-Host "      backend\.venv\Scripts\python -m pip install -r backend\requirements.txt"
  exit 1
}

Write-Host "[run] backend  -> http://localhost:8010"
Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--port","8010" -WorkingDirectory "backend"

Write-Host "[run] frontend -> http://localhost:5173"
Start-Process -FilePath "npm.cmd" -ArgumentList "run","dev" -WorkingDirectory "frontend"

Write-Host "[run] both starting in separate windows. Open http://localhost:5173"
