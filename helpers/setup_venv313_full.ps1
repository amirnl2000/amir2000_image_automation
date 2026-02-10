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

Write-Progress -Activity "Setup venv313" -Status "Install base runtime deps" -PercentComplete 40
& $py -m pip install -U pyinstaller pillow pyspellchecker piexif mysql-connector-python

Write-Progress -Activity "Setup venv313" -Status "Install scoring deps (numpy tqdm opencv pyiqa)" -PercentComplete 60
& $py -m pip install -U numpy tqdm opencv-python pyiqa

# Torch: auto detect NVIDIA via nvidia-smi. If it works, use CUDA wheels. Else CPU wheels.
$useCuda = $false
Write-Progress -Activity "Setup venv313" -Status "Detect NVIDIA GPU (nvidia-smi)" -PercentComplete 70
$nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvsmi) {
    try {
        & $nvsmi.Source | Out-Null
        if ($LASTEXITCODE -eq 0) { $useCuda = $true }
    } catch {
        $useCuda = $false
    }
}

if ($useCuda) {
    Write-Host "[INFO] NVIDIA detected. Installing Torch CUDA wheels (cu121)."
    Write-Progress -Activity "Setup venv313" -Status "Install torch + torchvision (CUDA cu121)" -PercentComplete 85
    & $py -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cu121
} else {
    Write-Host "[INFO] No working NVIDIA detected. Installing Torch CPU wheels."
    Write-Progress -Activity "Setup venv313" -Status "Install torch + torchvision (CPU)" -PercentComplete 85
    & $py -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cpu
}

Write-Progress -Activity "Setup venv313" -Status "Verify imports" -PercentComplete 95
& $py -c "import numpy, tqdm, cv2, torch, torchvision, pyiqa; print('OK imports'); print('python', __import__('sys').version.split()[0]); print('torch', torch.__version__); print('cuda', torch.cuda.is_available())"

Write-Progress -Activity "Setup venv313" -Completed
Write-Host "[OK] .venv313 is ready with scoring."
