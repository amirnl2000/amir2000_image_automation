param(
    [switch]$Clean,
    [ValidateSet("Lite","Full")]
    [string]$BuildProfile = "Lite"
)


$ErrorActionPreference = "Stop"

# IMPORTANT: do not let native stderr become terminating errors
# PyInstaller often prints INFO to stderr on Windows
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $global:PSNativeCommandUseErrorActionPreference = $false
}

function Get-FirstExistingPath {
    param([string[]]$Candidates)
    foreach ($p in $Candidates) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

# Project root is parent of helpers
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null

$LogPath = Join-Path $logDir "build_multiset.log"
$OutLog  = Join-Path $logDir "build_multiset.out.log"
$ErrLog  = Join-Path $logDir "build_multiset.err.log"


# Pick venv python
$py = Get-FirstExistingPath @(
    (Join-Path $root ".venv313\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
)

if (-not $py) { throw "Python venv not found. Looked for .venv313 and .venv under: $root" }

$entry = Join-Path $root "main_set.py"
if (-not (Test-Path -LiteralPath $entry)) { throw "Entry script not found: $entry" }

# Icon
$IconPath = Get-FirstExistingPath @(
    (Join-Path $root "amir2000_image_automation.ico"),
    "YOUR_PATH_HERE"
)
if (-not $IconPath) { throw "Icon not found in project root or fixed path." }

# Output locations
$buildDir = Join-Path $root "build"
$distDir  = Join-Path $root "dist"

if ($Clean) {
    Write-Host "[INFO] Cleaning build artifacts..."
    Remove-Item -Force -ErrorAction SilentlyContinue $LogPath, $OutLog, $ErrLog
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $buildDir
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $distDir
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $root "Amir2000ImageAutomation-MultiSet.spec")
}

Write-Host "[INFO] Ensuring PyInstaller exists..."
& $py -m pip install -q pyinstaller | Out-Null

# Keep EXE lean by default (matches your old stable approach)
$excludes = @(
    "torch","torchvision","pyiqa","clip","cv2",
    "matplotlib","pandas","scipy","dask",
    "tensorflow","keras","tf_keras","tensorboard","tensorflow_probability",
    "jax","jaxlib","tflite_runtime","flax","optax",
    "pytest","_pytest","pluggy","py",
    "pip","setuptools","wheel",
    "IPython","jupyter","notebook","traitlets",
    "PyQt5","PyQt6","PySide2","PySide6","gi",
    "pyarrow","numba","llvmlite",
    "bitsandbytes","onnx","onnxruntime"
)

# Base args
$piArgs = @(
    "-m","PyInstaller",
    "--name","Amir2000ImageAutomation-MultiSet",
    "--noconfirm",
    "--clean",
    "--onefile",                # matches your old -F
    "--icon",$IconPath,
    "--workpath",$buildDir,
    "--specpath",$root,
    "--distpath",$distDir,

    # mysql connector (only if you need it inside the EXE stages)
    "--collect-submodules","mysql.connector",
    "--collect-data","mysql.connector",
    "--hidden-import","mysql.connector",

    # Keep tqdm minimal; collect-all pulls optional stacks (pandas/scipy/matplotlib)
    # and can crash PyInstaller on large onefile builds.
    "--hidden-import","tqdm",
    "--hidden-import","tqdm.auto",
    "--collect-submodules","mysql.connector.plugins",
    "--hidden-import","mysql.connector.plugins.mysql_native_password",
    "--hidden-import","mysql.connector.plugins.caching_sha2_password",
    "--hidden-import","mysql.connector.plugins.sha256_password"


    "--hidden-import","ftfy",
    "--hidden-import","regex",
    "--hidden-import","piexif",
    "--collect-all","piexif",

    # Pillow for runpy scripts
    "--hidden-import","PIL.Image",
    "--hidden-import","PIL.ImageDraw",
    "--hidden-import","PIL.ImageFont",
    "--hidden-import","PIL.ImageTk",
    "--hidden-import","PIL.ImageOps",
    "--hidden-import","PIL.ImageEnhance",

    # Spellchecker resources
    "--hidden-import","spellchecker",
    "--collect-data","spellchecker"
)

# Add your app scripts and folders (same style as your old build)
$addData = @(
    "batch_image_quality_score.py;.",
    "caption_review_local.py;.",
    "review_editor.py;.",
    "db_uploader.py;.",
    "amir2000_config.py;.",
    "simple_inference.py;.",
    "utils;utils",
    "vendor;vendor",
    "fonts;fonts",
    "sac+logos+ava1-l14-linearMSE.pth;.",
    "data;data"
)

foreach ($d in $addData) {
    $src = ($d.Split(";")[0])
    $srcPath = Join-Path $root $src
    if (Test-Path -LiteralPath $srcPath) {
        $piArgs += @("--add-data", $d)
    }
}

# Full profile is optional and NOT recommended right now while NTFS/WOF is crashing
if ($BuildProfile -eq "Full") {
    Write-Host "[WARN] Full profile requested. This will bundle heavy deps and is NOT recommended right now."
    $piArgs += @("--collect-all","requests")
    $piArgs += @("--collect-all","numpy")
    $piArgs += @("--hidden-import","tqdm")
    $piArgs += @("--hidden-import","tqdm.auto")
}

foreach ($m in $excludes) {
    $piArgs += @("--exclude-module", $m)
}

# IMPORTANT: scriptname must be LAST, otherwise you get "scriptname required"
$piArgs += @($entry)

"Build started: $(Get-Date -Format s)" | Set-Content -Path $LogPath -Encoding UTF8
"Build started: $(Get-Date -Format s)" | Set-Content -Path $OutLog  -Encoding UTF8
"Build started: $(Get-Date -Format s)" | Set-Content -Path $ErrLog  -Encoding UTF8

Write-Host "Build started: $(Get-Date -Format s)"
Write-Host "Python: $py"
Write-Host "Profile: $BuildProfile"
Write-Host "OUT log: $OutLog"
Write-Host "ERR log: $ErrLog"
Write-Host ""

$proc = Start-Process -FilePath $py -ArgumentList $piArgs -WorkingDirectory $root -NoNewWindow -PassThru `
    -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog

Write-Host "PyInstaller PID: $($proc.Id)"
Write-Host ""

$fsOut = [System.IO.File]::Open($OutLog, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
$fsErr = [System.IO.File]::Open($ErrLog, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
$srOut = New-Object System.IO.StreamReader($fsOut)
$srErr = New-Object System.IO.StreamReader($fsErr)

$null = $srOut.BaseStream.Seek(0, [System.IO.SeekOrigin]::Begin)
$null = $srErr.BaseStream.Seek(0, [System.IO.SeekOrigin]::Begin)

while (-not $proc.HasExited) {
    while (-not $srOut.EndOfStream) { Write-Host $srOut.ReadLine() }
    while (-not $srErr.EndOfStream) { Write-Host $srErr.ReadLine() }

    try {
        $p = Get-Process -Id $proc.Id -ErrorAction Stop
        $cpu = if ($null -eq $p.CPU) { 0 } else { $p.CPU }
        $ws  = [math]::Round($p.WorkingSet64 / 1MB)
        Write-Host ("[build heartbeat] cpu={0:n1}s ws={1:n0}MB" -f $cpu, $ws)
    } catch {
        Write-Host "[build heartbeat] process still running..."
    }

    Start-Sleep -Seconds 2
    $proc.Refresh()
}

$proc.WaitForExit()

while (-not $srOut.EndOfStream) { Write-Host $srOut.ReadLine() }
while (-not $srErr.EndOfStream) { Write-Host $srErr.ReadLine() }

$srOut.Close(); $srErr.Close()
$fsOut.Close(); $fsErr.Close()

$code = $proc.ExitCode
Get-Content $OutLog, $ErrLog | Set-Content -Path $LogPath -Encoding UTF8

$exe = Join-Path $distDir "Amir2000ImageAutomation-MultiSet.exe"
if (Test-Path -LiteralPath $exe) {
    Write-Host ""
    Write-Host "Build finished. EXE: $exe"
    Write-Host "Log: $LogPath"
    # Ensure amir2000_config.py is next to the EXE (so db_uploader can find it)
    $configSrc = Join-Path $root "amir2000_config.py"
    if (Test-Path -LiteralPath $configSrc) {
        Copy-Item -Force $configSrc (Join-Path $distDir "amir2000_config.py")
    }

    exit 0
}

throw "PyInstaller failed (no EXE created). Exit code: $code. See log: $LogPath"

