$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

Set-Location $root

Write-Progress -Activity "Setup venv313" -Status "Remove old .venv313" -PercentComplete 5
if (Test-Path -LiteralPath ".\.venv313") {
    Remove-Item -LiteralPath ".\.venv313" -Recurse -Force
}

Write-Progress -Activity "Setup venv313" -Status "Create venv with Python 3.13" -PercentComplete 15
py -3.13 -m venv .venv313

$py = Join-Path $root ".venv313\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { throw "Failed to create .venv313 at: $py" }

Write-Progress -Activity "Setup venv313" -Status "Upgrade pip" -PercentComplete 25
& $py -m pip install -U pip

Write-Progress -Activity "Setup venv313" -Status "Install base runtime deps" -PercentComplete 35
& $py -m pip install -U pyinstaller pillow pyspellchecker piexif mysql-connector-python requests packaging "setuptools<82"

Write-Progress -Activity "Setup venv313" -Status "Install AI/runtime deps" -PercentComplete 50
& $py -m pip install -U numpy tqdm opencv-python pyiqa huggingface_hub transformers

Write-Progress -Activity "Setup venv313" -Status "Install OpenAI CLIP scorer" -PercentComplete 60
& $py -m pip show clip *> $null
if ($LASTEXITCODE -eq 0) {
    & $py -m pip uninstall -y clip | Out-Null
}
& $py -m pip install -U "git+https://github.com/openai/CLIP.git"

# Torch: auto detect NVIDIA via nvidia-smi. If it works, prefer CUDA wheels.
$useCuda = $false
$nvidiaSmiCandidates = @(
    "nvidia-smi",
    "YOUR_PATH_HERE",
    "YOUR_PATH_HERE Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
)
Write-Progress -Activity "Setup venv313" -Status "Detect NVIDIA GPU (nvidia-smi)" -PercentComplete 70
foreach ($candidate in $nvidiaSmiCandidates) {
    try {
        $resolved = $null
        if (Test-Path -LiteralPath $candidate) {
            $resolved = $candidate
        } else {
            $cmd = Get-Command $candidate -ErrorAction Stop
            $resolved = $cmd.Source
        }
        & $resolved | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $useCuda = $true
            break
        }
    } catch {
        continue
    }
}

if ($useCuda) {
    $cudaIndexes = @(
        @{ Name = "cu128"; Url = "https://download.pytorch.org/whl/cu128" },
        @{ Name = "cu126"; Url = "https://download.pytorch.org/whl/cu126" },
        @{ Name = "cu124"; Url = "https://download.pytorch.org/whl/cu124" },
        @{ Name = "cu121"; Url = "https://download.pytorch.org/whl/cu121" }
    )
    $torchInstalled = $false
    foreach ($cuda in $cudaIndexes) {
        Write-Host "[INFO] NVIDIA detected. Trying Torch CUDA wheels ($($cuda.Name))."
        Write-Progress -Activity "Setup venv313" -Status "Install torch + torchvision ($($cuda.Name))" -PercentComplete 85
        try {
            & $py -m pip install -U torch torchvision --index-url $cuda.Url
            if ($LASTEXITCODE -eq 0) {
                $torchInstalled = $true
                break
            }
        } catch {
            Write-Host "[WARN] Torch install failed for $($cuda.Name). Trying next CUDA index."
        }
    }
    if (-not $torchInstalled) {
        Write-Host "[WARN] CUDA wheels unavailable for this Python/Windows combo. Falling back to CPU wheels."
        Write-Progress -Activity "Setup venv313" -Status "Install torch + torchvision (CPU fallback)" -PercentComplete 85
        & $py -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cpu
    }
} else {
    Write-Host "[INFO] No working NVIDIA detected. Installing Torch CPU wheels."
    Write-Progress -Activity "Setup venv313" -Status "Install torch + torchvision (CPU)" -PercentComplete 85
    & $py -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cpu
}

Write-Progress -Activity "Setup venv313" -Status "Verify imports" -PercentComplete 95
& $py -c "import clip, cv2, huggingface_hub, mysql.connector, numpy, packaging, PIL, piexif, pyiqa, requests, spellchecker, torch, torchvision, transformers, tqdm; print('OK imports'); print('python', __import__('sys').version.split()[0]); print('torch', torch.__version__); print('cuda', torch.cuda.is_available())"

Write-Progress -Activity "Setup venv313" -Completed
Write-Host "[OK] .venv313 is ready with scoring."
