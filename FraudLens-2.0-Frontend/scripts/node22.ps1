param([ValidateSet('typecheck','build','dev','preview')][string]$Task = 'typecheck')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = if ($env:FRAUDLENS_NODE22_HOME) { $env:FRAUDLENS_NODE22_HOME } else { 'D:\tools\FraudLens-node22\node-v22.23.3-win-x64' }
$node = Join-Path $runtime 'node.exe'
if (-not (Test-Path -LiteralPath $node)) { throw 'Install the official Node 22 archive; set FRAUDLENS_NODE22_HOME to its directory.' }
$expected = (Get-Content -LiteralPath (Join-Path $root '.nvmrc') -Raw).Trim()
$actual = (& $node --version).TrimStart('v')
if ($actual -ne $expected) { throw "Expected Node $expected, got $actual. No global installation was changed." }
$oldPath = $env:PATH
Push-Location -LiteralPath $root
try {
    $env:PATH = $runtime + ';' + $oldPath
    Write-Output "Using Node $actual for $Task"
    # PowerShell 5 treats native warning stderr as errors. Preserve the log
    # and use the actual exit code to decide whether the command passed.
    $ErrorActionPreference = 'Continue'
    if ($Task -eq 'typecheck') { & $node 'node_modules\typescript\bin\tsc' --noEmit 2>&1 | ForEach-Object { $_.ToString() } }
    else { & (Join-Path $runtime 'npm.cmd') run $Task 2>&1 | ForEach-Object { $_.ToString() } }
    if ($LASTEXITCODE -ne 0) { throw "$Task failed with exit code $LASTEXITCODE" }
} finally {
    $env:PATH = $oldPath
    Pop-Location
}
