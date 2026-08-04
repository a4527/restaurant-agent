#!/bin/bash
# KB 생성 스크립트 — Bedrock Knowledge Base + OpenSearch Serverless (수동 생성)
# 사전 조건: 00-infra.yaml 배포 완료
# 멱등성: 이미 존재하는 리소스는 건너뛰고 기존 ID 재사용
set -e

REGION=${AWS_DEFAULT_REGION:-us-west-2}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
BUCKET_NAME="dining-kb-data-${ACCOUNT_ID}"
KB_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/dining-kb-role"
EMBED_MODEL="amazon.titan-embed-text-v2:0"
COLLECTION_NAME="dining-kb-collection"
INDEX_NAME="bedrock-knowledge-base-default-index"

echo "============================================================"
echo " Knowledge Base 생성 스크립트"
echo " Account: $ACCOUNT_ID | Region: $REGION"
echo "============================================================"
echo ""

# ────────────────────────────────────────────────────────────────
# 1. S3에 식당 데이터 업로드
# ────────────────────────────────────────────────────────────────
echo "=== 1. S3에 식당 데이터 업로드 ==="
aws s3 sync ./data/ s3://${BUCKET_NAME}/restaurant-docs/ --region $REGION
echo "✅ 데이터 업로드 완료"
echo ""

# ────────────────────────────────────────────────────────────────
# 2. OpenSearch Serverless 컬렉션 생성 (이미 있으면 재사용)
# ────────────────────────────────────────────────────────────────
echo "=== 2. OpenSearch Serverless 컬렉션 생성 ==="

# 기존 컬렉션 확인
EXISTING_COLLECTION=$(aws opensearchserverless list-collections \
  --region $REGION \
  --query "collectionSummaries[?name=='${COLLECTION_NAME}'].id" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_COLLECTION" ] && [ "$EXISTING_COLLECTION" != "None" ]; then
  COLLECTION_ID="$EXISTING_COLLECTION"
  echo "  기존 컬렉션 발견: $COLLECTION_ID (재사용)"
else
  # 2-1. Encryption Policy
  echo "  [1/4] Encryption Policy 생성..."
  aws opensearchserverless create-security-policy \
    --name "${COLLECTION_NAME}-enc" \
    --type encryption \
    --policy "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION_NAME}\"]}],\"AWSOwnedKey\":true}" \
    --region $REGION > /dev/null 2>&1 || echo "  (이미 존재 — 건너뜀)"

  # 2-2. Network Policy (public access)
  echo "  [2/4] Network Policy 생성..."
  aws opensearchserverless create-security-policy \
    --name "${COLLECTION_NAME}-net" \
    --type network \
    --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION_NAME}\"]},{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/${COLLECTION_NAME}\"]}],\"AllowFromPublic\":true}]" \
    --region $REGION > /dev/null 2>&1 || echo "  (이미 존재 — 건너뜀)"

  # 2-3. Data Access Policy
  echo "  [3/4] Data Access Policy 생성..."
  aws opensearchserverless create-access-policy \
    --name "${COLLECTION_NAME}-access" \
    --type data \
    --policy "[{\"Rules\":[{\"ResourceType\":\"index\",\"Resource\":[\"index/${COLLECTION_NAME}/*\"],\"Permission\":[\"aoss:CreateIndex\",\"aoss:UpdateIndex\",\"aoss:DescribeIndex\",\"aoss:ReadDocument\",\"aoss:WriteDocument\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION_NAME}\"],\"Permission\":[\"aoss:CreateCollectionItems\",\"aoss:DescribeCollectionItems\",\"aoss:UpdateCollectionItems\"]}],\"Principal\":[\"${KB_ROLE_ARN}\",\"${CALLER_ARN}\"]}]" \
    --region $REGION > /dev/null 2>&1 || echo "  (이미 존재 — 건너뜀)"

  # 2-4. 컬렉션 생성
  echo "  [4/4] 컬렉션 생성..."
  CREATE_RESULT=$(aws opensearchserverless create-collection \
    --name "${COLLECTION_NAME}" \
    --type VECTORSEARCH \
    --region $REGION \
    --output json 2>&1)
  COLLECTION_ID=$(echo "$CREATE_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['createCollectionDetail']['id'])" 2>/dev/null)

  if [ -z "$COLLECTION_ID" ]; then
    echo "❌ 컬렉션 생성 실패:"
    echo "$CREATE_RESULT"
    exit 1
  fi

  # ACTIVE 대기
  echo "  컬렉션 ACTIVE 대기 중 (최대 10분)..."
  for i in $(seq 1 60); do
    STATUS=$(aws opensearchserverless batch-get-collection \
      --ids "$COLLECTION_ID" \
      --region $REGION \
      --query "collectionDetails[0].status" --output text 2>/dev/null)
    if [ "$STATUS" = "ACTIVE" ]; then
      break
    fi
    printf "\r  대기 중... %ds" $((i * 10))
    sleep 10
  done
  echo ""

  if [ "$STATUS" != "ACTIVE" ]; then
    echo "❌ 컬렉션이 ACTIVE 되지 않음 (status: $STATUS)"
    exit 1
  fi
fi

COLLECTION_ARN="arn:aws:aoss:${REGION}:${ACCOUNT_ID}:collection/${COLLECTION_ID}"
COLLECTION_ENDPOINT=$(aws opensearchserverless batch-get-collection \
  --ids "$COLLECTION_ID" \
  --region $REGION \
  --query "collectionDetails[0].collectionEndpoint" --output text)

echo "✅ 컬렉션 준비 완료"
echo "  ARN: $COLLECTION_ARN"
echo "  Endpoint: $COLLECTION_ENDPOINT"
echo ""

# ────────────────────────────────────────────────────────────────
# 3. 벡터 인덱스 생성 (이미 있으면 건너뜀)
# ────────────────────────────────────────────────────────────────
echo "=== 3. 벡터 인덱스 생성 ==="

COLLECTION_HOST=$(echo "$COLLECTION_ENDPOINT" | sed 's|https://||')

python3 << EOF
import boto3, sys
try:
    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "opensearch-py", "requests-aws4auth", "-q", "--break-system-packages"], 
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth

region = "${REGION}"
host = "${COLLECTION_HOST}"
index_name = "${INDEX_NAME}"

session = boto3.Session()
creds = session.get_credentials().get_frozen_credentials()
auth = AWS4Auth(creds.access_key, creds.secret_key, region, "aoss", session_token=creds.token)

client = OpenSearch(
    hosts=[{"host": host, "port": 443}],
    http_auth=auth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection,
    timeout=30,
)

# 인덱스 존재 확인
if client.indices.exists(index=index_name):
    print("  인덱스 이미 존재 — 건너뜀")
else:
    client.indices.create(index=index_name, body={
        "settings": {"index.knn": True},
        "mappings": {
            "properties": {
                "vector": {
                    "type": "knn_vector",
                    "dimension": 1024,
                    "method": {"engine": "faiss", "name": "hnsw", "parameters": {}}
                },
                "text": {"type": "text"},
                "metadata": {"type": "text"}
            }
        }
    })
    print("  ✅ 벡터 인덱스 생성 완료")
EOF

echo ""

# ────────────────────────────────────────────────────────────────
# 4. Bedrock Knowledge Base 생성 (이미 있으면 재사용)
# ────────────────────────────────────────────────────────────────
echo "=== 4. Knowledge Base 생성 ==="

# 기존 KB 확인
EXISTING_KB=$(aws bedrock-agent list-knowledge-bases \
  --region $REGION \
  --query "knowledgeBaseSummaries[?name=='dining-restaurants-kb'].knowledgeBaseId" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_KB" ] && [ "$EXISTING_KB" != "None" ]; then
  KB_ID="$EXISTING_KB"
  echo "  기존 KB 발견: $KB_ID (재사용)"
else
  KB_RESULT=$(aws bedrock-agent create-knowledge-base \
    --name "dining-restaurants-kb" \
    --description "강남 식당 정보 Knowledge Base" \
    --role-arn "$KB_ROLE_ARN" \
    --knowledge-base-configuration '{
      "type": "VECTOR",
      "vectorKnowledgeBaseConfiguration": {
        "embeddingModelArn": "arn:aws:bedrock:'$REGION'::foundation-model/'$EMBED_MODEL'",
        "embeddingModelConfiguration": {
          "bedrockEmbeddingModelConfiguration": {"dimensions": 1024}
        }
      }
    }' \
    --storage-configuration '{
      "type": "OPENSEARCH_SERVERLESS",
      "opensearchServerlessConfiguration": {
        "collectionArn": "'"$COLLECTION_ARN"'",
        "fieldMapping": {
          "metadataField": "metadata",
          "textField": "text",
          "vectorField": "vector"
        },
        "vectorIndexName": "'"$INDEX_NAME"'"
      }
    }' \
    --region $REGION \
    --output json 2>&1)

  KB_ID=$(echo "$KB_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['knowledgeBase']['knowledgeBaseId'])" 2>/dev/null)

  if [ -z "$KB_ID" ]; then
    echo "❌ KB 생성 실패:"
    echo "$KB_RESULT"
    exit 1
  fi
  echo "  ✅ KB 생성 완료"
fi

echo "  KB ID: $KB_ID"
echo "$KB_ID" > kb-id.txt
echo ""

# ────────────────────────────────────────────────────────────────
# 5. Data Source 추가 (이미 있으면 재사용)
# ────────────────────────────────────────────────────────────────
echo "=== 5. Data Source 추가 ==="

EXISTING_DS=$(aws bedrock-agent list-data-sources \
  --knowledge-base-id "$KB_ID" \
  --region $REGION \
  --query "dataSourceSummaries[?name=='restaurant-docs'].dataSourceId" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_DS" ] && [ "$EXISTING_DS" != "None" ]; then
  DS_ID="$EXISTING_DS"
  echo "  기존 Data Source 발견: $DS_ID (재사용)"
else
  DS_RESULT=$(aws bedrock-agent create-data-source \
    --knowledge-base-id "$KB_ID" \
    --name "restaurant-docs" \
    --data-source-configuration '{
      "type": "S3",
      "s3Configuration": {
        "bucketArn": "arn:aws:s3:::'"$BUCKET_NAME"'",
        "inclusionPrefixes": ["restaurant-docs/"]
      }
    }' \
    --region $REGION \
    --output json 2>&1)

  DS_ID=$(echo "$DS_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['dataSource']['dataSourceId'])" 2>/dev/null)

  if [ -z "$DS_ID" ]; then
    echo "❌ Data Source 생성 실패:"
    echo "$DS_RESULT"
    exit 1
  fi
  echo "  ✅ Data Source 생성 완료"
fi

echo "  Data Source ID: $DS_ID"
echo ""

# ────────────────────────────────────────────────────────────────
# 6. 동기화 시작
# ────────────────────────────────────────────────────────────────
echo "=== 6. 동기화 시작 ==="
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "$KB_ID" \
  --data-source-id "$DS_ID" \
  --region $REGION > /dev/null

echo "✅ 동기화 시작됨 (완료까지 1-3분 소요)"
echo ""
echo "============================================================"
echo "✅ Knowledge Base 설정 완료"
echo "============================================================"
echo "  KB_ID=$KB_ID (kb-id.txt에 저장됨)"
echo "  Collection: $COLLECTION_ENDPOINT"
echo ""
echo "상태 확인:"
echo "  aws bedrock-agent list-ingestion-jobs --knowledge-base-id $KB_ID --data-source-id $DS_ID --region $REGION"
