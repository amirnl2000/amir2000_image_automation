-- Auto-generated init schema
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;

DROP TABLE IF EXISTS "photos_info_revamp";

CREATE TABLE "photos_info_revamp" ("id" INTEGER NOT NULL, "Folder" TEXT, "File_Name" TEXT, "Path" TEXT, "Thumb_Path" TEXT, "DateTime" TEXT, "Camera" TEXT, "Lens_model" TEXT, "Width" INTEGER DEFAULT 0, "Height" INTEGER DEFAULT 0, "Exposure" TEXT, "Aperture" TEXT, "ISO" INTEGER, "Focal_length" INTEGER, "Keywords" TEXT, "Caption" TEXT, "alt_text" TEXT, "Location" TEXT, "QR" INTEGER, "QC_Status" TEXT, "Original_File_Name" TEXT NOT NULL, "nima_score" REAL, "blur_score" REAL, "brightness_score" REAL, "contrast_score" REAL, "brisque_score" REAL, "clip_aesthetic_score" REAL, PRIMARY KEY ("id"));

COMMIT;
