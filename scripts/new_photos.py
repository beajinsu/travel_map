
# new_photos.py
# 스캔 대상: "C:\Users\jsbae\OneDrive - KIF\그림\카메라 앨범" 하위(연도별 폴더)
# 기능:
#  - EXIF에서 GPS/촬영시각을 추출
#  - 결과를 newphotos_with.json / newphotos_without.json / CSV 보고서로 저장
#  - "증분 처리" 지원: index 파일에 저장된 mtime/size를 기준으로 신규/변경 파일만 처리

import os, csv, json, sys, time
from pathlib import Path
from datetime import datetime
from PIL import Image, ExifTags

# === 설정 ===
ROOT = Path(r"C:\Users\jsbae\OneDrive - KIF\그림\카메라 앨범")  # 스캔할 루트 폴더 (연도별 하위 폴더 포함)
OUT_DIR = Path(r"C:\Users\jsbae\My_Drive\github\travel_map\scripts")  # 결과 저장 위치
INDEX_PATH = OUT_DIR / "newphotos_index.json"  # 증분처리 인덱스
WITH_JSON = OUT_DIR / "newphotos_with.json"
WITHOUT_JSON = OUT_DIR / "newphotos_without.json"
CSV_PATH = OUT_DIR / "newphotos_exif_scan_report.csv"

# 진행 상황을 몇 개마다 요약해서 보여줄지 설정
PROGRESS_SUMMARY_EVERY = 25

# 스캔할 확장자
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff"}

# === EXIF 유틸 ===
GPSTAGS = ExifTags.GPSTAGS

def _rational_to_float(x):
    try:
        # Pillow의 IFDRational
        return float(getattr(x, 'numerator', x[0])) / float(getattr(x, 'denominator', x[1]))
    except Exception:
        try:
            return float(x)
        except Exception:
            return None

def _dms_to_deg(dms, ref):
    """((d_num,d_den),(m_num,m_den),(s_num,s_den)), 'N/E/S/W' -> signed degree"""
    try:
        d = _rational_to_float(dms[0])
        m = _rational_to_float(dms[1])
        s = _rational_to_float(dms[2])
        if None in (d, m, s):
            return None
        deg = d + (m / 60.0) + (s / 3600.0)
        if ref in ("S", "W"):
            deg = -deg
        return deg
    except Exception:
        return None

def extract_exif_basic(img_path: Path):
    """
    이미지에서 (lat, lng, time_str) 추출
    time_str: 'YYYY-MM-DD HH:MM:SS' 또는 None
    """
    try:
        with Image.open(img_path) as im:
            exif = im._getexif() or {}
    except Exception:
        return None, None, None  # 이미지 열기 실패 또는 EXIF 없음

    gps_raw = {}
    dt_original = None

    for tag_id, value in exif.items():
        tag = ExifTags.TAGS.get(tag_id, tag_id)
        if tag == "GPSInfo":
            for k, v in value.items():
                gps_tag = GPSTAGS.get(k, k)
                gps_raw[gps_tag] = v
        elif tag in ("DateTimeOriginal", "DateTime"):
            # 예: "2019:01:23 18:30:22"
            try:
                dt_original = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
            except Exception:
                dt_original = None

    lat = lng = None
    if gps_raw:
        lat = _dms_to_deg(gps_raw.get("GPSLatitude"), gps_raw.get("GPSLatitudeRef", "N"))
        lng = _dms_to_deg(gps_raw.get("GPSLongitude"), gps_raw.get("GPSLongitudeRef", "E"))

    time_str = dt_original.strftime("%Y-%m-%d %H:%M:%S") if dt_original else None
    return lat, lng, time_str

def is_valid_coord(lat, lng):
    if lat is None or lng is None: return False
    if not (-90 <= lat <= 90 and -180 <= lng <= 180): return False
    if lat == 0.0 and lng == 0.0: return False
    return True

# === 증분처리 인덱스 ===
def load_index():
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_index(index_data):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")

def file_sig(p: Path):
    """증분 판별용 간단 시그니처: (파일 크기, mtime)"""
    try:
        stat = p.stat()
        return {"size": stat.st_size, "mtime": stat.st_mtime}
    except FileNotFoundError:
        return None

def need_process(p: Path, index):
    sig = file_sig(p)
    if sig is None:
        return False
    key = p.as_posix().lower()
    old = index.get(key)
    return (old != sig)

def main():
    if not ROOT.exists():
        print(f"경로 없음: {ROOT}")
        sys.exit(1)

    print("사진 파일 목록을 검색하는 중...", flush=True)
    index = load_index()
    with_location, without_location = [], []
    csv_rows = []
    started_at = time.perf_counter()

    photo_files = [
        p for p in ROOT.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTS
    ]
    pending_files = [p for p in photo_files if need_process(p, index)]
    total = len(photo_files)
    pending_total = len(pending_files)

    print(f"전체 사진: {total}개", flush=True)
    print(f"이번 실행 대상: {pending_total}개", flush=True)

    if pending_total == 0:
        print("새로 처리할 사진이 없습니다.", flush=True)

    touched = 0
    try:
        for touched, p in enumerate(pending_files, start=1):
            rel = p.relative_to(ROOT).as_posix()
            percent = touched / pending_total * 100
            print(
                f"[{touched:>4}/{pending_total} | {percent:6.2f}%] 처리 중: {rel}",
                flush=True,
            )

            lat, lng, tstr = extract_exif_basic(p)

            has_gps = is_valid_coord(lat, lng)
            has_time = tstr is not None

            if has_gps:
                with_location.append({
                    "file": rel,
                    "lat": round(lat, 7),
                    "lng": round(lng, 7),
                    "time": tstr
                })
            else:
                without_location.append({"file": rel})

            csv_rows.append({
                "path": rel,
                "has_gps": "Y" if has_gps else "N",
                "lat": lat if has_gps else "",
                "lng": lng if has_gps else "",
                "has_time": "Y" if has_time else "N",
                "time": tstr or ""
            })

            # 인덱스 업데이트
            key = p.as_posix().lower()
            index[key] = file_sig(p)

            if touched % PROGRESS_SUMMARY_EVERY == 0 or touched == pending_total:
                elapsed = time.perf_counter() - started_at
                print(
                    "  -> 중간 집계: "
                    f"GPS {len(with_location)}개 / "
                    f"무GPS {len(without_location)}개 / "
                    f"경과 {elapsed:.1f}초",
                    flush=True,
                )
    except KeyboardInterrupt:
        elapsed = time.perf_counter() - started_at
        print("\n=== 사용자가 작업을 중단했습니다 ===", flush=True)
        print(
            f"중단 시점: {touched}/{pending_total}개, 경과 {elapsed:.1f}초",
            flush=True,
        )
        print("이번 실행 결과는 아직 파일에 저장되지 않았습니다.", flush=True)
        raise

    # 기존 JSON이 있다면 이어붙이기 (중복 제거)
    existed_with = []
    existed_without = []
    if WITH_JSON.exists():
        try:
            existed_with = json.loads(WITH_JSON.read_text(encoding="utf-8"))
        except Exception:
            existed_with = []
    if WITHOUT_JSON.exists():
        try:
            existed_without = json.loads(WITHOUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            existed_without = []

    # 병합 + 중복 제거: (file, lat, lng, time) 기준
    def unique_by_key(items, keyfunc):
        seen = set()
        out = []
        for it in items:
            k = keyfunc(it)
            if k in seen: 
                continue
            seen.add(k)
            out.append(it)
        return out

    merged_with = unique_by_key(existed_with + with_location,
                                lambda r: (r.get("file"), r.get("lat"), r.get("lng"), r.get("time")))
    merged_without = unique_by_key(existed_without + without_location,
                                   lambda r: r.get("file"))

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WITH_JSON.write_text(json.dumps(merged_with, ensure_ascii=False, indent=2), encoding="utf-8")
    WITHOUT_JSON.write_text(json.dumps(merged_without, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV는 새 처리분만 추가 기록 (필요 시 전체 재생성으로 바꿔도 됨)
    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path","has_gps","lat","lng","has_time","time"])
        if write_header:
            writer.writeheader()
        writer.writerows(csv_rows)

    # 인덱스 저장
    save_index(index)

    print("=== 완료 ===")
    print(f"전체 파일(탐색): {total}")
    print(f"이번 실행 처리: {touched}")
    print(f"누적 GPS 사진: {len(merged_with)}  | 누적 무GPS 사진: {len(merged_without)}")
    print(f"- JSON: {WITH_JSON}")
    print(f"- JSON: {WITHOUT_JSON}")
    print(f"- CSV : {CSV_PATH}")
    print(f"- INDEX : {INDEX_PATH}")

if __name__ == "__main__":
    main()
