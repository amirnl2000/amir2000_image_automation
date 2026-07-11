# Amir2000 Image Automation V1.0

Local-first photography workflow for preparing large image batches for review and publishing.

This project automates the path from image intake to upload-ready metadata:

1. Import one or more image sets.
2. Extract EXIF and create local review rows.
3. Score technical and aesthetic image quality.
4. Suggest or identify subjects from image evidence.
5. Generate captions, alt text, and keywords.
6. Repair weak metadata before review.
7. Prove metadata quality in a dedicated audit table.
8. Review, approve, reject, and publish approved rows.

The workflow is designed for repeatable batches of different subjects, locations, and image types. It should not depend on per-topic hardcoded fixes.

## V1.0 Focus

V1.0 adds the identifier and metadata-quality layers needed for a reproducible workflow:

- Multi-set batch orchestration in `main_set.py`.
- Subject suggestion and identification through the `scripts/` identifier modules.
- Image-evidence metadata generation through `metadata_evidence_pipeline.py`.
- Deterministic repair through `scripts/metadata_auto_repair_loop.py`.
- Upload-readiness proof through `scripts/metadata_quality_production.py`.
- Review and publish control through `review_editor.py` and `db_uploader.py`.
- Color-managed website export through `utils/image_processor.py`: tagged source ICC profiles are converted to sRGB, and the generated web JPG plus thumbnail embed an sRGB ICC profile.

## Workflow Safeguards

- Identifier routing uses image evidence and separate biological and aircraft refinement paths; it does not treat broad labels as a final species or aircraft result when stronger evidence is available.
- Metadata-quality repair is limited to captions, alt text, and keywords. It preserves the selected subject, location, and folder/category.
- For aviation sets, the selected aircraft subject is retained while each image receives scene-specific metadata from its own composition.
- Filename formatting preserves meaningful aircraft-registration hyphens, and spellcheck offers close correction suggestions without changing accepted terms automatically.
- Runtime script copies, operational databases, logs, model caches, and full local JSON data remain local-only and are not part of the public workflow repository.

## Metadata Quality and ML Readiness

`metadata_quality` is the proof and audit table for generated captions, alt text, and keywords.

It stores the generated fields, repaired fields, pass/fail status, quality issues, subject evidence, series context, and upload state. This makes the workflow measurable instead of only manual. Approved, rejected, repaired, and uploaded rows can later become the first evaluation dataset for metadata improvement.

In V1.0 this is the start of the ML feedback layer: the system records what passed, what failed, and why.

## Publish Image Export Quality

Approved images are resized and watermarked by `utils/image_processor.py` before FTP upload. The export path is color-managed: tagged source images are converted to sRGB with Pillow `ImageCms`, and both the website JPG and thumbnail are saved with an embedded sRGB ICC profile. This avoids faded browser/viewer output from wide-gamut source files.

For already-exported 2026 files, `scripts/reexport_2026_srgb_from_originals.py` can audit, re-export, and optionally re-upload website JPGs from the preserved originals. It defaults to dry-run, supports `--apply --upload`, and can resume failed FTP rows with `--retry-failed-report`.

## Key Files

```text
.
|-- main_set.py
|-- review_editor.py
|-- caption_review_local.py
|-- batch_image_quality_score.py
|-- metadata_evidence_pipeline.py
|-- run_metadata_quality_production.ps1
|-- db_uploader.py
|-- init_db.py
|-- simple_inference.py
|-- amir2000_config.py
|
|-- data/
|   `-- init/
|       |-- review_queue.sql
|       |-- photos_info_revamp.sql
|       `-- metadata_quality.sql
|
|-- docs/
|   `-- init/
|       |-- review_queue.sql
|       |-- photos_info_revamp.sql
|       `-- metadata_quality.sql
|
|-- helpers/
|   |-- setup_venv313_full.ps1
|   |-- preflight_multiset.ps1
|   |-- build_multiset.ps1
|   `-- runtime_hook_samevenv_classifier.py
|
|-- scripts/
|   |-- subject_identifier_production.py
|   |-- subject_identifier_engine.py
|   |-- evidence_subject_pipeline.py
|   |-- identifier_router.py
|   |-- identifier_biology_runner.py
|   |-- identifier_biology_inaturalist.py
|   |-- identifier_biology_bioclip.py
|   |-- identifier_general_vision.py
|   |-- identifier_vehicle_aircraft.py
|   |-- identifier_visual_evidence.py
|   |-- identifier_consensus.py
|   |-- identifier_db_setup.py
|   |-- apply_identifier_router_result_to_db.py
|   |-- download_identifier_models.py
|   |-- series_versioning.py
|   |-- metadata_auto_repair_loop.py
|   |-- metadata_quality_production.py
|   `-- reexport_2026_srgb_from_originals.py
|
|-- utils/
|-- vendor/
|-- fonts/
`-- sac+logos+ava1-l14-linearMSE.pth
```

## Required Config

Edit `amir2000_config.py` and replace all `YOUR_*` placeholders before real runs.

Required areas:

- MySQL settings
- FTP settings
- Publish target URLs and remote paths
- Local image intake paths
- Ollama host/model settings

Do not commit private credentials, local run logs, generated databases, image folders, temporary model caches, or backup packs.

## Environment

Preferred setup:

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\helpers\setup_venv313_full.ps1
```

Manual setup:

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
ollama pull qwen3-vl:4b
```

Keep `sac+logos+ava1-l14-linearMSE.pth` in the repo root for CLIP aesthetic scoring.

## Run

```powershell
Set-Location "YOUR_PATH_HERE"
.\.venv313\Scripts\Activate.ps1
python .\main_set.py
```

## Build EXE

```powershell
Set-Location "YOUR_PATH_HERE"
pwsh -NoProfile -ExecutionPolicy Bypass -File .\helpers\build_multiset.ps1 -Clean -BuildProfile Lite
```

Output:

```text
dist/Amir2000ImageAutomation-MultiSet.exe
```

## Generated Runtime Files

Generated runtime folders and files should not be committed:

- `data/ollama_tmp`
- `data/_runtime_scripts`
- `data/*_tmp`
- `logs/*`
- local `.db` files
- backup packs
- model cache folders

## Public Documentation

The V1.0 workflow is documented as a public case study on:

```text
https://www.amir2000.com/
```
