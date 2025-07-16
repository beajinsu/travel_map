# heat_data_gen.py
import os
import json

# locatin 정보가 있는 Json 파일 위치를 넣으세요. 같은 폴더에 heat_map이 만들어 집니다.
os.chdir(r"C:\Users\jsbae\My_Drive\github\travel_map\scripts")
print("현재 작업 디렉토리:", os.getcwd())

# 원본 위치 JSON
pts = json.load(open('takeout_with_location.json', encoding='utf-8'))

heat_pts = []
for p in pts:
    lat = round(p['lat'], 2)   # 소수점 둘째 자리까지
    lng = round(p['lng'], 2)
    heat_pts.append([lat, lng])

# 중복 제거 (도시 수준)
heat_pts = list({(lat,lng) for lat,lng in heat_pts})

# JS용 파일로 덤프
with open('heat_data.js','w',encoding='utf-8') as f:
    f.write('var heatData = ' + json.dumps(heat_pts, ensure_ascii=False) + ';')
print(f"heat_data.js 생성: {len(heat_pts)}개 도시 단위 좌표")