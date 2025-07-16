# parse_takeout_filtered.py
import os, re, json
from pathlib import Path

# Json 파일을 저장할 폴더로 설정하세요.
os.chdir(r"C:\Users\jsbae\My_Drive\github\travel_map\scripts")
print("현재 작업 디렉토리:", os.getcwd())

# → 압축을 푼 Google Photos 최상위 폴더로 바꾸세요
ROOT = Path(r"C:\Users\jsbae\OneDrive - KIF\g_phto\Takeout\Google Photos")

# "Photos from 2015", "Photos from 2016" 등 연도별 폴더만 처리
YEAR_DIR_RE = re.compile(r"^Photos from (\d{4})$")

with_location = []
without_location = []

for child in ROOT.iterdir():
    if not child.is_dir(): continue
    if not YEAR_DIR_RE.match(child.name):  # 연도 폴더가 아니면 건너뜀
        continue

    print(f"▶ {child.name} 폴더 검사 중...")
    for js in child.rglob("*.json"):
        data = json.loads(js.read_text(encoding="utf-8"))
        geo = data.get("geoData") or {}
        lat = geo.get("latitude")
        lng = geo.get("longitude")
        if lat is not None and lng is not None:
            with_location.append({
                "file": js.name.replace(".json", ".jpg"),
                "lat":  lat,
                "lng":  lng,
                "time": data.get("photoTakenTime",{}).get("formatted")
            })
        else:
            without_location.append({
                "file": js.name.replace(".json", ".jpg")
            })

# 결과 저장
with open("takeout_with_location.json",   "w", encoding="utf-8") as f:
    json.dump(with_location,   f, ensure_ascii=False, indent=2)
with open("takeout_without_location.json","w", encoding="utf-8") as f:
    json.dump(without_location,f, ensure_ascii=False, indent=2)

print(f"\n완료! 위치 있는 사진: {len(with_location)}장")
print(f"위치 없는 사진: {len(without_location)}장")