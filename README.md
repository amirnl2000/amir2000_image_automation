# Amir2000 Image Automation

Local-first photo publishing pipeline for high-volume image sets.

This project automates the path from intake to reviewed metadata and publish:

1. Queue and normalize image sets
2. Extract EXIF and insert/refresh review rows
3. Score quality (NIMA, BRISQUE, CLIP aesthetic)
4. Generate caption, alt text, keywords with local Ollama
5. Review/approve/reject in editor UI
6. Upload approved images/thumbnails to FTP
7. Sync metadata to MySQL and local mirror DB

## Production Updates (Current)

- Nature classifier integration in production:
  - Subject suggestion path in `main_set.py` (classifier-first, Ollama fallback)
  - Caption/alt/keyword generation hints in `caption_review_local.py`
- Review editor metadata retry:
  - `Generate` button in `review_editor.py` regenerates caption/alt/keywords on demand
  - Regenerated output is persisted to DB with current row status
- Publish completion UX:
  - One final completion popup in `review_editor.py`
  - Clicking `OK` closes the review window
- Ollama startup visibility:
  - App startup logs one line with loaded model processor/context/VRAM
  - Example: `processor=GPU context=32768 vram=6.5GiB`
- Optional auto-close of Ollama app process at run end:
  - Controlled by `OLLAMA_CLOSE_ON_RUN_END` (default enabled)

## Key Files

```text
.
|-- amir2000_config.py
|-- main_set.py
|-- batch_image_quality_score.py
|-- caption_review_local.py
|-- review_editor.py
|-- db_uploader.py
|-- init_db.py
|-- simple_inference.py
|-- sac+logos+ava1-l14-linearMSE.pth
|
|-- data/
|   |-- review.db
|   |-- photos_info_revamp.db
|   |-- folder_map.json
|   |-- location_list.json
|   |-- used_filenames.json
|   |-- autofix_dict.json
|   |-- spellcheck_exceptions.json        # optional but recommended
|   |-- ui_state.json                     # optional, UI preference state
|   `-- init/
|       |-- review_queue.sql
|       `-- photos_info_revamp.sql
|
|-- helpers/
|   |-- setup_venv313_full.ps1
|   |-- preflight_multiset.ps1
|   |-- build_multiset.ps1
|   |-- runtime_hook_samevenv_classifier.py
|   |-- copy_pack.ps1
|   `-- sanitize_for_github.ps1
|
|-- utils/
|-- vendor/
|   |-- brisque/
|   `-- clip/
`-- fonts/
```

## Required Config

Edit `amir2000_config.py` and replace all `YOUR_*` placeholders before real runs.

Required areas:

- MySQL: `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASS`, `MYSQL_DB`
- FTP: `FTP_HOST`, `FTP_PORT`, `FTP_USER`, `FTP_PASS`
- Publish targets: `PUBLIC_URL_BASE`, `REMOTE_BASE`
- Paths: `DATA_DIR`, `INCOMING_DIR`, `BASE_PICK_DIR`, `STAGED_DIR`, `REJECTED_DIR`
- Site/Ollama values: `OLLAMA["host"]`, `WEBSITE_V2["base_url"]`, `WEBSITE_V2["resized_root"]`, `WEBSITE_V2["orig_root"]`

## Environment (Python 3.13)

Preferred:

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\helpers\setup_venv313_full.ps1
```

Manual:

```powershell
Set-Location "YOUR_PATH_HERE"
py -3.13 -m venv .venv313
.\.venv313\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -U pyinstaller pillow pyspellchecker piexif mysql-connector-python numpy tqdm opencv-python pyiqa requests
python -m pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

## First-Time Setup

```powershell
Set-Location "YOUR_PATH_HERE"
.\.venv313\Scripts\Activate.ps1
python .\init_db.py
ollama pull llama3.2-vision:latest
ollama pull minicpm-v:latest
```

Keep `sac+logos+ava1-l14-linearMSE.pth` in repo root for full CLIP aesthetic behavior.

## Run

```powershell
Set-Location "YOUR_PATH_HERE"
.\.venv313\Scripts\Activate.ps1
python .\main_set.py
```

In EXE mode, check startup console line:

- `[INFO] Ollama startup check: model=... processor=GPU/CPU context=... vram=...`

## Useful Runtime Flags

- `NATURE_SUBJECT_ENABLE=1` (default)
- `NATURE_SUBJECT_MODEL=openai/clip-vit-large-patch14`
- `NATURE_CLASSIFIER_ENABLE=1` (default)
- `NATURE_CLASSIFIER_MODEL=openai/clip-vit-large-patch14`
- `OLLAMA_CLOSE_ON_RUN_END=1` (default)
- `AUTO_AI_SUBJECT_ON_SELECT=0` (optional, disable auto subject suggest on selection)

## Build EXE

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\helpers\build_multiset.ps1 -Clean -BuildProfile Lite
```

Output:

- `dist/Amir2000ImageAutomation-MultiSet.exe`

## Backup and Sanitize

Curated runnable backup:

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\copy_pack.ps1
```

GitHub-safe sanitized export:

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\sanitize_for_github.ps1 -Latest
```

## Notes on Generated Folders

These are generated at runtime and can be removed when app is closed:

- `data/ollama_tmp`
- `data/_runtime_scripts`
- `logs/*` run/build logs

Optional report/history files that can be recreated:

- `data/new_taxonomy_log.json`
- `data/prefill_qc_last.json`

