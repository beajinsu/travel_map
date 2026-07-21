# heat_data_gen.py
import os
import json
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

print("현재 작업 디렉토리:", os.getcwd())
try:
    flight_periods, flight_counts = load_flight_periods()
except FlightSettingsError as exc:
    raise SystemExit(f"비행 설정 오류: {exc}") from exc

def parse_timestamp(timestamp_str):
    """다양한 형식의 타임스탬프를 파싱"""
    try:
        # 보이지 않는 특수 문자들 제거 (Google Takeout 형식)
        timestamp_str = timestamp_str.replace('\u202f', ' ')  # narrow no-break space
        timestamp_str = timestamp_str.replace('\u00a0', ' ')  # non-breaking space
        timestamp_str = timestamp_str.strip()
        
        # Unix timestamp (초 단위)
        if timestamp_str.isdigit():
            return datetime.fromtimestamp(int(timestamp_str))
        
        # Unix timestamp (밀리초 단위)
        if len(timestamp_str) == 13 and timestamp_str.isdigit():
            return datetime.fromtimestamp(int(timestamp_str) / 1000)
        
        # Google Takeout 형식 우선 처리: "May 1, 2025, 2:27:42 AM UTC"
        if ' UTC' in timestamp_str:
            # UTC 제거
            timestamp_str = timestamp_str.replace(' UTC', '').strip()
            # 파싱 시도
            try:
                return datetime.strptime(timestamp_str, "%b %d, %Y, %I:%M:%S %p")
            except ValueError:
                try:
                    return datetime.strptime(timestamp_str, "%B %d, %Y, %I:%M:%S %p")  # 전체 월 이름
                except ValueError:
                    pass
        
        # ISO 형식 (Google Takeout 처리 후)
        if 'T' in timestamp_str:
            try:
                return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                pass
        
        # 기타 일반적인 형식들
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%b %d, %Y, %I:%M:%S %p",  # Google Takeout 형식 (UTC 제거된 후)
            "%B %d, %Y, %I:%M:%S %p",  # 전체 월 이름
            "%m/%d/%Y %I:%M:%S %p",
            "%d/%m/%Y %H:%M:%S",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue
                
        # 파싱 실패 시 None 반환 (오류 메시지 제거)
        return None
        
    except Exception as e:
        # 오류 발생 시 None 반환
        return None

# 원본 위치 JSON 로드
try:
    with open('takeout_with_location.json', 'r', encoding='utf-8') as f:
        pts = json.load(f)
    print(f"📂 원본 데이터 로드 완료: {len(pts)}개 포인트")
except FileNotFoundError:
    print("❌ takeout_with_location.json 파일을 찾을 수 없습니다.")
    exit(1)
except json.JSONDecodeError:
    print("❌ JSON 파일 형식이 잘못되었습니다.")
    exit(1)

# 비행기 시간 파싱 (설정 검증)
print("\n🛫 설정된 비행기 탑승 시간:")
print(
    f"  수동 {flight_counts['manual']}개, "
    f"승인 후보 {flight_counts['approved_candidates']}개"
)
for i, flight in enumerate(flight_periods, 1):
    print(f"  {i}. {period_summary(flight)}")

# 데이터 필터링
heat_pts = []
heat_pts_by_year = {}  # 연도별 데이터 저장
flight_data = []  # 비행기 노선 데이터 별도 저장
flight_filtered_count = 0
invalid_time_count = 0

print("\n🔍 데이터 필터링 시작...")

for i, p in enumerate(pts):
    # 위치 정보 확인
    if 'lat' not in p or 'lng' not in p:
        continue
    
    # 시간 정보 확인 및 파싱
    photo_time = None
    for time_key in ['timestamp', 'time', 'date', 'taken_time', 'photo_taken_time']:
        if time_key in p and p[time_key]:
            photo_time = parse_timestamp(str(p[time_key]))
            break
    
    if not photo_time:
        invalid_time_count += 1
        # 시간 정보가 없으면 전체 데이터에만 포함
        lat = round(p['lat'], 2)
        lng = round(p['lng'], 2)
        heat_pts.append([lat, lng])
        continue
    
    # 비행기 탑승 시간 확인
    matched_flight = match_flight(photo_time, flight_periods)
    
    if matched_flight:
        flight_name = matched_flight["name"]
        flight_filtered_count += 1
        # 🛫 비행기 데이터 별도 저장
        flight_point = {
            "lat": round(p['lat'], 4),  # 비행기는 더 정밀하게
            "lng": round(p['lng'], 4),
            "time": photo_time.isoformat(),
            "flight_name": flight_name,
            "altitude": p.get('altitude', None)  # 고도 정보도 있으면 저장
        }
        flight_data.append(flight_point)
        
        if i < 10:  # 처음 몇 개만 출력
            print(f"  🛫 비행기 데이터 수집: {photo_time} ({flight_name})")
        continue
    
    # 정상 데이터 추가
    lat = round(p['lat'], 2)   # 소수점 둘째 자리까지
    lng = round(p['lng'], 2)
    heat_pts.append([lat, lng])
    
    # 연도별 데이터 분류
    year = str(photo_time.year)
    if year not in heat_pts_by_year:
        heat_pts_by_year[year] = []
    heat_pts_by_year[year].append([lat, lng])

# 중복 제거 (도시 수준)
original_count = len(heat_pts)
heat_pts = [[lat, lng] for lat, lng in {(lat, lng) for lat, lng in heat_pts}]
deduplicated_count = original_count - len(heat_pts)

# 연도별 데이터도 중복 제거
for year in heat_pts_by_year:
    heat_pts_by_year[year] = [[lat, lng] for lat, lng in {(lat, lng) for lat, lng in heat_pts_by_year[year]}]

# 전체 데이터와 연도별 데이터 통합
heat_data_combined = {
    "all": heat_pts,
    **heat_pts_by_year  # 연도별 데이터 추가
}

# 연도별 통계 출력
available_years = sorted([year for year in heat_pts_by_year.keys() if year.isdigit()])
if available_years:
    print(f"\n📅 연도별 데이터:")
    for year in available_years:
        count = len(heat_pts_by_year[year])
        print(f"  • {year}년: {count}개 지점")

# 비행기 데이터 시간순 정렬 및 노선별 그룹화
flight_routes = {}
for flight_point in flight_data:
    flight_name = flight_point["flight_name"]
    if flight_name not in flight_routes:
        flight_routes[flight_name] = []
    flight_routes[flight_name].append(flight_point)

# 각 노선별로 시간순 정렬
for flight_name in flight_routes:
    flight_routes[flight_name].sort(key=lambda x: x["time"])

print("\n📊 필터링 결과:")
print(f"  • 원본 포인트: {len(pts)}개")
print(f"  • 비행기 시간 제외: {flight_filtered_count}개")
print(f"  • 시간 정보 없음: {invalid_time_count}개")
print(f"  • 중복 제거: {deduplicated_count}개")
print(f"  • 최종 히트맵: {len(heat_pts)}개 도시 단위 좌표")
print(f"  • 수집된 연도: {', '.join(available_years) if available_years else '없음'}")
print(f"  • 비행기 노선: {len(flight_routes)}개 노선, {len(flight_data)}개 포인트")

# 🛫 비행기 노선별 요약 출력
if flight_routes:
    print("\n✈️ 수집된 비행기 노선:")
    for flight_name, points in flight_routes.items():
        start_time = points[0]["time"][:16]  # YYYY-MM-DD HH:MM
        end_time = points[-1]["time"][:16]
        print(f"  • {flight_name}: {len(points)}개 포인트 ({start_time} ~ {end_time})")

# JS용 파일들 저장
try:
    # 1. 연도별 히트맵 데이터 (전체 + 연도별) - 연도별 구분
    with open('heat_data.js', 'w', encoding='utf-8') as f:
        f.write('var heatDataByYear = {\n')
        
        # 각 연도별로 한 줄씩
        for i, (year, data) in enumerate(heat_data_combined.items()):
            comma = ',' if i < len(heat_data_combined) - 1 else ''
            compact_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            f.write(f'  "{year}": {compact_data}{comma}\n')
        
        f.write('};')
    print("\n✅ heat_data.js 생성 완료!")
    
    # 2. 호환성을 위한 기존 형태 데이터도 생성
    with open('heat_data_legacy.js', 'w', encoding='utf-8') as f:
        f.write('var heatData = ' + json.dumps(heat_pts, ensure_ascii=False) + ';')
    print("✅ heat_data_legacy.js 생성 완료!")
    
    # 3. 비행기 노선 데이터 (시간순 정렬된 포인트들)
    if flight_data:
        with open('flight_routes.js', 'w', encoding='utf-8') as f:
            f.write('var flightRoutes = ' + json.dumps(flight_routes, ensure_ascii=False, separators=(',', ':')) + ';')
        print("✅ flight_routes.js 생성 완료!")
        
        # 4. 비행기 경로를 라인으로 표시할 수 있는 형태로도 저장
        flight_lines = []
        for flight_name, points in flight_routes.items():
            if len(points) >= 2:  # 최소 2개 포인트가 있어야 라인
                line_coords = [[p["lat"], p["lng"]] for p in points]
                flight_lines.append({
                    "name": flight_name,
                    "coordinates": line_coords,
                    "start_time": points[0]["time"],
                    "end_time": points[-1]["time"],
                    "points_count": len(points)
                })
        
        with open('flight_lines.js', 'w', encoding='utf-8') as f:
            f.write('var flightLines = ' + json.dumps(flight_lines, ensure_ascii=False, separators=(',', ':')) + ';')
        print("✅ flight_lines.js 생성 완료!")
    
    # 샘플 데이터 미리보기 (처음 5개)
    if heat_pts:
        print("\n🔍 전체 히트맵 샘플 데이터:")
        for i, point in enumerate(heat_pts[:5]):
            print(f"  {i+1}. [{point[0]}, {point[1]}]")
        if len(heat_pts) > 5:
            print(f"  ... 외 {len(heat_pts)-5}개")
    
    # 연도별 샘플 미리보기
    if available_years:
        print("\n📅 연도별 샘플 데이터:")
        for year in available_years[:3]:  # 처음 3개 연도만
            year_data = heat_pts_by_year[year]
            print(f"  {year}년: {len(year_data)}개 지점")
            if year_data:
                print(f"    예시: [{year_data[0][0]}, {year_data[0][1]}]")
    
    # 비행기 노선 샘플
    if flight_routes:
        print("\n🛫 비행기 노선 샘플:")
        for flight_name, points in list(flight_routes.items())[:2]:
            print(f"  {flight_name}: {points[0]['lat']:.4f}, {points[0]['lng']:.4f} → {points[-1]['lat']:.4f}, {points[-1]['lng']:.4f}")
            
except Exception as e:
    print("❌ 파일 저장 오류: {e}")

print("\n🎉 처리 완료!")
print("📁 생성된 파일:")
print("  • heat_data.js - 연도별 히트맵 데이터")
print("  • heat_data_legacy.js - 기존 호환 데이터")
print("  • flight_routes.js - 비행기 노선별 포인트")
print("  • flight_lines.js - 비행기 경로 라인")
print("💡 이제 연도별 히트맵 표시가 가능합니다!")
