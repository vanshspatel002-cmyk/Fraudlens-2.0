param(
    [ValidateSet('Panel','Pilot')][string]$Dataset='Panel',
    [ValidateSet('Api','Worker','Info')][string]$Service='Info'
)
$ErrorActionPreference='Stop'
$backendRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $backendRoot
$schema=if($Dataset -eq 'Panel') {'fraudlens_validation_panel_20261022'} else {'fraudlens_pilot'}
$runtime=if($Dataset -eq 'Panel') {'outputs\final_presentation\rehearsal'} else {'outputs\pilot_validation'}
if(-not (Test-Path -LiteralPath $runtime -PathType Container)) {throw 'Existing dataset evidence directory is missing. No dataset was created.'}
Write-Host "Review dataset: $Dataset | PostgreSQL schema: $schema"
Write-Host 'Customer http://127.0.0.1:5173/dashboard | Admin http://127.0.0.1:5173/admin'
Write-Host 'Existing private filesystem evidence and database PDF persistence; no Supabase Storage migration.'
if($Service -eq 'Info') {return}
if($Service -eq 'Worker') {
    $listener=Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction Stop
    $ErrorActionPreference='Continue'
    & .\venv\Scripts\python.exe scripts/verify_review_configuration.py --api-process-id $listener.OwningProcess --schema $schema --start-worker 2>&1 | ForEach-Object { $_.ToString() }
    if($LASTEXITCODE -ne 0) {throw 'API dataset/configuration does not match. Worker not started.'}
} else {
    & .\scripts\start_pilot.ps1 -Database postgresql -Schema $schema -RuntimeDirectory $runtime -Port 8001 -NoWorker
}
