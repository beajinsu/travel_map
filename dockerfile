FROM python:3.10-slim

WORKDIR /app

# 필요한 경우만 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# static 파일만 복사
COPY . .

# 로컬서버 실행
CMD ["python", "-m", "http.server", "4000"]