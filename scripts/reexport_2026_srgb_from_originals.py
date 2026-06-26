from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from ftplib import FTP
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageCms  # type: ignore
from io import BytesIO

from amir2000_config import FTP_CONFIG, PATHS, PUBLISH
from utils.image_processor import resize_and_watermark


WATERMARK_TEXT = "© YOUR_HOST\nPhotography"
FONT_PATH = ROOT / "fonts" / "Montserrat-Light.ttf"
IMAGE_EXTS = {".jpg", ".jpeg"}


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def dated(path: Path) -> date:
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def profile_name(path: Path) -> str:
    try:
        with Image.open(path) as img:
            icc = img.info.get("icc_profile")
        if not icc:
            return "MISSING"
        try:
            profile = ImageCms.ImageCmsProfile(BytesIO(icc))
            return (ImageCms.getProfileName(profile) or "UNKNOWN").strip()
        except Exception as exc:
            return f"UNREADABLE:{type(exc).__name__}"
    except Exception as exc:
        return f"OPEN_ERROR:{type(exc).__name__}"


def is_srgb_profile(name: str) -> bool:
    return "srgb" in (name or "").lower()


def year_base(root: Path, year: str) -> Path:
    return root if root.name == year else root / year


def find_original(rel_path: Path, original_roots: list[Path], year: str) -> Path | None:
    for root in original_roots:
        base = year_base(root, year)
        candidate = base / rel_path
        if candidate.exists():
            return candidate
    return None


def mkdir_p(ftp: FTP, remote_dir: str) -> None:
    ftp.cwd("/")
    for part in remote_dir.strip("/").split("/"):
        if not part:
            continue
        try:
            ftp.cwd(part)
        except Exception:
            ftp.mkd(part)
            ftp.cwd(part)


def upload_pair(ftp: FTP, web_path: Path, thumb_path: Path, rel_path: Path, year: str) -> None:
    remote_base = str(PUBLISH.get("REMOTE_BASE") or "").strip("/")
    folder = rel_path.parent.as_posix()
    filename = rel_path.name

    remote_web_dir = "/".join(p for p in [remote_base, year, folder] if p)
    remote_thumb_dir = "/".join(p for p in [remote_base, year, "thumbs", folder] if p)

    mkdir_p(ftp, remote_web_dir)
    with web_path.open("rb") as f:
        ftp.storbinary(f"STOR {filename}", f)

    mkdir_p(ftp, remote_thumb_dir)
    with thumb_path.open("rb") as f:
        ftp.storbinary(f"STOR {filename}", f)


def open_ftp() -> FTP:
    ftp = FTP()
    ftp.connect(FTP_CONFIG["host"], int(FTP_CONFIG.get("port", 21) or 21), timeout=60)
    ftp.login(FTP_CONFIG["user"], FTP_CONFIG["passwd"])
    ftp.encoding = "utf-8"
    return ftp


def close_ftp(ftp: FTP | None) -> None:
    if ftp is None:
        return
    try:
        ftp.quit()
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass


def iter_web_images(local_year_root: Path):
    for path in sorted(local_year_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            rel = path.relative_to(local_year_root)
        except ValueError:
            continue
        parts = rel.parts
        if parts and parts[0].lower() == "thumbs":
            continue
        yield path, rel


def retry_failed_uploads(args, local_year_root: Path, year: str, report_path: Path) -> int:
    source_report = Path(args.retry_failed_report)
    if not source_report.exists():
        raise SystemExit(f"retry report not found: {source_report}")

    retry_rows: list[dict[str, str]] = []
    with source_report.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if str(row.get("status") or "").strip().upper() == "FAILED":
                retry_rows.append(row)

    if args.limit:
        retry_rows = retry_rows[: args.limit]

    out_rows: list[dict[str, str]] = []
    checked = uploaded = failed = missing_local = 0
    ftp: FTP | None = open_ftp() if args.upload else None
    reconnect_every = max(1, int(args.reconnect_every or 200))

    try:
        for row in retry_rows:
            checked += 1
            web_path = Path(row.get("web_path") or "")
            status = "WOULD_UPLOAD"
            message = ""

            try:
                rel_path = web_path.relative_to(local_year_root)
            except ValueError:
                status = "FAILED"
                message = f"web_path is not under local year root: {local_year_root}"
                failed += 1
                out_rows.append({**row, "retry_status": status, "retry_message": message})
                continue

            thumb_path = local_year_root / "thumbs" / rel_path
            if not web_path.exists() or not thumb_path.exists():
                status = "MISSING_LOCAL"
                message = f"web_exists={web_path.exists()} thumb_exists={thumb_path.exists()}"
                missing_local += 1
                out_rows.append({**row, "retry_status": status, "retry_message": message})
                continue

            if args.upload:
                if uploaded and uploaded % reconnect_every == 0:
                    close_ftp(ftp)
                    ftp = open_ftp()
                try:
                    upload_pair(ftp, web_path, thumb_path, rel_path, year)  # type: ignore[arg-type]
                    uploaded += 1
                    status = "RETRY_UPLOADED"
                except Exception as exc:
                    close_ftp(ftp)
                    ftp = open_ftp()
                    try:
                        upload_pair(ftp, web_path, thumb_path, rel_path, year)
                        uploaded += 1
                        status = "RETRY_UPLOADED_AFTER_RECONNECT"
                    except Exception as retry_exc:
                        failed += 1
                        status = "RETRY_FAILED"
                        message = f"{type(exc).__name__}: {exc}; retry={type(retry_exc).__name__}: {retry_exc}"

            out_rows.append({**row, "retry_status": status, "retry_message": message})
    finally:
        close_ftp(ftp)

    with report_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(out_rows[0].keys()) if out_rows else [
            "status",
            "profile",
            "original_profile",
            "web_path",
            "original_path",
            "message",
            "retry_status",
            "retry_message",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"retry_source={source_report}")
    print(f"checked_failed_rows={checked}")
    print(f"uploaded={uploaded}")
    print(f"missing_local={missing_local}")
    print(f"failed={failed}")
    print(f"report={report_path}")
    if not args.upload:
        print("DRY RUN ONLY. Add --upload to upload these failed rows.")
    return 1 if failed or missing_local else 0


def main() -> int:
    today = date.today().isoformat()
    default_local = Path(PATHS.get("LOCAL_SITE_IMAGES_BASE", r"YOUR_PATH_HERE"))
    default_desktop = Path(PATHS.get("DESKTOP_ROOT", r"YOUR_PATH_HERE"))
    fallback_archive = Path(PATHS.get("ARCHIVE_ROOT", r"YOUR_PATH_HERE"))

    parser = argparse.ArgumentParser(
        description="Audit and optionally re-export 2026 web JPGs with proper sRGB ICC from original files."
    )
    parser.add_argument("--year", default="2026")
    parser.add_argument("--start-date", default="2026-01-01", help="Filter by local export modified date.")
    parser.add_argument("--end-date", default=today, help="Filter by local export modified date.")
    parser.add_argument("--local-site-root", default=str(default_local))
    parser.add_argument("--original-root", default=r"YOUR_PATH_HERE")
    parser.add_argument("--fallback-original-root", default=str(fallback_archive))
    parser.add_argument("--desktop-root", default=str(default_desktop))
    parser.add_argument("--report", default="")
    parser.add_argument("--retry-failed-report", default="", help="Upload only FAILED rows from a previous CSV report.")
    parser.add_argument("--reconnect-every", type=int, default=200, help="Reconnect FTP after this many successful retry uploads.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--all", action="store_true", help="Re-export all matched files, not only missing/non-sRGB ICC.")
    parser.add_argument(
        "--only-original-non-srgb",
        action="store_true",
        help="Only re-export rows whose matching original is tagged non-sRGB, such as Wide Gamut RGB.",
    )
    parser.add_argument("--apply", action="store_true", help="Overwrite local web/thumb/desktop files.")
    parser.add_argument("--upload", action="store_true", help="Also overwrite remote FTP web/thumb files. Requires --apply.")
    args = parser.parse_args()

    if args.upload and not args.apply and not args.retry_failed_report:
        raise SystemExit("--upload requires --apply")

    year = str(args.year)
    local_year_root = Path(args.local_site_root) / year
    desktop_root = Path(args.desktop_root)
    original_roots = [Path(args.original_root), Path(args.fallback_original_root)]
    report_kind = "reexport_srgb_retry" if args.retry_failed_report else "reexport_srgb_audit"
    report_path = Path(args.report) if args.report else ROOT / "logs" / f"{report_kind}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    if args.retry_failed_report:
        return retry_failed_uploads(args, local_year_root, year, report_path)

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)

    rows: list[dict[str, str]] = []
    checked = needs_reexport = missing_original = reexported = uploaded = failed = 0

    ftp: FTP | None = None
    if args.upload:
        ftp = open_ftp()

    try:
        for web_path, rel_path in iter_web_images(local_year_root):
            if dated(web_path) < start or dated(web_path) > end:
                continue
            checked += 1
            web_profile = profile_name(web_path)
            needs = args.all or not is_srgb_profile(web_profile)
            if not needs:
                rows.append(
                    {
                        "status": "OK",
                        "profile": web_profile,
                        "original_profile": "",
                        "web_path": str(web_path),
                        "original_path": "",
                        "message": "",
                    }
                )
                continue

            original = find_original(rel_path, original_roots, year)
            if not original:
                missing_original += 1
                rows.append(
                    {
                        "status": "MISSING_ORIGINAL",
                        "profile": web_profile,
                        "original_profile": "",
                        "web_path": str(web_path),
                        "original_path": "",
                        "message": "No matching original found",
                    }
                )
                continue

            original_profile = profile_name(original)
            if args.only_original_non_srgb and is_srgb_profile(original_profile):
                rows.append(
                    {
                        "status": "SKIP_ORIGINAL_SRGB",
                        "profile": web_profile,
                        "original_profile": original_profile,
                        "web_path": str(web_path),
                        "original_path": str(original),
                        "message": "Skipped by --only-original-non-srgb",
                    }
                )
                continue

            needs_reexport += 1
            thumb_path = local_year_root / "thumbs" / rel_path
            desktop_path = desktop_root / rel_path
            status = "WOULD_REEXPORT"
            message = ""

            if args.apply:
                try:
                    ok = resize_and_watermark(
                        str(original),
                        str(web_path),
                        str(thumb_path),
                        str(desktop_path),
                        WATERMARK_TEXT,
                        str(FONT_PATH),
                    )
                    if not ok:
                        raise RuntimeError("resize_and_watermark returned False")
                    reexported += 1
                    status = "REEXPORTED"

                    if ftp is not None:
                        upload_pair(ftp, web_path, thumb_path, rel_path, year)
                        uploaded += 1
                        status = "REEXPORTED_UPLOADED"
                except Exception as exc:
                    failed += 1
                    status = "FAILED"
                    message = f"{type(exc).__name__}: {exc}"

            rows.append(
                {
                    "status": status,
                    "profile": web_profile,
                    "original_profile": original_profile,
                    "web_path": str(web_path),
                    "original_path": str(original),
                    "message": message,
                }
            )

            if args.limit and needs_reexport >= args.limit:
                break
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                pass

    with report_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["status", "profile", "original_profile", "web_path", "original_path", "message"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"checked={checked}")
    print(f"needs_reexport={needs_reexport}")
    print(f"missing_original={missing_original}")
    print(f"reexported={reexported}")
    print(f"uploaded={uploaded}")
    print(f"failed={failed}")
    print(f"report={report_path}")
    if not args.apply:
        print("DRY RUN ONLY. Add --apply to overwrite local files. Add --upload to overwrite online files too.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
