<# 
copy_pack.ps1

Goal
Create a minimal, runnable backup pack of the Amir2000 image automation workflow.

Default behavior
- BackupRoot: YOUR_PATH_HERE
- Timestamped: ON (so every run creates a new folder)
- Excludes: build, dist, test/tests, *.spec, __pycache__, .git, .venv*, logs, runtime caches
- Uses a curated file list for helpers so old reports/backups are not copied

Run
  Set-Location "YOUR_PATH_HERE"
  Unblock-File -LiteralPath ".\copy_pack.ps1" -ErrorAction SilentlyContinue
  .\copy_pack.ps1
#>

[CmdletBinding()]
param(
  [string]$SrcRoot = "",

  [Alias("PackRoot")]
  [string]$BackupRoot = "YOUR_PATH_HERE",

  [switch]$Timestamped,
  [switch]$DryRun = $false,
  [switch]$Prune = $false,
  [switch]$NoScoring = $false,
  [switch]$Open = $false
)
if (-not $PSBoundParameters.ContainsKey("Timestamped")) { $Timestamped = $true }

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-SrcRoot {
  param([string]$Given)

  if ($Given -and $Given.Trim() -ne "") {
    return (Resolve-Path -LiteralPath $Given).Path
  }

  $here = $PSScriptRoot
  if ((Split-Path -Leaf $here).ToLowerInvariant() -eq "helpers") {
    return (Resolve-Path -LiteralPath (Split-Path -Parent $here)).Path
  }

  return (Resolve-Path -LiteralPath $here).Path
}

function New-Dir([string]$Path) {
  if ($DryRun) {
    Write-Host "[DRYRUN] Ensure dir: $Path"
    return
  }
  if (-not (Test-Path -LiteralPath $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

function Copy-RequiredFile([string]$From, [string]$To) {
  if (-not (Test-Path -LiteralPath $From)) {
    throw "Required file missing: $From"
  }
  if ($DryRun) {
    Write-Host "[DRYRUN] Copy: $From -> $To"
    return
  }
  New-Dir (Split-Path -Parent $To)
  Copy-Item -LiteralPath $From -Destination $To -Force
  Write-Host "[OK] Copied: $($To)"
}

function Copy-OptionalFile([string]$From, [string]$To) {
  if (-not (Test-Path -LiteralPath $From)) {
    Write-Host "[INFO] Optional missing: $From"
    return
  }
  if ($DryRun) {
    Write-Host "[DRYRUN] Copy optional: $From -> $To"
    return
  }
  New-Dir (Split-Path -Parent $To)
  Copy-Item -LiteralPath $From -Destination $To -Force
  Write-Host "[OK] Copied optional: $($To)"
}

function Invoke-RoboCopyDir {
  param(
    [string]$From,
    [string]$To,
    [switch]$Mirror
  )

  if (-not (Test-Path -LiteralPath $From)) {
    throw "Required directory missing: $From"
  }

  if ($DryRun) {
    $mode = $(if ($Mirror) { "MIRROR" } else { "COPY" })
    Write-Host "[DRYRUN] Robocopy ($mode): $From -> $To"
    return
  }

  New-Dir $To

  $rcArgs = @(
    $From,
    $To,
    "*.*",
    $(if ($Mirror) { "/MIR" } else { "/E" }),
    "/R:1",
    "/W:1",
    "/NP",
    "/NFL",
    "/NDL",
    "/XD",
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".venv",
    ".venv313",
    ".venv_cuda",
    ".venv_florence",
    "build",
    "dist",
    "test",
    "tests",
    "experimental",
    "experiments",
    "_archive_",
    "logs",
    "ollama_tmp",
    "hf_cache"
  )

  & robocopy @rcArgs | Out-Null
  $rc = $LASTEXITCODE

  if ($rc -ge 8) {
    throw "Robocopy failed (exit code $rc): $From -> $To"
  }

  Write-Host "[OK] Copied dir: $From -> $To"
}

$SrcRoot = Resolve-SrcRoot -Given $SrcRoot

$packPrefix = "amir2000_workflow_pack"
$stamp = (Get-Date -Format "yyyyMMdd_HHmm")
$packName = $(if ($Timestamped) { "$packPrefix`_$stamp" } else { $packPrefix })
$DstRoot = Join-Path $BackupRoot $packName

New-Dir $BackupRoot
New-Dir $DstRoot

$MirrorMode = $Prune
$DoScoring = -not $NoScoring

Write-Host ""
Write-Host "== BUILD BACKUP PACK =="
Write-Host "Source:      $SrcRoot"
Write-Host "Destination: $DstRoot"
Write-Host "Timestamped: $Timestamped"
Write-Host "Prune:       $Prune"
Write-Host "Scoring:     $DoScoring"
Write-Host "DryRun:      $DryRun"
Write-Host ""

$coreRequired = @(
  "main_set.py",
  "review_editor.py",
  "db_uploader.py",
  "caption_review_local.py",
  "batch_image_quality_score.py",
  "simple_inference.py",
  "amir2000_config.py",
  "amir2000_image_automation.ico"
)

$coreOptional = @(
  "README.md",
  "init_db.py"
)

$helpersRequired = @(
  "helpers\copy_pack.ps1",
  "helpers\build_multiset.ps1",
  "helpers\preflight_multiset.ps1",
  "helpers\setup_venv313_full.ps1"
)

$helpersOptional = @()

$dirsRequired = @(
  "utils",
  "fonts",
  "docs\init"
)

$dataRequired = @(
  "data\review.db",
  "data\photos_info_revamp.db",
  "data\folder_map.json",
  "data\location_list.json",
  "data\used_filenames.json",
  "data\autofix_dict.json"
)

$dataOptional = @(
  "data\spellcheck_exceptions.json",
  "data\ui_state.json",
  "data\new_taxonomy_log.json",
  "data\run_log.txt",
  "data\init\review_queue.sql",
  "data\init\photos_info_revamp.sql"
)

$step = 0
$totalSteps = 7

$step++
Write-Progress -Activity "Backup pack" -Status "Copy core scripts" -PercentComplete (($step / $totalSteps) * 100)

for ($i = 0; $i -lt $coreRequired.Count; $i++) {
  $rel = $coreRequired[$i]
  Write-Progress -Activity "Backup pack" -Status "Core: $rel" -PercentComplete ((($i + 1) / $coreRequired.Count) * 100)
  Copy-RequiredFile -From (Join-Path $SrcRoot $rel) -To (Join-Path $DstRoot $rel)
}

foreach ($rel in $coreOptional) {
  Copy-OptionalFile -From (Join-Path $SrcRoot $rel) -To (Join-Path $DstRoot $rel)
}

$step++
Write-Progress -Activity "Backup pack" -Status "Copy helper scripts (curated)" -PercentComplete (($step / $totalSteps) * 100)

foreach ($rel in $helpersRequired) {
  Copy-RequiredFile -From (Join-Path $SrcRoot $rel) -To (Join-Path $DstRoot $rel)
}

foreach ($rel in $helpersOptional) {
  Copy-OptionalFile -From (Join-Path $SrcRoot $rel) -To (Join-Path $DstRoot $rel)
}

$step++
Write-Progress -Activity "Backup pack" -Status "Copy required folders" -PercentComplete (($step / $totalSteps) * 100)

foreach ($d in $dirsRequired) {
  Invoke-RoboCopyDir -From (Join-Path $SrcRoot $d) -To (Join-Path $DstRoot $d) -Mirror:$MirrorMode
}

$step++
Write-Progress -Activity "Backup pack" -Status "Copy required data" -PercentComplete (($step / $totalSteps) * 100)

foreach ($rel in $dataRequired) {
  Copy-RequiredFile -From (Join-Path $SrcRoot $rel) -To (Join-Path $DstRoot $rel)
}

$step++
Write-Progress -Activity "Backup pack" -Status "Copy optional data" -PercentComplete (($step / $totalSteps) * 100)

foreach ($rel in $dataOptional) {
  Copy-OptionalFile -From (Join-Path $SrcRoot $rel) -To (Join-Path $DstRoot $rel)
}

$step++
Write-Progress -Activity "Backup pack" -Status "Copy scoring assets" -PercentComplete (($step / $totalSteps) * 100)

if ($DoScoring) {
  Invoke-RoboCopyDir -From (Join-Path $SrcRoot "vendor\brisque") -To (Join-Path $DstRoot "vendor\brisque") -Mirror:$MirrorMode
  Invoke-RoboCopyDir -From (Join-Path $SrcRoot "vendor\clip") -To (Join-Path $DstRoot "vendor\clip") -Mirror:$MirrorMode
  Copy-OptionalFile -From (Join-Path $SrcRoot "sac+logos+ava1-l14-linearMSE.pth") -To (Join-Path $DstRoot "sac+logos+ava1-l14-linearMSE.pth")
}

$step++
Write-Progress -Activity "Backup pack" -Status "Write manifest and verify" -PercentComplete (($step / $totalSteps) * 100)

$manifest = Join-Path $DstRoot "PACK_MANIFEST.txt"
if ($DryRun) {
  Write-Progress -Activity "Backup pack" -Completed
  Write-Host ""
  Write-Host "== DRY RUN DONE =="
  Write-Host "Dry run validated copy plan."
  Write-Host "Target pack: $DstRoot"
  return
}

if (-not $DryRun) {
  "Pack built: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File -FilePath $manifest -Encoding UTF8
  "Source: $SrcRoot" | Out-File -FilePath $manifest -Append -Encoding UTF8
  "Destination: $DstRoot" | Out-File -FilePath $manifest -Append -Encoding UTF8
  "Scoring: $DoScoring" | Out-File -FilePath $manifest -Append -Encoding UTF8
  "Prune: $Prune" | Out-File -FilePath $manifest -Append -Encoding UTF8
  "" | Out-File -FilePath $manifest -Append -Encoding UTF8
  "== FILE TREE ==" | Out-File -FilePath $manifest -Append -Encoding UTF8

  Get-ChildItem -LiteralPath $DstRoot -Recurse -File |
    Select-Object FullName |
    ForEach-Object { $_.FullName.Replace($DstRoot, ".") } |
    Out-File -FilePath $manifest -Append -Encoding UTF8
}

$missing = New-Object System.Collections.Generic.List[string]
foreach ($rel in $coreRequired) {
  if (-not (Test-Path -LiteralPath (Join-Path $DstRoot $rel))) { $missing.Add($rel) | Out-Null }
}
foreach ($rel in $helpersRequired) {
  if (-not (Test-Path -LiteralPath (Join-Path $DstRoot $rel))) { $missing.Add($rel) | Out-Null }
}
foreach ($rel in $dirsRequired) {
  if (-not (Test-Path -LiteralPath (Join-Path $DstRoot $rel))) { $missing.Add("$rel (dir)") | Out-Null }
}
foreach ($rel in $dataRequired) {
  if (-not (Test-Path -LiteralPath (Join-Path $DstRoot $rel))) { $missing.Add($rel) | Out-Null }
}

$forbiddenPaths = @(
  "build",
  "dist",
  "test",
  "tests",
  "Amir2000ImageAutomation-MultiSet.spec",
  "helpers\sanitize_for_github.ps1"
)

$forbidden = New-Object System.Collections.Generic.List[string]
foreach ($rel in $forbiddenPaths) {
  if (Test-Path -LiteralPath (Join-Path $DstRoot $rel)) {
    $forbidden.Add($rel) | Out-Null
  }
}

$forbiddenSpecs = Get-ChildItem -LiteralPath $DstRoot -Recurse -File -Filter "*.spec" -ErrorAction SilentlyContinue
foreach ($f in $forbiddenSpecs) {
  $forbidden.Add($f.FullName.Replace($DstRoot, ".")) | Out-Null
}

if ($missing.Count -gt 0) {
  Write-Host ""
  Write-Host "Missing items in pack:"
  $missing | ForEach-Object { Write-Host "  $_" }
  throw "Backup pack verification failed"
}

if ($forbidden) {
  Write-Host ""
  Write-Host "Forbidden items found in pack:"
  $forbidden | ForEach-Object { Write-Host "  $_" }
  throw "Pack contains build/test/spec/release artifacts"
}

Write-Progress -Activity "Backup pack" -Completed

Write-Host ""
Write-Host "== DONE =="
Write-Host "Pack: $DstRoot"
Write-Host "Manifest: $manifest"

if ($Open -and -not $DryRun) {
  Start-Process explorer.exe $DstRoot
}

