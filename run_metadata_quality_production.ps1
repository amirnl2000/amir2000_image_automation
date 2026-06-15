$ErrorActionPreference = "Stop"

$ProjectRoot = "YOUR_PATH_HERE"
$PythonExe = Join-Path $ProjectRoot ".venv313\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectRoot "scripts\metadata_quality_production.py"
$DbPath = Join-Path $ProjectRoot "data\review.db"

Write-Host "== Metadata quality production runner =="
Write-Host "Project root: $ProjectRoot"
Write-Host "Review DB:    $DbPath"
Write-Host "Script:       $ScriptPath"
Write-Host ""

if (-not (Test-Path $PythonExe)) {
    throw "Python not found: $PythonExe"
}

if (-not (Test-Path $ScriptPath)) {
    throw "Script not found: $ScriptPath"
}

if (-not (Test-Path $DbPath)) {
    throw "Review DB not found: $DbPath"
}

& $PythonExe $ScriptPath --db $DbPath

if ($LASTEXITCODE -ne 0) {
    throw "Metadata quality production run failed"
}

Write-Host ""
Write-Host "[DONE] Metadata quality production run complete."

