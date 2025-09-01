# merge_old_photos.py - old_photos_with.json을 heat_data.js에 병합
import json
import re
import shutil
import os
from datetime import datetime

print("데이터 병합 시작...")

# 1. 기존 heat_data.js 데이터 로드
try:
    with open('heat_data.js', 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r'var heatDataByYear = ({.*?});', content, re.DOTALL)
    existing_heat_data = json.loads(match.group(1)) if match else {}
    print(f"기존 heat_data.js 로드: {len(existing_heat_data)}개 연도")
except:
    existing_heat_data = {}
    print("기존 heat_data.js 없음. 새로 생성")

# 2. old_photos_with.json 로드
with open('old_photos_with.json', 'r', encoding='utf-8') as f:
    old_photos = json.load(f)
print(f"old_photos_with.json 로드: {len(old_photos)}개 사진")

# 3. 새 데이터 변환
all_coords = []
by_year = {}

for photo in old_photos:
    if not photo.get('lat') or not photo.get('lng'):
        continue
    
    # 좌표 반올림 (기존과 동일)
    lat = round(photo['lat'], 2)
    lng = round(photo['lng'], 2)
    coord = [lat, lng]
    all_coords.append(coord)
    
    # 연도별 분류
    if photo.get('time'):
        year = photo['time'][:4]  # "2014-01-15 12:53:04" -> "2014"
        if year not in by_year:
            by_year[year] = []
        by_year[year].append(coord)

print(f"변환 완료: {len(all_coords)}개 좌표, {len(by_year)}개 연도")

# 4. 중복 제거
def remove_dupes(coords):
    return list({(c[0], c[1]): c for c in coords}.values())

# 5. 기존 데이터와 병합
merged = {}
merged['all'] = remove_dupes(existing_heat_data.get('all', []) + all_coords)

all_years = set(existing_heat_data.keys()) | set(by_year.keys())
all_years.discard('all')

for year in all_years:
    existing = existing_heat_data.get(year, [])
    new = by_year.get(year, [])
    merged[year] = remove_dupes(existing + new)

# 6. 통계 출력
print(f"병합 결과:")
print(f"  전체: {len(existing_heat_data.get('all', []))} + {len(all_coords)} = {len(merged['all'])}개")
for year in sorted([y for y in merged.keys() if y != 'all']):
    old_count = len(existing_heat_data.get(year, []))
    new_count = len(by_year.get(year, []))
    print(f"  {year}년: {old_count} + {new_count} = {len(merged[year])}개")

# 7. 파일 생성
if os.path.exists('heat_data.js'):
    shutil.copy2('heat_data.js', 'heat_data_backup.js')
    print("기존 파일 백업 완료")

with open('heat_data.js', 'w', encoding='utf-8') as f:
    f.write('var heatDataByYear = {\n')
    items = sorted(merged.items(), key=lambda x: ('0' if x[0] == 'all' else x[0]))
    for i, (year, data) in enumerate(items):
        comma = ',' if i < len(items) - 1 else ''
        f.write(f'  "{year}": {json.dumps(data, separators=(",", ":"))}{comma}\n')
    f.write('};')

print("heat_data.js 업데이트 완료!")