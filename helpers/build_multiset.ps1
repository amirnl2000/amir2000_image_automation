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
    (Join-Path $root ".venv_cuda\Scripts\python.exe"),
    (Join-Path $root ".venv\Scripts\python.exe")
)

if (-not $py) { throw "Python venv not found. Looked for .venv_cuda, .venv313 and .venv under: $root" }

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
& $py -m pip install -q "pyinstaller==6.18.0" | Out-Null

# Keep EXE lean by default (matches your old stable approach)
$excludes = @(
    "torch","torchvision","transformers","huggingface_hub","tokenizers","safetensors",
    "pyiqa","clip","cv2",
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
    "--noupx",                  # avoid BEX64/0xc0000005 crashes seen with compressed EXEs
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
    "--hidden-import","tqdm.contrib",
    "--hidden-import","tqdm.contrib.concurrent",
    "--collect-submodules","mysql.connector.plugins",
    "--hidden-import","mysql.connector.plugins.mysql_native_password",
    "--hidden-import","mysql.connector.plugins.caching_sha2_password",
    "--hidden-import","mysql.connector.plugins.sha256_password",


    "--hidden-import","ftfy",
    "--hidden-import","regex",
    "--hidden-import","piexif",
    "--collect-all","piexif",
    # caption_review_local.py is shipped as external data and run via external
    # Python in Stage 6. Do not hidden-import it in the EXE build, because
    # PyInstaller+Python 3.13 can crash while bytecode-scanning that module.
    "--hidden-import","requests",
    "--hidden-import","http.cookies",
    "--hidden-import","metadata_evidence_pipeline",
    "--hidden-import","scripts.evidence_subject_pipeline",

    # Pillow for runpy scripts
    "--hidden-import","PIL.Image",
    "--hidden-import","PIL.ImageDraw",
    "--hidden-import","PIL.ImageFont",
    "--hidden-import","PIL.ImageTk",
    "--hidden-import","PIL.ImageOps",
    "--hidden-import","PIL.ImageEnhance",
    "--hidden-import","PIL.ImageCms",

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
    "simple_inference.py;.",
    "metadata_evidence_pipeline.py;.",
    "utils;utils",
    "scripts;scripts",
    "helpers;helpers",
    "fonts;fonts",
    "docs;docs",
    "sac+logos+ava1-l14-linearMSE.pth;."
)

foreach ($d in $addData) {
    $src = ($d.Split(";")[0])
    $srcPath = Join-Path $root $src
    if (Test-Path -LiteralPath $srcPath) {
        $piArgs += @("--add-data", $d)
    }
}

$runtimeHook = Join-Path $root "helpers\runtime_hook_samevenv_classifier.py"
if (Test-Path -LiteralPath $runtimeHook) {
    $piArgs += @("--runtime-hook", $runtimeHook)
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

    # AMIR_COPY_NIMA_SCORING_CACHE_TO_DIST_START
    # Keep strict scoring fully offline in the built EXE.
    # PyIQA/torch looks for NIMA here at runtime:
    #   dist\.cache\torch\hub\pyiqa\NIMA_InceptionV2_ava-b0c77c00.pth
    $NimaFileName = "NIMA_InceptionV2_ava-b0c77c00.pth"
    $ProjectRootForNima = $root

    $NimaCandidates = @(
        (Join-Path $ProjectRootForNima ".cache\torch\hub\pyiqa\$NimaFileName"),
        (Join-Path $ProjectRootForNima "data\_runtime_scripts\.cache\torch\hub\pyiqa\$NimaFileName"),
        (Join-Path $ProjectRootForNima "dist\.cache\torch\hub\pyiqa\$NimaFileName")
    )

    $NimaSource = $null

    foreach ($Candidate in $NimaCandidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $NimaSource = $Candidate
            break
        }
    }

    if ($NimaSource) {
        $NimaDistTarget = Join-Path $ProjectRootForNima "dist\.cache\torch\hub\pyiqa\$NimaFileName"
        $NimaRuntimeTarget = Join-Path $ProjectRootForNima "data\_runtime_scripts\.cache\torch\hub\pyiqa\$NimaFileName"

        New-Item -ItemType Directory -Force -Path (Split-Path $NimaDistTarget -Parent) | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path $NimaRuntimeTarget -Parent) | Out-Null

        Copy-Item -LiteralPath $NimaSource -Destination $NimaDistTarget -Force
        Copy-Item -LiteralPath $NimaSource -Destination $NimaRuntimeTarget -Force

        Write-Host "[OK] Copied NIMA scoring checkpoint to EXE runtime cache."
    } else {
        Write-Host "[WARN] NIMA checkpoint not found locally. Strict scoring may try to download at runtime."
    }
    # AMIR_COPY_NIMA_SCORING_CACHE_TO_DIST_END

    # AMIR_COPY_BRISQUE_SCORING_CACHE_TO_DIST_START
    # PyIQA/torch looks for BRISQUE here at runtime:
    #   dist\.cache\torch\hub\pyiqa\brisque_svm_weights.pth
    # If this file is missing, strict scoring may try to download during a batch.
    $BrisqueFileName = "brisque_svm_weights.pth"

    $BrisqueCandidates = @(
        (Join-Path $ProjectRootForNima ".cache\torch\hub\pyiqa\$BrisqueFileName"),
        (Join-Path $ProjectRootForNima "data\_runtime_scripts\.cache\torch\hub\pyiqa\$BrisqueFileName"),
        (Join-Path $ProjectRootForNima "dist\.cache\torch\hub\pyiqa\$BrisqueFileName")
    )

    $BrisqueSource = $null

    foreach ($Candidate in $BrisqueCandidates) {
        if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
            $BrisqueSource = $Candidate
            break
        }
    }

    if ($BrisqueSource) {
        $BrisqueDistTarget = Join-Path $ProjectRootForNima "dist\.cache\torch\hub\pyiqa\$BrisqueFileName"
        $BrisqueRuntimeTarget = Join-Path $ProjectRootForNima "data\_runtime_scripts\.cache\torch\hub\pyiqa\$BrisqueFileName"

        New-Item -ItemType Directory -Force -Path (Split-Path $BrisqueDistTarget -Parent) | Out-Null
        New-Item -ItemType Directory -Force -Path (Split-Path $BrisqueRuntimeTarget -Parent) | Out-Null

        Copy-Item -LiteralPath $BrisqueSource -Destination $BrisqueDistTarget -Force
        Copy-Item -LiteralPath $BrisqueSource -Destination $BrisqueRuntimeTarget -Force

        Write-Host "[OK] Copied BRISQUE scoring checkpoint to EXE runtime cache."
    } else {
        Write-Host "[WARN] BRISQUE checkpoint not found locally. Strict scoring may try to download at runtime."
    }
    # AMIR_COPY_BRISQUE_SCORING_CACHE_TO_DIST_END

    # AMIR_SIGN_LOCAL_EXE_START
    # Keep rebuilt EXEs trusted on this machine. Device Guard/Smart App Control
    # treats each clean rebuild as a new unsigned binary unless it is signed.
    try {
        $certSubject = "CN=Amir2000 Local Code Signing"
        $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
            Where-Object { $_.Subject -eq $certSubject -and $_.HasPrivateKey } |
            Sort-Object NotAfter -Descending |
            Select-Object -First 1

        if (-not $cert) {
            $cert = New-SelfSignedCertificate `
                -Type CodeSigningCert `
                -Subject $certSubject `
                -KeyUsage DigitalSignature `
                -KeyAlgorithm RSA `
                -KeyLength 3072 `
                -HashAlgorithm SHA256 `
                -CertStoreLocation Cert:\CurrentUser\My `
                -NotAfter (Get-Date).AddYears(5)
        }

        $certExportPath = Join-Path $root "data\amir2000_local_code_signing.cer"
        New-Item -ItemType Directory -Force -Path (Split-Path $certExportPath -Parent) | Out-Null
        Export-Certificate -Cert $cert -FilePath $certExportPath -Force | Out-Null
        Import-Certificate -FilePath $certExportPath -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
        Import-Certificate -FilePath $certExportPath -CertStoreLocation Cert:\CurrentUser\TrustedPublisher | Out-Null

        $signature = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256

        if ($signature.Status -eq "Valid") {
            Write-Host "[OK] Signed EXE with local trusted certificate: $($cert.Thumbprint)"
        } else {
            Write-Host "[WARN] EXE signing status: $($signature.Status) - $($signature.StatusMessage)"
        }
    } catch {
        Write-Host "[WARN] EXE signing failed: $($_.Exception.Message)"
    }
    # AMIR_SIGN_LOCAL_EXE_END

    exit 0
}

throw "PyInstaller failed (no EXE created). Exit code: $code. See log: $LogPath"
