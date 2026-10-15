param(
    [ValidateSet('sqlite','postgresql')][string]$Database = 'postgresql',
    [int]$Port = 8001,
    [string]$Schema = 'fraudlens_pilot',
    [string]$SqlitePath,
    [switch]$NoWarmup,
    [switch]$NoWorker,
    [switch]$WorkerOnly
)
$ErrorActionPreference = 'Stop'
if ($NoWorker -and $WorkerOnly) { throw 'Choose API without worker, or worker-only mode.' }
$backendRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $backendRoot
$pilotDirectory = Join-Path $backendRoot 'outputs\pilot_validation'
$ledgerPath = Join-Path $pilotDirectory 'live_calls.json'
if (-not (Test-Path -LiteralPath $ledgerPath)) {
    throw 'The existing live-call ledger is missing. Restore it; do not create a new allowance.'
}
$env:FRAUDLENS_SQLITE_ROLLBACK = Join-Path $pilotDirectory 'demo.db'
if (-not (Test-Path -LiteralPath $env:FRAUDLENS_SQLITE_ROLLBACK)) {
    throw 'The preserved SQLite demo is missing. Restore a copy before starting.'
}
if ($SqlitePath -and $Database -ne 'sqlite') { throw 'SqlitePath requires -Database sqlite.' }
if ($SqlitePath) {
    $resolvedSqlite = (Resolve-Path -LiteralPath $SqlitePath).Path
    if (-not (Test-Path -LiteralPath $resolvedSqlite -PathType Leaf)) { throw 'Use an existing isolated SQLite copy.' }
}
$env:FRAUDLENS_DB = if ($Database -eq 'postgresql') { 'postgresql' } elseif ($SqlitePath) { $resolvedSqlite } else { $env:FRAUDLENS_SQLITE_ROLLBACK }
$env:FRAUDLENS_PG_SCHEMA = $Schema
$env:FRAUDLENS_UPLOAD_DIR = Join-Path $pilotDirectory 'uploads'
$env:FRAUDLENS_THUMB_DIR = Join-Path $pilotDirectory 'thumbnails'
if ($SqlitePath) {
    $isolatedDirectory = Split-Path -Parent $resolvedSqlite
    $env:FRAUDLENS_UPLOAD_DIR = Join-Path $isolatedDirectory 'uploads'
    $env:FRAUDLENS_THUMB_DIR = Join-Path $isolatedDirectory 'thumbnails'
}
$env:FRAUDLENS_LIVE_LEDGER = $ledgerPath
$env:FRAUDLENS_LIVE_LIMIT = '15'
$env:FRAUDLENS_GEMINI_REQUEST_PROFILE = 'gemini3_defaults_v2'
$env:GEMINI_QUOTA_BUDGET = Join-Path $pilotDirectory 'quota_budget.json'
$env:GEMINI_QUOTA_CONSUMER = 'pilot'
# PostgreSQL defaults to the qualified dedicated-worker setup; SQLite retains
# its original in-process option. WorkerOnly runs the same pipeline separately.
$env:FRAUDLENS_WORKER_ENABLED = if ($NoWorker -or ($Database -eq 'postgresql' -and -not $WorkerOnly)) { '0' } else { '1' }
$env:FRAUDLENS_WARM_MODELS = if ($NoWarmup) { '0' } else { '1' }
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:CORS_ORIGINS = 'http://127.0.0.1:5173,http://localhost:5173'
# Windows PowerShell 5 turns native stderr (including uvicorn INFO) into error
# records. Check native exit codes explicitly instead of terminating on logs.
$ErrorActionPreference = 'Continue'
& .\venv\Scripts\python.exe -X utf8 scripts/pilot_preflight.py
if ($LASTEXITCODE -ne 0) { throw 'Pilot preflight failed; no server started.' }
if ($WorkerOnly) {
    & .\venv\Scripts\python.exe -u -X utf8 scripts/run_worker.py 2>&1 | ForEach-Object { $_.ToString() }
    exit $LASTEXITCODE
}
& .\venv\Scripts\python.exe -X utf8 -m uvicorn src.api:app --host 127.0.0.1 --port $Port 2>&1 | ForEach-Object { $_.ToString() }
exit $LASTEXITCODE
