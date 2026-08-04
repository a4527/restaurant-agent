#!/bin/bash
# ============================================================
# DiningConcierge 전체 재현 스크립트
# 새 AWS 계정에서 처음부터 끝까지 세팅
# 사용법: ./setup.sh [--all | --infra | --kb | --agent | --sam | --frontend | --pipeline]
#   인자 없으면 infra + kb + agent + app 까지 실행 (기본)
#   --all: 전체 (SAM + Frontend + Pipeline 포함)
# ============================================================
set -e

REGION=${AWS_DEFAULT_REGION:-us-west-2}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo " DiningConcierge 전체 재현 스크립트"
echo " Account: $ACCOUNT_ID | Region: $REGION"
echo "============================================================"
echo ""

cd "$SCRIPT_DIR"

# ── 인자 파싱 ──
RUN_INFRA=false; RUN_KB=false; RUN_AGENT=false; RUN_APP=false
RUN_SAM=false; RUN_FRONTEND=false; RUN_PIPELINE=false

if [ $# -eq 0 ]; then
  RUN_INFRA=true; RUN_KB=true; RUN_AGENT=true; RUN_APP=true
else
  for arg in "$@"; do
    case $arg in
      --all)       RUN_INFRA=true; RUN_KB=true; RUN_AGENT=true; RUN_APP=true; RUN_SAM=true; RUN_FRONTEND=true; RUN_PIPELINE=true ;;
      --infra)     RUN_INFRA=true ;;
      --kb)        RUN_KB=true ;;
      --agent)     RUN_AGENT=true ;;
      --app)       RUN_APP=true ;;
      --sam)       RUN_SAM=true ;;
      --frontend)  RUN_FRONTEND=true ;;
      --pipeline)  RUN_PIPELINE=true ;;
      *) echo "Unknown option: $arg"; exit 1 ;;
    esac
  done
fi

# ── STEP 0: 인프라 (CloudFormation) ──
if [ "$RUN_INFRA" = true ]; then
  echo "============================================================"
  echo "STEP 0: 인프라 배포 (S3 2개 + IAM 2개)"
  echo "============================================================"
  aws cloudformation deploy \
    --template-file 00-infra.yaml \
    --stack-name dining-infra \
    --parameter-overrides AccountId=$ACCOUNT_ID \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $REGION
  echo "✅ 인프라 배포 완료"
  echo ""
fi

# ── STEP 1: Knowledge Base ──
if [ "$RUN_KB" = true ]; then
  echo "============================================================"
  echo "STEP 1: Knowledge Base 생성"
  echo "============================================================"
  cd 01-kb && bash setup-kb.sh
  cd "$SCRIPT_DIR"

  # KB_ID를 03-app/tools.py에 자동 반영
  KB_ID_FILE="01-kb/kb-id.txt"
  if [ -f "$KB_ID_FILE" ]; then
    KB_ID=$(cat "$KB_ID_FILE")
    sed -i "s/KB_ID = \".*\"/KB_ID = \"$KB_ID\"/" 03-app/tools.py
    echo "✅ 03-app/tools.py KB_ID 업데이트: $KB_ID"
  fi

  echo ""
  echo "KB 동기화 대기 (60초)..."
  sleep 60
fi

# ── STEP 2: AgentCore Runtime + Memory + Gateway 배포 ──
if [ "$RUN_AGENT" = true ]; then
  echo "============================================================"
  echo "STEP 2: AgentCore Runtime + Memory + Gateway 배포"
  echo "============================================================"
  cd 02-agent

  # Memory 추가 (이미 있으면 건너뜀)
  EXISTING_MEMORY=$(grep -c '"memories":\s*\[\s*{' agentcore/agentcore.json 2>/dev/null || echo "0")
  if [ "$EXISTING_MEMORY" = "0" ]; then
    echo "  [1/3] Memory 추가..."
    npx @aws/agentcore add memory \
      --name dining_memory \
      --strategies USER_PREFERENCE,SEMANTIC \
      --expiry 30 2>/dev/null || echo "  (이미 존재 — 건너뜀)"
  else
    echo "  [1/3] Memory 이미 설정됨 — 건너뜀"
  fi

  # Gateway 추가 (Web Search, us-east-1 전용)
  EXISTING_GW=$(grep -c '"agentCoreGateways":\s*\[\s*{' agentcore/agentcore.json 2>/dev/null || echo "0")
  if [ "$EXISTING_GW" = "0" ]; then
    echo "  [2/3] Web Search Gateway 추가..."
    npx @aws/agentcore add gateway \
      --name dining-web-search \
      --protocol-type MCP \
      --authorizer-type NONE 2>/dev/null || echo "  (이미 존재 — 건너뜀)"

    npx @aws/agentcore add gateway-target \
      --name web-search \
      --gateway dining-web-search \
      --type connector \
      --connector web-search 2>/dev/null || echo "  (이미 존재 — 건너뜀)"
  else
    echo "  [2/3] Gateway 이미 설정됨 — 건너뜀"
  fi

  # 배포 (Runtime + Memory + Gateway)
  echo "  [3/3] AgentCore 배포..."
  bash deploy.sh
  cd "$SCRIPT_DIR"

  # RUNTIME_ARN 추출
  RUNTIME_ARN=$(npx @aws/agentcore status --json 2>/dev/null | \
    python3 -c "import sys,json; data=json.load(sys.stdin); print(data['runtimes'][0]['arn'])" 2>/dev/null || echo "")
  if [ -z "$RUNTIME_ARN" ]; then
    RUNTIME_ARN=$(npx @aws/agentcore status 2>/dev/null | grep -oP 'arn:aws:bedrock-agentcore:[^\s)]+' | head -1)
  fi

  # MEMORY_ID 추출
  MEMORY_ID=$(aws bedrock-agentcore-control list-memories \
    --region "$AWS_REGION" \
    --query "memories[0].id" --output text 2>/dev/null || echo "")
  if [ -z "$MEMORY_ID" ]; then
    MEMORY_ID=$(npx @aws/agentcore status 2>/dev/null | grep -oP '[A-Za-z0-9_]+-[A-Za-z0-9]+' | grep -i memory | head -1 || echo "")
  fi

  # GATEWAY_URL 추출
  GATEWAY_ID=$(npx @aws/agentcore status 2>/dev/null | grep -oP 'dining-web-search[^\s]+' | head -1 || echo "")
  if [ -n "$GATEWAY_ID" ]; then
    GATEWAY_URL="https://${GATEWAY_ID}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
  else
    GATEWAY_URL=""
  fi

  # SSM Parameter Store에 저장 (CI/CD에서 자동으로 읽음)
  if [ -n "$RUNTIME_ARN" ]; then
    aws ssm put-parameter --name "/dining/RUNTIME_ARN" --value "$RUNTIME_ARN" \
      --type String --overwrite --region "$AWS_REGION" 2>/dev/null
    echo "✅ SSM /dining/RUNTIME_ARN: $RUNTIME_ARN"
  else
    echo "⚠️  RUNTIME_ARN 추출 실패"
  fi
  if [ -n "$MEMORY_ID" ]; then
    aws ssm put-parameter --name "/dining/MEMORY_ID" --value "$MEMORY_ID" \
      --type String --overwrite --region "$AWS_REGION" 2>/dev/null
    echo "✅ SSM /dining/MEMORY_ID: $MEMORY_ID"
  fi
  if [ -n "$GATEWAY_URL" ]; then
    aws ssm put-parameter --name "/dining/GATEWAY_URL" --value "$GATEWAY_URL" \
      --type String --overwrite --region "$AWS_REGION" 2>/dev/null
    echo "✅ SSM /dining/GATEWAY_URL: $GATEWAY_URL"
  fi

  # 03-app/.env 생성 (로컬 앱용)
  cat > 03-app/.env <<EOF
# DiningConcierge 로컬 앱 환경변수 (setup.sh에 의해 자동 생성됨)
RUNTIME_ARN=${RUNTIME_ARN}
MEMORY_ID=${MEMORY_ID}
GATEWAY_WEB_SEARCH_URL=${GATEWAY_URL}
AWS_REGION=${AWS_REGION:-us-west-2}
EOF
  echo "✅ 03-app/.env 생성 완료"

  echo ""
fi

# ── STEP 3: Streamlit 앱 설치 ──
if [ "$RUN_APP" = true ]; then
  echo "============================================================"
  echo "STEP 3: Streamlit 앱 설치"
  echo "============================================================"
  cd 03-app
  python3 -m venv venv 2>/dev/null || true
  source venv/bin/activate
  pip install -r requirements.txt -q
  deactivate
  echo "✅ Streamlit 설치 완료"
  echo "   실행: cd 03-app && source venv/bin/activate && streamlit run app.py --server.port 8501"
  cd "$SCRIPT_DIR"
  echo ""
fi

# ── STEP 4: SAM API 배포 ──
if [ "$RUN_SAM" = true ]; then
  echo "============================================================"
  echo "STEP 4: SAM API 배포 (Lambda + API Gateway)"
  echo "============================================================"
  cd 05-sam

  # RUNTIME_ARN을 SSM에서 읽기 (없으면 직접 조회)
  RUNTIME_ARN=$(aws ssm get-parameter --name "/dining/RUNTIME_ARN" \
    --query "Parameter.Value" --output text --region "$AWS_REGION" 2>/dev/null || echo "")
  if [ -z "$RUNTIME_ARN" ]; then
    RUNTIME_ARN=$(aws bedrock-agentcore-control list-agent-runtimes \
      --region "$AWS_REGION" \
      --query "agentRuntimes[?status=='READY'].agentRuntimeArn | [0]" \
      --output text 2>/dev/null || echo "")
  fi

  sam build
  sam deploy \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset \
    --parameter-overrides RuntimeArn="$RUNTIME_ARN"

  # API URL 추출 + SSM 저장
  API_URL=$(aws cloudformation describe-stacks \
    --stack-name dining-sam-api \
    --query "Stacks[0].Outputs[?OutputKey=='ChatApiUrl'].OutputValue" \
    --output text --region "${AWS_REGION:-us-west-2}" 2>/dev/null || echo "")

  if [ -n "$API_URL" ]; then
    echo "$API_URL" > api-url.txt
    aws ssm put-parameter --name "/dining/API_URL" --value "$API_URL" \
      --type String --overwrite --region "${AWS_REGION:-us-west-2}" 2>/dev/null
    echo "✅ SAM API 배포 완료: $API_URL"
  else
    echo "✅ SAM 배포 완료 (URL은 CloudFormation 출력에서 확인)"
  fi

  cd "$SCRIPT_DIR"
  echo ""
fi

# ── STEP 5: Frontend 빌드 & S3 + CloudFront 배포 ──
if [ "$RUN_FRONTEND" = true ]; then
  echo "============================================================"
  echo "STEP 5: React 프론트엔드 빌드 & S3 + CloudFront 배포"
  echo "============================================================"
  cd 06-frontend

  # API URL 설정
  API_URL_FILE="$SCRIPT_DIR/05-sam/api-url.txt"
  if [ -f "$API_URL_FILE" ]; then
    export REACT_APP_API_URL=$(cat "$API_URL_FILE")
    echo "API URL: $REACT_APP_API_URL"
  else
    echo "⚠️ SAM API URL 없음. REACT_APP_API_URL 수동 설정 필요."
    export REACT_APP_API_URL="http://localhost:3001"
  fi

  npm install
  npm run build

  # S3에 업로드
  FRONTEND_BUCKET="dining-frontend-${ACCOUNT_ID}"
  aws s3 sync build/ s3://${FRONTEND_BUCKET}/ --delete --region $REGION
  echo "✅ Frontend S3 업로드 완료: s3://${FRONTEND_BUCKET}/"

  # CloudFront Distribution 확인 또는 생성
  DIST_ID=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?contains(Origins.Items[0].DomainName, '${FRONTEND_BUCKET}')].Id" \
    --output text 2>/dev/null || echo "")

  if [ -n "$DIST_ID" ] && [ "$DIST_ID" != "None" ]; then
    # 이미 존재 → 캐시 무효화만
    aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" > /dev/null
    CF_DOMAIN=$(aws cloudfront get-distribution --id "$DIST_ID" \
      --query "Distribution.DomainName" --output text)
    echo "✅ CloudFront 캐시 무효화 완료: https://${CF_DOMAIN}"
  else
    echo "  CloudFront Distribution 생성 중..."

    # OAC 생성 (이미 있으면 재사용)
    OAC_ID=$(aws cloudfront list-origin-access-controls \
      --query "OriginAccessControlList.Items[?Name=='dining-frontend-oac'].Id" \
      --output text 2>/dev/null || echo "")

    if [ -z "$OAC_ID" ] || [ "$OAC_ID" = "None" ]; then
      OAC_ID=$(aws cloudfront create-origin-access-control \
        --origin-access-control-config '{
          "Name": "dining-frontend-oac",
          "Description": "OAC for dining frontend S3 bucket",
          "OriginAccessControlOriginType": "s3",
          "SigningBehavior": "always",
          "SigningProtocol": "sigv4"
        }' --query "OriginAccessControl.Id" --output text)
      echo "  OAC 생성: $OAC_ID"
    else
      echo "  기존 OAC 재사용: $OAC_ID"
    fi

    # CloudFront Distribution 생성
    CF_RESULT=$(aws cloudfront create-distribution \
      --distribution-config '{
        "CallerReference": "dining-frontend-'"$(date +%s)"'",
        "Comment": "DiningConcierge Frontend",
        "DefaultRootObject": "index.html",
        "Enabled": true,
        "Origins": {
          "Quantity": 1,
          "Items": [
            {
              "Id": "S3-'"${FRONTEND_BUCKET}"'",
              "DomainName": "'"${FRONTEND_BUCKET}"'.s3.'"${REGION}"'.amazonaws.com",
              "OriginAccessControlId": "'"${OAC_ID}"'",
              "S3OriginConfig": {
                "OriginAccessIdentity": ""
              }
            }
          ]
        },
        "DefaultCacheBehavior": {
          "TargetOriginId": "S3-'"${FRONTEND_BUCKET}"'",
          "ViewerProtocolPolicy": "redirect-to-https",
          "AllowedMethods": {
            "Quantity": 2,
            "Items": ["GET", "HEAD"]
          },
          "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
          "Compress": true
        },
        "CustomErrorResponses": {
          "Quantity": 2,
          "Items": [
            {
              "ErrorCode": 403,
              "ResponsePagePath": "/index.html",
              "ResponseCode": "200",
              "ErrorCachingMinTTL": 10
            },
            {
              "ErrorCode": 404,
              "ResponsePagePath": "/index.html",
              "ResponseCode": "200",
              "ErrorCachingMinTTL": 10
            }
          ]
        },
        "PriceClass": "PriceClass_100",
        "ViewerCertificate": {
          "CloudFrontDefaultCertificate": true
        }
      }' --output json 2>&1)

    DIST_ID=$(echo "$CF_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Distribution']['Id'])")
    CF_DOMAIN=$(echo "$CF_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['Distribution']['DomainName'])")

    echo "  ✅ CloudFront Distribution 생성: $DIST_ID"
    echo "  Domain: https://${CF_DOMAIN}"

    # S3 버킷 정책 설정 (CloudFront OAC에서만 접근)
    aws s3api put-bucket-policy \
      --bucket "$FRONTEND_BUCKET" \
      --policy '{
        "Version": "2012-10-17",
        "Statement": [
          {
            "Sid": "AllowCloudFrontServicePrincipal",
            "Effect": "Allow",
            "Principal": {
              "Service": "cloudfront.amazonaws.com"
            },
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::'"${FRONTEND_BUCKET}"'/*",
            "Condition": {
              "StringEquals": {
                "AWS:SourceArn": "arn:aws:cloudfront::'"${ACCOUNT_ID}"':distribution/'"${DIST_ID}"'"
              }
            }
          }
        ]
      }'
    echo "  ✅ S3 버킷 정책 업데이트 완료"
  fi

  # CloudFront URL 저장
  echo "https://${CF_DOMAIN:-$(aws cloudfront get-distribution --id "$DIST_ID" --query "Distribution.DomainName" --output text)}" > cloudfront-url.txt
  echo "✅ CloudFront URL 저장: $(cat cloudfront-url.txt)"

  cd "$SCRIPT_DIR"
  echo ""
fi

# ── STEP 6: CI/CD (GitHub Actions) ──
if [ "$RUN_PIPELINE" = true ]; then
  echo "============================================================"
  echo "STEP 6: CI/CD — GitHub Actions"
  echo "============================================================"
  echo ""
  echo "GitHub Actions 워크플로우가 이미 설정되어 있습니다:"
  echo "  .github/workflows/agent.yml    — 02-agent/** 변경 시 평가 + 배포"
  echo "  .github/workflows/api.yml      — 05-sam/** 변경 시 SAM 배포"
  echo "  .github/workflows/frontend.yml — 06-frontend/** 변경 시 빌드 + S3 + CloudFront"
  echo ""
  echo "📋 GitHub repo에 Secrets 등록 필요:"
  echo "  AWS_ACCESS_KEY_ID"
  echo "  AWS_SECRET_ACCESS_KEY"
  echo ""
  echo "  설정 방법: GitHub repo → Settings → Secrets and variables → Actions → New repository secret"
  echo ""
  echo "✅ git push to main 하면 변경된 경로에 따라 자동 배포됩니다."
  echo ""
fi

# ── 완료 ──
echo "============================================================"
echo "✅ 설정 완료!"
echo "============================================================"
echo ""
echo "수동 확인/설정 필요:"
echo "  - 03-app/app.py, 03-app/tools.py → 자동 업데이트됨 (확인만)"
echo ""
echo "실행 방법:"
echo "  [Streamlit 로컬] cd 03-app && source venv/bin/activate && streamlit run app.py"
echo "  [SAM API 테스트] curl -X POST \$(cat 05-sam/api-url.txt)/chat -d '{\"message\":\"이탈리안 추천해줘\"}'"
echo "  [Frontend]       브라우저에서 CloudFront URL 또는 06-frontend/cloudfront-url.txt 참조"
echo ""
echo "선택적 추가:"
echo "  - Memory 생성: AgentCore 콘솔에서 memory 생성 후 app.py의 MEMORY_ID 수정"
echo "  - Gateway (Web Search): us-east-1에서 Gateway + Connector 생성"
echo ""
