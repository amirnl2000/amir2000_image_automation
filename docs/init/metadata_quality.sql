-- Auto-generated init schema
-- Amir2000 Image Automation V1.0 metadata quality proof table.
-- Records generated, repaired, accepted, and blocked metadata for audit,
-- upload readiness, and the first ML feedback/evaluation layer.
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;

DROP TABLE IF EXISTS "metadata_quality";

CREATE TABLE metadata_quality (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
    revamp_id INTEGER,
    revamp_File_Name TEXT NOT NULL,
    revamp_Original_File_Name TEXT,
    revamp_Location TEXT,
    revamp_Folder TEXT,
    current_caption TEXT,
    current_alt_text TEXT,
    current_keywords TEXT,
    upload_caption TEXT,
    upload_alt_text TEXT,
    upload_keywords TEXT,
    overall_quality_status TEXT,
    overall_quality_score REAL,
    overall_quality_issues TEXT,
    generation_mode TEXT,
    repair_attempts INTEGER DEFAULT 0,
    fallback_used INTEGER DEFAULT 0,
    fallback_reason TEXT,
    accepted_for_upload INTEGER DEFAULT 0,
    caption_accepted_for_upload INTEGER DEFAULT 0,
    alt_text_accepted_for_upload INTEGER DEFAULT 0,
    keywords_accepted_for_upload INTEGER DEFAULT 0,
    part_of_serie INTEGER DEFAULT 0,
    unique_name TEXT,
    ai_suggested_subject TEXT,
    final_subject TEXT,
    subject_seed TEXT,
    subject_seed_mode TEXT,
    subject_seed_confidence INTEGER,
    subject_seed_reason TEXT,
    manual_decision TEXT,
    uploaded_to_mysql INTEGER DEFAULT 0,
    mysql_synced_at TEXT,
    upload_public_path TEXT,
    upload_status TEXT,
    source_review_status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        , batch_set_index INTEGER, batch_set_total INTEGER, series_key TEXT, series_cluster_index INTEGER, series_position INTEGER, series_count INTEGER, series_similarity_score REAL, series_reason TEXT, visual_hash TEXT, visual_variant TEXT, metadata_version INTEGER DEFAULT 1);

DROP INDEX IF EXISTS "idx_metadata_quality_file";
CREATE INDEX idx_metadata_quality_file ON metadata_quality(revamp_File_Name);

DROP INDEX IF EXISTS "idx_metadata_quality_revamp_id";
CREATE INDEX idx_metadata_quality_revamp_id
        ON metadata_quality(revamp_id);

DROP INDEX IF EXISTS "idx_metadata_quality_status";
CREATE INDEX idx_metadata_quality_status
        ON metadata_quality(overall_quality_status);

DROP INDEX IF EXISTS "uq_metadata_quality_file";
CREATE UNIQUE INDEX uq_metadata_quality_file
        ON metadata_quality(revamp_File_Name);

COMMIT;
