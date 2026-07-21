
# new_photos_to_heat.py
# 목적:
#  - newphotos_with.json(누적)을 heat_data.js(연도별 구조)에 병합
#  - heat_data_gen.py와 동일한 "비행기 탑승시간" 제거 로직 적용 (버퍼 포함)
#  - 증분 실행에 친화적(기존 heat_data.js 유지 + 좌표 단위 중복 제거)

import json, re, shutil, os
from datetime import datetime, timedelta

# 작업 디렉토리(heat_data.js와 JSON들이 있는 곳)로 변경
os.chdir(r"C:\Users\jsbae\My_Drive\github\travel_map\scripts")
print("데이터 병합 시작...")

# =============================================================================
# 🛫 비행기 탑승 시간 설정 (heat_data_gen.py 포맷과 동일하게 유지)
# =============================================================================
flight_periods = [
    # 예시 (필요에 맞게 수정/추가)
    {"name": "뉴욕여행 출발", 
     "start": "2025-09-28 10:00:00",
     "end": "2025-09-28 20:00:00"
    },
    {"name": "뉴욕여행 도착",
     "start": "2025-10-08 12:00:00",
     "end": "2025-10-09 18:00:00"
     },
    # 필요한 만큼 더 추가하세요
    # {
    #     "name": "설명",
    #     "start": "YYYY-MM-DD HH:MM:SS", # 출발 시간
    #     "end": "YYYY-MM-DD HH:MM:SS"    # 도착 시간
    # },
]

BUFFER = timedelta(hours=6)  # 시간대 혼동 및 전후 버퍼 제거

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

def is_during_flight(photo_time, periods):
    if not photo_time:
        return False, None
    for f in periods:
        try:
            start = datetime.strptime(f["start"], "%Y-%m-%d %H:%M:%S") - BUFFER
            end   = datetime.strptime(f["end"],   "%Y-%m-%d %H:%M:%S") + BUFFER
        except Exception:
            continue
        if start <= photo_time <= end:
            return True, f["name"]
    return False, None

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

flight_filtered = 0
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
    is_f, _ = is_during_flight(dt, flight_periods)
    if is_f:
        flight_filtered += 1
        continue

    # 전체/연도 분배
    all_coords.append([lat_r, lng_r])
    if dt:
        year = str(dt.year)
        by_year.setdefault(year, []).append([lat_r, lng_r])

print(f"변환: 전체 {len(all_coords)}개 / 연도 {len(by_year)}개, "
      f"비행기제외 {flight_filtered}개, 시간파싱실패 {invalid_time}개")

# 4) 중복 제거 helper
def dedupe(coords):
    return list({(a,b): [a,b] for a,b in coords}.values())

# 5) 기존 데이터와 병합
merged = {}
merged['all'] = dedupe(existing.get('all', []) + all_coords)

all_years = set(existing.keys()) | set(by_year.keys())
all_years.discard('all')
for y in all_years:
    merged[y] = dedupe(existing.get(y, []) + by_year.get(y, []))

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
print(f"  • all: {len(merged['all'])}개 좌표")
for y in sorted([k for k in merged.keys() if k!='all']):
    print(f"  • {y}: {len(merged[y])}개")
