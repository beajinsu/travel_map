# ai_landmark_scan_skip_v2_fixed.py
import os, io, csv, json, time
from pathlib import Path
from datetime import datetime
from PIL import Image, ExifTags
from google.cloud import vision


# ====== 설정 ======
ROOT = Path(r"C:\Users\b_jin\OneDrive - KIF\4. backup_folder\old_photos")
OUT_DIR = ROOT
SKIP_FOLDER = "외장하드 백업"  # 이 폴더는 제외
EXTS = {".jpg", ".jpeg", ".png"}  # 필요한 확장자만
MAX_QPS = 3
SLEEP_BETWEEN = 1.0 / MAX_QPS

# 서비스 계정 키 경로 - 환경변수로 설정
CRED_PATH = r"C:\Users\b_jin\OneDrive - KIF\4. backup_folder\old_photos\photo-geo-ai-a378cd1f19fb.json"
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = CRED_PATH
client = vision.ImageAnnotatorClient()


# ====== EXIF 시간 추출 ======
def get_exif_time_str(path: Path):
    try:
        with Image.open(path) as im:
            exif = im._getexif() or {}
    except Exception:
        return None
    for tag_id, value in exif.items():
        tag = ExifTags.TAGS.get(tag_id, tag_id)
        if tag in ("DateTimeOriginal", "DateTime"):
            try:
                dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
    return None

# ====== Vision API 호출 ======
def detect_landmark_bytes(content: bytes):
    try:
        image = vision.Image(content=content)
        resp = client.landmark_detection(image=image, max_results=3)
        if resp.error.message:
            raise RuntimeError(resp.error.message)
        return resp
    except Exception as e:
        print(f"Vision API 에러: {type(e).__name__}: {e}")
        raise

def pick_best_landmark(annotations):
    best = None
    for ann in annotations:
        desc = ann.description
        score = getattr(ann, "score", 0.0)
        if ann.locations:
            latlng = ann.locations[0].lat_lng
            lat, lng = latlng.latitude, latlng.longitude
            if best is None or score > best[1]:
                best = (desc, float(score), float(lat), float(lng))
    return best

# ====== 메인 ======
def main():
    with_loc, no_landmark, rows = [], [], []
    total = 0

    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in EXTS:
            continue

        # 상위 경로에 "외장하드 백업" 포함 시 스킵
        if any(part == SKIP_FOLDER for part in p.parts):
            continue

        total += 1
        rel = p.relative_to(ROOT).as_posix()

        print(f"[{total}] 처리 중: {rel}")

        try:
            content = p.read_bytes()
        except Exception as e:
            print(f"[SKIP] 읽기 실패: {p} / {e}")
            continue

        try:
            resp = detect_landmark_bytes(content)
        except Exception as e:
            print(f"[ERR] Vision 호출 실패: {p} / {e}")
            no_landmark.append({"file": rel})
            time.sleep(SLEEP_BETWEEN)  # 실패해도 rate limiting
            continue

        anns = resp.landmark_annotations
        best = pick_best_landmark(anns)
        time_str = get_exif_time_str(p)

        if best:
            desc, score, lat, lng = best
            print(f"  -> 랜드마크 발견: {desc} (점수: {score:.3f})")
            with_loc.append({
                "file": rel,
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "time": time_str
            })
            rows.append({
                "path": rel,
                "landmark": desc,
                "score": f"{score:.4f}",
                "lat": lat,
                "lng": lng,
                "time": time_str or ""
            })
        else:
            print(f"  -> 랜드마크 없음")
            no_landmark.append({"file": rel})
            rows.append({
                "path": rel,
                "landmark": "",
                "score": "",
                "lat": "",
                "lng": "",
                "time": time_str or ""
            })

        time.sleep(SLEEP_BETWEEN)

    # 중복 제거
    seen, dedup = set(), []
    for rec in with_loc:
        key = (rec["lat"], rec["lng"], rec.get("time"))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(rec)

    # 저장
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "oldphotos_ai_with.json").write_text(
        json.dumps(dedup, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "oldphotos_ai_nolandmark.json").write_text(
        json.dumps(no_landmark, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with open(OUT_DIR / "oldphotos_ai_landmarks.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path","landmark","score","lat","lng","time"])
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== 완료 ===")
    print(f"총 처리 파일: {total}")
    print(f"랜드마크 인식됨: {len(dedup)} | 미검출: {len(no_landmark)}")
    print(f"- JSON 저장: {OUT_DIR/'oldphotos_ai_with.json'}")
    print(f"- JSON 저장: {OUT_DIR/'oldphotos_ai_nolandmark.json'}")
    print(f"- CSV 저장 : {OUT_DIR/'oldphotos_ai_landmarks.csv'}")

if __name__ == "__main__":