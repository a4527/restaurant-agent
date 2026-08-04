#!/bin/bash
# Streamlit 앱 실행
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 가상환경 설정
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -r requirements.txt

# app.py에서 RUNTIME_ID와 KB_ID를 확인/수정하세요
echo "=== Streamlit 실행 ==="
echo "브라우저: http://localhost:8501"
streamlit run app.py --server.port 8501
