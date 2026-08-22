$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
  python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if (-not $env:REDFOX_API_KEY) {
  Write-Error "请先设置 REDFOX_API_KEY"
}
& ".venv\Scripts\python.exe" -m uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
