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
                Original_File_Name TEXT, brisque_score REAL, clip_aesthetic_score REAL
            );

COMMIT;
