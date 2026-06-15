from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageOps, ImageStat


SERIES_COLUMNS = {
    "batch_set_index": "INTEGER",
    "batch_set_total": "INTEGER",
    "series_key": "TEXT",
    "series_cluster_index": "INTEGER",
    "series_position": "INTEGER",
    "series_count": "INTEGER",
    "series_similarity_score": "REAL",
    "series_reason": "TEXT",
    "visual_hash": "TEXT",
    "visual_variant": "TEXT",
    "metadata_version": "INTEGER DEFAULT 1",
}


_SEQ_RE = re.compile(r"(\d+)(?!.*\d)")


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def slug(value: Any, fallback: str = "set") -> str:
    text = norm(value).lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


def stable_hash(value: Any, chars: int = 12) -> str:
    raw = norm(value).encode("utf-8", errors="ignore")
    return hashlib.sha1(raw).hexdigest()[: max(6, int(chars))]


def q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def db_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({q(table)})").fetchall()}


def ensure_series_columns(conn: sqlite3.Connection, table: str) -> None:
    have = db_columns(conn, table)
    for name, definition in SERIES_COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {q(table)} ADD COLUMN {q(name)} {definition}")
    conn.commit()


def parse_id_list(value: str) -> List[int]:
    ids: List[int] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except Exception:
            pass
    return sorted({x for x in ids if x > 0})


def parse_datetime(value: Any) -> Optional[float]:
    text = norm(value)
    if not text:
        return None
    text = text.replace("T", " ")
    for fmt in (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(text[:19], fmt).timestamp()
        except Exception:
            continue
    return None


def filename_number(row: sqlite3.Row) -> int:
    for key in ("Original_File_Name", "File_Name", "Path"):
        text = norm(row[key]) if key in row.keys() else ""
        if not text:
            continue
        match = _SEQ_RE.search(Path(text).stem)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                pass
    try:
        return int(row["id"])
    except Exception:
        return 0


def orientation(width: Any, height: Any) -> str:
    try:
        w = float(width or 0)
        h = float(height or 0)
    except Exception:
        return "unknown"
    if w <= 0 or h <= 0:
        return "unknown"
    ratio = w / h
    if ratio > 1.15:
        return "landscape"
    if ratio < 0.87:
        return "portrait"
    return "square"


def focal_bucket(value: Any) -> str:
    try:
        fl = float(value or 0)
    except Exception:
        return "unknown-lens"
    if fl <= 0:
        return "unknown-lens"
    if fl < 24:
        return "ultrawide"
    if fl < 45:
        return "wide"
    if fl < 90:
        return "normal"
    if fl < 220:
        return "telephoto"
    return "long-lens"


def image_path_for_hash(row: sqlite3.Row) -> Optional[Path]:
    for key in ("ollama_path", "Path", "Thumb_Path"):
        if key not in row.keys():
            continue
        text = norm(row[key])
        if not text:
            continue
        path = Path(text)
        if path.exists():
            return path
    return None


def avg_hash_and_brightness(path: Path) -> Tuple[str, Optional[float]]:
    with Image.open(path) as img:
        gray = ImageOps.exif_transpose(img).convert("L")
        small = gray.resize((8, 8), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
        mean = sum(pixels) / max(1, len(pixels))
        bits = "".join("1" if px >= mean else "0" for px in pixels)
        value = int(bits, 2)
        stat_img = gray.resize((32, 32), Image.Resampling.LANCZOS)
        brightness = float(ImageStat.Stat(stat_img).mean[0]) / 255.0
        return f"{value:016x}", brightness


def hamming(a: str, b: str) -> Optional[int]:
    if not a or not b:
        return None
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except Exception:
        return None


def hash_similarity(a: str, b: str) -> Optional[float]:
    dist = hamming(a, b)
    if dist is None:
        return None
    return max(0.0, min(1.0, 1.0 - (dist / 64.0)))


def brightness_bucket(value: Optional[float]) -> str:
    if value is None:
        return "unknown-light"
    if value < 0.28:
        return "low-light"
    if value > 0.68:
        return "bright"
    return "mid-light"


@dataclass
class FeatureRow:
    row: sqlite3.Row
    row_id: int
    partition: str
    order_no: int
    captured_ts: Optional[float]
    orient: str
    lens: str
    visual_hash: str
    brightness: Optional[float]


def load_rows(conn: sqlite3.Connection, table: str, statuses: Sequence[str], ids: Sequence[int]) -> List[sqlite3.Row]:
    have = db_columns(conn, table)
    if "id" not in have:
        raise RuntimeError(f"{table} must have an id column")

    sql = f"SELECT * FROM {q(table)}"
    params: List[Any] = []
    where: List[str] = []

    if ids:
        marks = ",".join("?" for _ in ids)
        where.append(f"id IN ({marks})")
        params.extend([int(x) for x in ids])
    elif statuses and "Review_Status" in have:
        marks = ",".join("?" for _ in statuses)
        where.append(f"COALESCE(Review_Status, '') IN ({marks})")
        params.extend(list(statuses))

    if where:
        sql += " WHERE " + " AND ".join(where)

    sql += " ORDER BY COALESCE(batch_set_index, id), id"
    return list(conn.execute(sql, params).fetchall())


def row_partition(row: sqlite3.Row) -> str:
    keys = set(row.keys())
    set_index = row["batch_set_index"] if "batch_set_index" in keys else None
    if set_index is not None and str(set_index).strip() != "":
        return f"set:{int(set_index)}"

    subject = norm(row["final_subject"] if "final_subject" in keys else "") or norm(row["Subject"] if "Subject" in keys else "")
    location = norm(row["Location"] if "Location" in keys else "")
    folder = norm(row["Folder"] if "Folder" in keys else "")
    return "fallback:" + stable_hash("|".join([slug(folder), slug(location), slug(subject)]), 12)


def build_features(rows: Sequence[sqlite3.Row]) -> List[FeatureRow]:
    features: List[FeatureRow] = []
    for row in rows:
        row_id = int(row["id"])
        img_path = image_path_for_hash(row)
        visual_hash = ""
        brightness = None
        if img_path is not None:
            try:
                visual_hash, brightness = avg_hash_and_brightness(img_path)
            except Exception as exc:
                print(f"[WARN] id={row_id} visual hash failed: {type(exc).__name__}: {exc}")

        features.append(
            FeatureRow(
                row=row,
                row_id=row_id,
                partition=row_partition(row),
                order_no=filename_number(row),
                captured_ts=parse_datetime(row["DateTime"] if "DateTime" in row.keys() else ""),
                orient=orientation(row["Width"] if "Width" in row.keys() else None, row["Height"] if "Height" in row.keys() else None),
                lens=focal_bucket(row["Focal_length"] if "Focal_length" in row.keys() else None),
                visual_hash=visual_hash,
                brightness=brightness,
            )
        )
    return features


def sort_key(feature: FeatureRow) -> Tuple[int, float, int, int]:
    ts = feature.captured_ts if feature.captured_ts is not None else 0.0
    return (feature.order_no or 0, ts, feature.row_id, 0)


def pair_similarity(a: FeatureRow, b: FeatureRow) -> float:
    scores: List[Tuple[float, float]] = []

    hs = hash_similarity(a.visual_hash, b.visual_hash)
    if hs is not None:
        scores.append((0.55, hs))

    if a.order_no and b.order_no:
        gap = abs(a.order_no - b.order_no)
        scores.append((0.20, max(0.0, 1.0 - min(gap, 24) / 24.0)))

    if a.captured_ts is not None and b.captured_ts is not None:
        gap_sec = abs(a.captured_ts - b.captured_ts)
        scores.append((0.15, max(0.0, 1.0 - min(gap_sec, 7200.0) / 7200.0)))

    if a.orient != "unknown" and b.orient != "unknown":
        scores.append((0.10, 1.0 if a.orient == b.orient else 0.0))

    if not scores:
        return 0.5

    total_weight = sum(w for w, _ in scores)
    return sum(w * s for w, s in scores) / max(0.001, total_weight)


def cluster_partition(features: Sequence[FeatureRow], split: bool) -> List[List[FeatureRow]]:
    ordered = sorted(features, key=sort_key)
    if not split or len(ordered) <= 2:
        return [ordered]

    clusters: List[List[FeatureRow]] = []
    for feature in ordered:
        best_index = -1
        best_score = -1.0
        for index, cluster in enumerate(clusters):
            representative = cluster[0]
            score = pair_similarity(feature, representative)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0 and best_score >= 0.62:
            clusters[best_index].append(feature)
        else:
            clusters.append([feature])
    return clusters


def variant_for(feature: FeatureRow, position: int) -> str:
    return "_".join(
        [
            feature.orient,
            feature.lens,
            brightness_bucket(feature.brightness),
            f"v{int(position):03d}",
        ]
    )


def update_series(conn: sqlite3.Connection, table: str, rows: Sequence[sqlite3.Row], split_within_set: bool) -> Dict[str, Any]:
    features = build_features(rows)
    by_partition: Dict[str, List[FeatureRow]] = {}
    for feature in features:
        by_partition.setdefault(feature.partition, []).append(feature)

    series_total = 0
    updated = 0
    one_row_series = 0
    multi_row_series = 0

    for partition, partition_features in sorted(by_partition.items()):
        explicit_set = partition.startswith("set:")
        split = split_within_set or not explicit_set
        clusters = cluster_partition(partition_features, split=split)

        for cluster_index, cluster in enumerate(clusters, start=1):
            ordered = sorted(cluster, key=sort_key)
            first = ordered[0]
            seed = "|".join(
                [
                    partition,
                    str(cluster_index),
                    norm(first.row["Subject"] if "Subject" in first.row.keys() else ""),
                    norm(first.row["Location"] if "Location" in first.row.keys() else ""),
                    str(first.order_no),
                    first.visual_hash[:8],
                ]
            )
            series_key = "ser_" + stable_hash(seed, 14)
            series_count = len(ordered)
            series_total += 1
            if series_count > 1:
                multi_row_series += 1
            else:
                one_row_series += 1

            similarities = [
                pair_similarity(feature, first)
                for feature in ordered
                if feature.row_id != first.row_id
            ]
            avg_similarity = float(sum(similarities) / len(similarities)) if similarities else 1.0
            reason = {
                "source": "batch_set" if explicit_set else "generic_cluster",
                "split_within_set": bool(split_within_set),
                "rows": series_count,
                "avg_similarity": round(avg_similarity, 3),
                "signals": ["set_boundary", "file_order", "capture_time", "orientation", "phash"],
            }

            for position, feature in enumerate(ordered, start=1):
                row_similarity = 1.0 if feature.row_id == first.row_id else pair_similarity(feature, first)
                conn.execute(
                    f"""
                    UPDATE {q(table)}
                    SET
                        series_key = ?,
                        series_cluster_index = ?,
                        series_position = ?,
                        series_count = ?,
                        series_similarity_score = ?,
                        series_reason = ?,
                        visual_hash = ?,
                        visual_variant = ?,
                        metadata_version = COALESCE(metadata_version, 1)
                    WHERE id = ?
                    """,
                    (
                        series_key,
                        cluster_index,
                        position,
                        series_count,
                        round(float(row_similarity), 4),
                        json.dumps(reason, separators=(",", ":"), sort_keys=True),
                        feature.visual_hash,
                        variant_for(feature, position),
                        feature.row_id,
                    ),
                )
                updated += 1

    conn.commit()
    return {
        "rows": len(rows),
        "updated": updated,
        "series_total": series_total,
        "multi_row_series": multi_row_series,
        "one_row_series": one_row_series,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generic non-topic series/versioning analyzer for review_queue rows.")
    parser.add_argument("--db", required=True)
    parser.add_argument("--table", default="review_queue")
    parser.add_argument("--status", default="Queued", help="Comma-separated statuses to analyze when --id-list is omitted.")
    parser.add_argument("--id-list", default="", help="Optional comma-separated row ids.")
    parser.add_argument("--split-within-set", action="store_true", help="Allow visual clustering inside one selected set.")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[FAIL] DB not found: {db_path}")
        return 2

    statuses = [part.strip() for part in str(args.status or "").split(",") if part.strip()]
    ids = parse_id_list(args.id_list)

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        ensure_series_columns(conn, args.table)
        rows = load_rows(conn, args.table, statuses=statuses, ids=ids)
        if not rows:
            print("[SERIES] No rows to analyze.")
            return 0

        summary = update_series(conn, args.table, rows, split_within_set=bool(args.split_within_set))

    print(
        "[SERIES] Generic versioning complete | "
        f"rows={summary['rows']} updated={summary['updated']} "
        f"series={summary['series_total']} multi={summary['multi_row_series']} single={summary['one_row_series']}"
    )
    print(f"[OK] rows={summary['updated']} series={summary['series_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
