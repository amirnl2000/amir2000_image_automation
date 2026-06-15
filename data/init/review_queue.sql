-- Auto-generated init schema
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;

DROP TABLE IF EXISTS "review_queue";

CREATE TABLE review_queue(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Folder TEXT, File_Name TEXT, Path TEXT, ollama_path TEXT, Thumb_Path TEXT,
            DateTime TEXT, Camera TEXT, Lens_model TEXT,
            Width INTEGER, Height INTEGER, Exposure TEXT, Aperture TEXT,
            ISO INTEGER, Focal_length INTEGER,
            Keywords TEXT, Caption TEXT, alt_text TEXT, Location TEXT, Subject TEXT,
            nima_score REAL, blur_score REAL, brightness_score REAL,
            contrast_score REAL, QR REAL, QC_Status TEXT, Review_Status TEXT,
            Original_File_Name TEXT, brisque_score REAL, clip_aesthetic_score REAL,
            identifier_route TEXT, identifier_category TEXT, identifier_subject TEXT,
            identifier_confidence INTEGER, subject_seed TEXT, subject_seed_mode TEXT,
            subject_seed_confidence INTEGER, subject_seed_reason TEXT, identifier_raw_json TEXT,
            ai_suggested_subject TEXT, final_subject TEXT
        , "batch_set_index" INTEGER, "batch_set_total" INTEGER, "series_key" TEXT, "series_cluster_index" INTEGER, "series_position" INTEGER, "series_count" INTEGER, "series_similarity_score" REAL, "series_reason" TEXT, "visual_hash" TEXT, "visual_variant" TEXT, "metadata_version" INTEGER DEFAULT 1);

COMMIT;
