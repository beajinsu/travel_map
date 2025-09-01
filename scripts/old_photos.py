# exif_scan_old_photos.py
import os, csv, json, sys
from pathlib import Path
from datetime import datetime
from PIL import Image, ExifTags

# === 설정 ===
ROOT = Path(r"C:\Users\b_jin\OneDrive - KIF\4. backup_folder\old_photos")  # 스캔할 루트 폴더
OUT_DIR = Path(r"C:\Users\b_jin\My_Drive\github\travel_map\scripts")  # 결과 저장 위치(원하면 다른 경로로 변경)

# 스캔할 확장자(대소문자 구분 없음)
EXTS = {".jpg", ".jpeg", ".png"}  # 필요하면 ".png", ".heic" 등 추가

# === EXIF 유틸 ===
TAGS = {v: k for k, v in ExifTags.TAGS.items()}
GPSTAGS = ExifTags.GPSTAGS

def rational_to_float(x):
    """Pillow의 Rational 또는 (num, den) -> float"""
    try:
        return float(x[0]) / float(x[1])
    except Exception:
        try:
            return float(x)
        except Exception:
            return None

def dms_to_deg(dms, ref):
    """((d_num,d_den),(m_num,m_den),(s_num,s_den)), 'N/E/S/W' -> signed degree"""
    try:
        d = rational_to_float(dms[0])
        m = rational_to_float(dms[1])
        s = rational_to_float(dms[2])
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
        lat = dms_to_deg(gps_raw.get("GPSLatitude"), gps_raw.get("GPSLatitudeRef", "N"))
        lng = dms_to_deg(gps_raw.get("GPSLongitude"), gps_raw.get("GPSLongitudeRef", "E"))

    time_str = dt_original.strftime("%Y-%m-%d %H:%M:%S") if dt_original else None
    return lat, lng, time_str

def is_valid_coord(lat, lng):
    if lat is None or lng is None: return False
    if not (-90 <= lat <= 90 and -180 <= lng <= 180): return False
    if lat == 0.0 and lng == 0.0: return False
    return True

# === 실행 ===
def main():
    if not ROOT.exists():
        print(f"경로 없음: {ROOT}")
        sys.exit(1)

    with_location = []
    without_location = []

    csv_rows = []  # 보고서용

    total = 0
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXTS:
            total += 1
            lat, lng, tstr = extract_exif_basic(p)
            rel = p.relative_to(ROOT).as_posix()

            has_gps = is_valid_coord(lat, lng)
            has_time = tstr is not None

            # JSON(heat_data_gen과 호환되는 형태)
            if has_gps:
                with_location.append({
                    "file": rel,     # 파일명만 쓰려면 p.name
                    "lat": round(lat, 7),
                    "lng": round(lng, 7),
                    "time": tstr
                })
            else:
                without_location.append({"file": rel})

            # CSV 보고용
            csv_rows.append({
                "path": rel,
                "has_gps": "Y" if has_gps else "N",
                "lat": lat if has_gps else "",
                "lng": lng if has_gps else "",
                "has_time": "Y" if has_time else "N",
                "time": tstr or ""
            })

    # 중복 제거: (lat,lng,time) 기준
    seen = set()
    dedup_with = []
    for rec in with_location:
        key = (rec["lat"], rec["lng"], rec.get("time"))
        if key in seen: 
            continue
        seen.add(key)
        dedup_with.append(rec)

    # 결과 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "oldphotos_with.json").write_text(
        json.dumps(dedup_with, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "oldphotos_without.json").write_text(
        json.dumps(without_location, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # CSV 리포트
    csv_path = OUT_DIR / "oldphotos_exif_scan_report.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path","has_gps","lat","lng","has_time","time"])
        writer.writeheader()
        writer.writerows(csv_rows)

    print("=== 완료 ===")
    print(f"전체 파일: {total}")
    print(f"GPS 있는 사진: {len(dedup_with)}  | GPS 없는 사진: {len(without_location)}")
    print(f"- JSON: {OUT_DIR/'oldphotos_with.json'}")
    print(f"- JSON: {OUT_DIR/'oldphotos_without.json'}")
    print(f"- CSV : {csv_path}")

if __name__ == "__main__":
    main()