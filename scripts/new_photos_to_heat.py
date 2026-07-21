
# new_photos_to_heat.py
# 목적:
#  - newphotos_with.json(누적)을 heat_data.js(연도별 구조)에 병합
#  - heat_data_gen.py와 동일한 "비행기 탑승시간" 제거 로직 적용 (버퍼 포함)
#  - 증분 실행에 친화적(기존 heat_data.js 유지 + 좌표 단위 중복 제거)

import json, re, shutil, os
from datetime import datetime
from pathlib import Path

from flight_settings import (
    FlightSettingsError,
    load_flight_periods,
    match_flight,
    period_summary,
)

# 스크립트 위치를 기준으로 입력/출력 파일을 찾는다.
SCRIPT_DIR = Path(__file__).resolve().parent
os.chdir(SCRIPT_DIR)
print("데이터 병합 시작...")

try:
    flight_periods, flight_counts = load_flight_periods()
except FlightSettingsError as exc:
    raise SystemExit(f"비행 설정 오류: {exc}") from exc

print(
    "비행 제외 설정: "
    f"수동 {flight_counts['manual']}개, "
    f"승인 후보 {flight_counts['approved_candidates']}개"
)
for period in flight_periods:
    print(f"  - {period_summary(period)}")

def parse_timestamp(ts):
    """열린 형식 파서 (heat_data_gen.py와 유사)"""
    try:
        s = str(ts).strip().replace('\u202f',' ').replace('\u00a0',' ')
        if s.isdigit():
            if len(s) == 13:
                return datetime.fromtimestamp(int(s)/1000)
            return datetime.fromtimestamp(int(s))
        if ' UTC' in s:
            s2 = s.replace(' UTC','').strip()
            for fmt in ("%b %d, %Y, %I:%M:%S %p", "%B %d, %Y, %I:%M:%S %p"):
                try: return datetime.strptime(s2, fmt)
                except ValueError: pass
        if 'T' in s:
            try: return datetime.fromisoformat(s.replace('Z', '+00:00'))
            except ValueError: pass
        for fmt in ("%Y-%m-%d %H:%M:%S","%Y/%m/%d %H:%M:%S","%Y-%m-%d","%Y/%m/%d",
                    "%b %d, %Y, %I:%M:%S %p","%B %d, %Y, %I:%M:%S %p",
                    "%m/%d/%Y %I:%M:%S %p","%d/%m/%Y %H:%M:%S"):
            try: return datetime.strptime(s, fmt)
            except ValueError: continue
        return None
    except Exception:
        return None

# 1) heat_data.js (기존) 읽기
try:
    with open('heat_data.js','r',encoding='utf-8') as f:
        content = f.read()
    m = re.search(r'var heatDataByYear = ({.*?});', content, re.DOTALL)
    existing = json.loads(m.group(1)) if m else {}
    print(f"기존 heat_data.js 로드: {len(existing)}개 연도")
except FileNotFoundError:
    existing = {}
    print("기존 heat_data.js 없음 → 새로 생성 예정")

# 2) newphotos_with.json 읽기
with open('newphotos_with.json','r',encoding='utf-8') as f:
    photos = json.load(f)
print(f"newphotos_with.json 로드: {len(photos)}개 사진")

# 3) 변환(+비행기시간 제거)
all_coords = []
by_year = {}
excluded_all_coords = []
excluded_by_year = {}

flight_filtered = 0
flight_filtered_by_name = {}
invalid_time = 0

for rec in photos:
    lat = rec.get('lat')
    lng = rec.get('lng')
    if lat is None or lng is None:
        continue

    # 좌표 반올림(도시단위)
    lat_r = round(lat, 2)
    lng_r = round(lng, 2)

    ts = rec.get('time')
    dt = parse_timestamp(ts) if ts else None
    if dt is None and ts:
        invalid_time += 1

    # 비행기 제외
    matched_flight = match_flight(dt, flight_periods)
    if matched_flight:
        flight_filtered += 1
        flight_name = matched_flight["name"]
        flight_filtered_by_name[flight_name] = (
            flight_filtered_by_name.get(flight_name, 0) + 1
        )
        excluded_all_coords.append([lat_r, lng_r])
        if dt:
            year = str(dt.year)
            excluded_by_year.setdefault(year, []).append([lat_r, lng_r])
        continue

    # 전체/연도 분배
    all_coords.append([lat_r, lng_r])
    if dt:
        year = str(dt.year)
        by_year.setdefault(year, []).append([lat_r, lng_r])

print(f"변환: 전체 {len(all_coords)}개 / 연도 {len(by_year)}개, "
      f"비행기제외 {flight_filtered}개, 시간파싱실패 {invalid_time}개")
for flight_name, count in sorted(flight_filtered_by_name.items()):
    print(f"  - 제외 사진 {flight_name}: {count}개")

# 4) 중복 제거 helper
def dedupe(coords):
    return list({(a,b): [a,b] for a,b in coords}.values())

def remove_excluded(coords, excluded_coords):
    excluded = {(a, b) for a, b in excluded_coords}
    if not excluded:
        return coords[:], 0
    kept = [[a, b] for a, b in coords if (a, b) not in excluded]
    return kept, len(coords) - len(kept)

# 5) 기존 데이터에서도 제외 좌표를 제거한 뒤 정상 좌표와 병합
merged = {}
all_years = set(existing.keys()) | set(by_year.keys()) | set(excluded_by_year.keys())
all_years.discard('all')
removed_existing_by_year = {}
for y in all_years:
    clean_existing_year, removed_count = remove_excluded(
        existing.get(y, []), excluded_by_year.get(y, [])
    )
    removed_existing_by_year[y] = removed_count
    merged[y] = dedupe(clean_existing_year + by_year.get(y, []))

# 전체보기에서 제외 좌표를 지우되, 다른 연도에 정상적으로 남은 동일 좌표는 보호한다.
remaining_year_coords = {
    (a, b)
    for year, coords in merged.items()
    if year != 'all'
    for a, b in coords
}
protected_all_coords = [
    [a, b]
    for a, b in excluded_all_coords
    if (a, b) in remaining_year_coords
]
clean_existing_all, removed_existing_all = remove_excluded(
    existing.get('all', []), excluded_all_coords
)
merged['all'] = dedupe(
    clean_existing_all + all_coords + protected_all_coords
)

print(f"기존 지도에서 제외 좌표 제거: all {removed_existing_all}개")
for y in sorted(y for y, count in removed_existing_by_year.items() if count):
    print(f"  - {y}: {removed_existing_by_year[y]}개")
protected_count = len(dedupe(protected_all_coords))
if protected_count:
    print(f"전체보기에서 타 연도 정상 좌표 보호: {protected_count}개")

# 6) 백업 및 쓰기
if os.path.exists('heat_data.js'):
    shutil.copy2('heat_data.js','heat_data_backup.js')
    print("기존 heat_data.js 백업 완료 → heat_data_backup.js")

with open('heat_data.js','w',encoding='utf-8') as f:
    f.write('var heatDataByYear = {\n')
    items = sorted(merged.items(), key=lambda x: ('0' if x[0]=='all' else x[0]))
    for i, (year, data) in enumerate(items):
        comma = ',' if i < len(items)-1 else ''
        f.write(f'  "{year}": {json.dumps(data, ensure_ascii=False, separators=(",", ":"))}{comma}\n')
    f.write('};')

print("[완료] heat_data.js 업데이트 완료")
print(f"  - all: {len(merged['all'])}개 좌표")
for y in sorted([k for k in merged.keys() if k!='all']):
    print(f"  - {y}: {len(merged[y])}개")
