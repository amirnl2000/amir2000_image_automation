# Amir2000 Image Automation

Local-first photo publishing pipeline for high-volume image sets.

This project automates the full path from raw image intake to reviewed metadata and website publish:

1. Queue and normalize image sets
2. Extract EXIF and create review rows
3. Score quality (NIMA, BRISQUE, CLIP aesthetic)
4. Generate caption, alt text, keywords with local Ollama
5. Review/approve/reject in editor UI
6. Upload approved images/thumbnails to FTP
7. Sync metadata to MySQL and local mirror DB

## Key Capabilities

- End-to-end guided desktop workflow (`main_set.py`)
- Series-aware caption generation with anti-duplication checks (`caption_review_local.py`)
- Strict filename reservation and duplicate prevention (`data/used_filenames.json`)
- EXIF-preserving resize/watermark pipeline (`utils/image_processor.py`)
- Review-first publishing with rollback on failures (`review_editor.py`, `db_uploader.py`)
- PyInstaller build path for one-click EXE distribution (`helpers/build_multiset.ps1`)

## Project Structure

```text
.
|-- amir2000_config.py               # Environment + pipeline config (edit this first)
|-- main_set.py                      # Main workflow UI and stage orchestration
|-- batch_image_quality_score.py     # Quality metrics stage
|-- caption_review_local.py          # Local LLM caption/keyword generation
|-- review_editor.py                 # Review/approve/publish UI
|-- db_uploader.py                   # FTP + MySQL publish sync
|-- init_db.py                       # Rebuild local SQLite DBs from data/init
|-- simple_inference.py              # Standalone inference helper
|-- sac+logos+ava1-l14-linearMSE.pth # Required CLIP aesthetic weights
|
|-- data/
|   |-- init/
|   |   |-- review_queue.sql
|   |   `-- photos_info_revamp.sql
|   |-- folder_map.json
|   |-- location_list.json
|   |-- used_filenames.json
|   `-- autofix_dict.json
|
|-- docs/
|   `-- init/
|       |-- review_queue.sql
|       `-- photos_info_revamp.sql
|
|-- helpers/
|   |-- setup_venv313_full.ps1       # Create/install runtime environment
|   |-- preflight_multiset.ps1       # Pre-build validations
|   |-- build_multiset.ps1           # EXE build script
|   `-- copy_pack.ps1                # Curated backup pack creator
|
|-- utils/                           # Shared workflow modules
|-- vendor/
|   |-- brisque/                     # BRISQUE model files
|   `-- clip/                        # CLIP tokenizer/vocab assets
`-- fonts/                           # UI fonts used by the workflow
```

## Before First Run (Required)

Edit `amir2000_config.py` and replace all placeholder values (`YOUR_*`):

- Database/FTP credentials:
  - `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASS`, `MYSQL_DB`
  - `FTP_HOST`, `FTP_PORT`, `FTP_USER`, `FTP_PASS`
- Publish targets:
  - `PUBLIC_URL_BASE`, `REMOTE_BASE`
- Local paths:
  - `DATA_DIR`, `INCOMING_DIR`, `BASE_PICK_DIR`, `STAGED_DIR`, `REJECTED_DIR`
  - `DESKTOP_ROOT`, `ARCHIVE_ROOT`, `LOCAL_SITE_IMAGES_BASE`
- Required endpoint/site values for your environment:
  - `OLLAMA["host"]`, `WEBSITE_V2["base_url"]`, `WEBSITE_V2["resized_root"]`, `WEBSITE_V2["orig_root"]`

Do not publish with placeholders still present.

## Create Environment (Python 3.13)

Preferred (installs all runtime deps + Torch CPU/CUDA auto-detect):

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\helpers\setup_venv313_full.ps1
```

Manual alternative:

```powershell
Set-Location "YOUR_PATH_HERE"
py -3.13 -m venv .venv313
.\.venv313\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -U pyinstaller pillow pyspellchecker piexif mysql-connector-python numpy tqdm opencv-python pyiqa requests
python -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

## First-Time Setup Checklist

1. Install prerequisites on Windows:
   - Python 3.13 (`py -3.13`) from https://www.python.org/downloads/windows/
   - Ollama (service running) from https://ollama.com/download
2. Create environment (preferred command above).
3. Initialize local DB files:

```powershell
Set-Location "YOUR_PATH_HERE"
.\.venv313\Scripts\Activate.ps1
python .\init_db.py
```

4. Pull required Ollama models (or set different ones in env/config):

```powershell
ollama pull llama3.2-vision:latest
ollama pull minicpm-v:latest
```

5. Required for complete quality scoring stage:
   - Keep `sac+logos+ava1-l14-linearMSE.pth` in repository root.
   - This pack includes it. Do not remove it if you want full workflow behavior.

## Libraries Used By The Automation Flow

- Core runtime: `pillow`, `pyspellchecker`, `piexif`, `mysql-connector-python`, `requests`
- Scoring/runtime: `numpy`, `tqdm`, `opencv-python`, `pyiqa`
- Torch backend: `torch`, `torchvision`
- Build tooling: `pyinstaller`

## Run The Automation Flow

1. Start Ollama and ensure configured models are available (`ollama list`).
2. Activate environment:

```powershell
Set-Location "YOUR_PATH_HERE"
.\.venv313\Scripts\Activate.ps1
```

3. Start pipeline UI:

```powershell
python .\main_set.py
```

4. Process sets -> review in editor -> publish approved rows.

## What To Adjust In Files

- Required:
  - `amir2000_config.py` (all placeholders and environment-specific paths/credentials)
  - Validate `main_set.py` fallback host/port defaults (`OLLAMA_HOST`, `OLLAMA_PORT`) match your environment if you changed them in config/env.

## Build EXE

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\helpers\build_multiset.ps1 -Clean -BuildProfile Lite
```

## Documentation Index

- `docs/init/review_queue.sql`
- `docs/init/photos_info_revamp.sql`

