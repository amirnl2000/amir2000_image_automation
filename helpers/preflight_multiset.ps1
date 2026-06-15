param(
    [ValidateSet("Lite","Full")]
    [string]$BuildProfile = "Lite"
)


$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$scriptDir = $PSScriptRoot
$root = $scriptDir
if ((Split-Path -Leaf $scriptDir) -ieq "helpers") {
    $root = Split-Path -Parent $scriptDir
}

function Get-FirstExistingPath {
    param([string[]]$Candidates)
    foreach ($p in $Candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

$venvPy = Get-FirstExistingPath @(
    (Join-Path $root ".venv313\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
)

if (-not $venvPy) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $pyLauncher) { throw "Python launcher 'py' not found. Install Python 3.13 and ensure 'py' works." }

    Write-Host "[INFO] No venv found. Creating .venv313 with Python 3.13..."
    Write-Progress -Activity "Preflight" -Status "Create venv .venv313 (Python 3.13)" -PercentComplete 8
    & py -3.13 -m venv (Join-Path $root ".venv313")

    $venvPy = Join-Path $root ".venv313\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPy)) { throw "Failed to create .venv313. Expected: $venvPy" }
}


$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$report = Join-Path $root "helpers\preflight_report_$stamp.txt"

$checks = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param([string]$Name, [string]$Status, [string]$Detail)
    $checks.Add([pscustomobject]@{ Name=$Name; Status=$Status; Detail=$Detail })
}

function Test-File {
    param([string]$Label, [string]$Path)
    if (Test-Path -LiteralPath $Path) { Add-Result $Label "OK" $Path }
    else { Add-Result $Label "FAIL" $Path }
}

function Test-Import {
    param([string]$Label, [string]$ImportStmt, [string]$PipName)
    $cmd = "import $ImportStmt"
    & $venvPy -c $cmd *> $null
    if ($LASTEXITCODE -eq 0) {
        Add-Result "import $Label" "OK" $ImportStmt
        return $true
    } else {
        Add-Result "import $Label" "FAIL" ("missing, pip install {0}" -f $PipName)
        return $false
    }
}

Write-Progress -Activity "Preflight" -Status "Paths and core files" -PercentComplete 10

Test-File "venv python" $venvPy
if (-not (Test-Path -LiteralPath $venvPy)) {
    $checks | Format-Table -AutoSize | Out-String | Set-Content -LiteralPath $report -Encoding UTF8
    Write-Host "[FAIL] venv python not found. Report: $report"
    exit 1
}

Write-Progress -Activity "Preflight" -Status "Upgrade pip" -PercentComplete 12
& $venvPy -m pip install -U pip | Out-Null

Write-Progress -Activity "Preflight" -Status "Install base runtime deps" -PercentComplete 16
& $venvPy -m pip install -U pyinstaller pillow pyspellchecker piexif mysql-connector-python requests packaging "setuptools<82" | Out-Null

Write-Progress -Activity "Preflight" -Status "Install AI/runtime deps" -PercentComplete 22
& $venvPy -m pip install -U numpy tqdm opencv-python pyiqa huggingface_hub transformers | Out-Null

Write-Progress -Activity "Preflight" -Status "Install OpenAI CLIP scorer" -PercentComplete 28
& $venvPy -m pip show clip *> $null
if ($LASTEXITCODE -eq 0) {
    & $venvPy -m pip uninstall -y clip | Out-Null
}
& $venvPy -m pip install -U "git+https://github.com/openai/CLIP.git" | Out-Null

# Torch install (Full always, Lite tries but does not fail the whole preflight if it errors)
$useCuda = $false
Write-Progress -Activity "Preflight" -Status "Detect NVIDIA GPU (nvidia-smi)" -PercentComplete 32
$nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvsmi) {
    try {
        & $nvsmi.Source | Out-Null
        if ($LASTEXITCODE -eq 0) { $useCuda = $true }
    } catch {
        $useCuda = $false
    }
}

try {
    if ($useCuda) {
        Write-Host "[INFO] NVIDIA detected. Installing Torch CUDA wheels (cu128)."
        Write-Progress -Activity "Preflight" -Status "Install torch + torchvision (CUDA cu128)" -PercentComplete 38
        & $venvPy -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cu128 | Out-Null
    } else {
        Write-Host "[INFO] No working NVIDIA detected. Installing Torch CPU wheels."
        Write-Progress -Activity "Preflight" -Status "Install torch + torchvision (CPU)" -PercentComplete 38
        & $venvPy -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cpu | Out-Null
    }
} catch {
    if ($BuildProfile -eq "Full") { throw }
    Write-Host "[WARN] Torch install failed in Lite profile. Scoring may not work until Torch is installed."
}

Test-File "entry main_set.py" (Join-Path $root "main_set.py")
Test-File "icon ico" (Join-Path $root "amir2000_image_automation.ico")
Test-File "config amir2000_config.py" (Join-Path $root "amir2000_config.py")

Write-Progress -Activity "Preflight" -Status "Internal scripts and assets" -PercentComplete 30

$mustFiles = @(
    (Join-Path $root "review_editor.py"),
    (Join-Path $root "db_uploader.py"),
    (Join-Path $root "batch_image_quality_score.py")
)

$niceToHaveFiles = @(
    (Join-Path $root "caption_review_local.py"),
    (Join-Path $root "simple_inference.py"),
    (Join-Path $root "sac+logos+ava1-l14-linearMSE.pth")
)

foreach ($p in $mustFiles) { Test-File ("file " + (Split-Path -Leaf $p)) $p }
foreach ($p in $niceToHaveFiles) {
    if (Test-Path -LiteralPath $p) { Add-Result ("file " + (Split-Path -Leaf $p)) "OK" $p }
    else { Add-Result ("file " + (Split-Path -Leaf $p)) "WARN" $p }
}

Test-File "folder fonts" (Join-Path $root "fonts")
Test-File "folder utils" (Join-Path $root "utils")
Test-File "folder vendor" (Join-Path $root "vendor")

$font = Join-Path $root "fonts\Montserrat-Light.ttf"
if (Test-Path -LiteralPath $font) { Add-Result "font Montserrat-Light.ttf" "OK" $font }
else { Add-Result "font Montserrat-Light.ttf" "WARN" $font }

Write-Progress -Activity "Preflight" -Status "Python version" -PercentComplete 45

$pyver = & $venvPy --version 2>&1
Add-Result "python --version" "OK" $pyver

if ($pyver -notmatch "Python 3\.13") {
    Add-Result "python version gate" "WARN" "Expected Python 3.13.x for your workflow"
} else {
    Add-Result "python version gate" "OK" "3.13 detected"
}

Write-Progress -Activity "Preflight" -Status "Imports (core)" -PercentComplete 60

Test-Import "PyInstaller" "PyInstaller" "pyinstaller" | Out-Null
Test-Import "Pillow" "PIL" "pillow" | Out-Null
Test-Import "pyspellchecker" "spellchecker" "pyspellchecker" | Out-Null
Test-Import "piexif" "piexif" "piexif" | Out-Null
Test-Import "mysql connector" "mysql.connector" "mysql-connector-python" | Out-Null
Test-Import "requests" "requests" "requests" | Out-Null
Test-Import "packaging" "packaging" "packaging" | Out-Null
Test-Import "huggingface_hub" "huggingface_hub" "huggingface_hub" | Out-Null
Test-Import "transformers" "transformers" "transformers" | Out-Null
Test-Import "OpenAI CLIP" "clip" "git+https://github.com/openai/CLIP.git" | Out-Null

Write-Progress -Activity "Preflight" -Status "Imports (scoring stack)" -PercentComplete 80

$scoringNeeded = @(
    @{ label="numpy";  imp="numpy"; pip="numpy" },
    @{ label="tqdm";   imp="tqdm"; pip="tqdm" },
    @{ label="opencv"; imp="cv2";  pip="opencv-python" },
    @{ label="pyiqa";  imp="pyiqa"; pip="pyiqa" },
    @{ label="torch";  imp="torch"; pip="torch" },
    @{ label="torchvision"; imp="torchvision"; pip="torchvision" }
)

foreach ($m in $scoringNeeded) {
    $ok = Test-Import $m.label $m.imp $m.pip
    if ($BuildProfile -eq "Lite" -and -not $ok) {
        # downgrade to WARN for Lite
        $checks[$checks.Count-1].Status = "WARN"
    }
}

Write-Progress -Activity "Preflight" -Status "Builder sanity check" -PercentComplete 92

$builder = Join-Path $root "helpers\build_multiset.ps1"
if (Test-Path -LiteralPath $builder) {
    $txt = Get-Content -LiteralPath $builder -Raw
    $hasDist = ($txt -match "--distpath") -and ($txt -match "--workpath") -and ($txt -match "--specpath")
    if ($hasDist) { Add-Result "builder dist and build paths" "OK" "distpath workpath specpath present" }
    else { Add-Result "builder dist and build paths" "FAIL" "Missing distpath or workpath or specpath, build will land in helpers" }
} else {
    Add-Result "builder build_multiset.ps1" "WARN" $builder
}

Write-Progress -Activity "Preflight" -Status "Report" -PercentComplete 100

$checks | Sort-Object Status, Name | Format-Table -AutoSize | Out-String | Set-Content -LiteralPath $report -Encoding UTF8

$fail = @($checks | Where-Object { $_.Status -eq "FAIL" })
$warn = @($checks | Where-Object { $_.Status -eq "WARN" })


Write-Host ""
Write-Host "Report: $report"
Write-Host ("FAIL: {0}   WARN: {1}   OK: {2}" -f $fail.Count, $warn.Count, (@($checks | Where-Object { $_.Status -eq "OK" }).Count))

if ($fail.Count -gt 0) {
    Write-Host "[FAIL] Fix FAIL items before building."
    exit 1
} else {
    Write-Host "[OK] Preflight passed. You can build now."
}
