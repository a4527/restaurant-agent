#!/bin/bash
# AgentCore 에이전트 배포
# 사전 조건: 01-kb 완료 (KB_ID 확인), Node.js 20+, npm
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# KB_ID 업데이트 필요 여부 체크
KB_ID_FILE="../01-kb/kb-id.txt"
if [ -f "$KB_ID_FILE" ]; then
  KB_ID=$(cat "$KB_ID_FILE")
  echo "KB_ID: $KB_ID"
  echo "tools.py의 KB_ID를 확인하세요: $KB_ID"
  sed -i "s/KB_ID = \".*\"/KB_ID = \"$KB_ID\"/" app/DiningConcierge/tools.py
  echo "✅ tools.py KB_ID 업데이트 완료"
fi

# CDK 의존성 설치
echo "=== CDK 의존성 설치 ==="
cd agentcore/cdk && npm ci && npm run build
cd "$SCRIPT_DIR"

# AgentCore CLI 설치
echo "=== AgentCore CLI 설치 ==="
npm install -g @aws/agentcore 2>/dev/null || true

# 배포
echo "=== AgentCore 배포 ==="
npx @aws/agentcore deploy --yes

echo ""
echo "=== 완료 ==="
echo "배포 후 Runtime ID 확인:"
echo "  npx @aws/agentcore status"
