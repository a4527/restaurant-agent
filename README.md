# DiningConcierge — 강남 식당 추천 AI 에이전트

> AWS Bedrock AgentCore 기반 풀스택 AI 에이전트 프로젝트  
> 새 AWS 계정에서 처음부터 끝까지 재현 가능한 올인원 프로젝트

---

## 프로젝트 개요

강남 지역 식당 8곳의 정보를 Bedrock Knowledge Base(RAG)에 저장하고,  
Strands Agents SDK 기반 에이전트가 도구 호출(검색/메뉴/예약/비용산정)로 추천하는 풀스택 AI 앱.

**핵심 구성 요소:**
- Bedrock Knowledge Base (OpenSearch Serverless + Titan Embed v2)
- Strands Agents SDK + MCP 서버 (예약/비용 도구)
- AgentCore Runtime (CDK 배포)
- Streamlit 앱 (로컬 테스트용)
- SAM Lambda API (서버리스 백엔드)
- React + Cloudscape 프론트엔드
- CloudFront + S3 정적 호스팅
- GitHub Actions CI/CD (경로별 자동 배포 + Strands Evals 평가 게이트)

---

## 아키텍처

```
사용자 (브라우저)
  ↓
CloudFront → S3 (React 정적 파일)   ← 06-frontend
  ↓ POST /chat
API Gateway → Lambda (SAM)           ← 05-sam
  ├─ Strands Agent + search_restaurants 도구
  └─ Bedrock KB retrieve (OpenSearch Serverless)
      ↓
  Bedrock Nova Lite → 응답 생성

[AgentCore Runtime 경로 — Streamlit 앱에서 사용]
Streamlit (03-app/app.py)
  ├─ Web Search Gateway (us-east-1) 직접 호출
  ├─ Memory (get_memory_record) → 취향 컨텍스트 주입
  ↓
AgentCore Runtime (us-west-2)        ← 02-agent
  ├─ tools.py → Bedrock KB retrieve  ← 01-kb
  ├─ mcp_server.py (stdio) → 예약/비용 도구
  ↓
Bedrock Nova Lite → 응답 생성
```

---

## 디렉토리 구조

```
restaurant-project/
├── README.md                 ← 이 파일 (통합 가이드)
├── setup.sh                  ← 전체 자동 재현 스크립트
├── progress-notes.md         ← 프로젝트 진행 기록
├── 00-infra.yaml             ← CloudFormation (S3 2개 + IAM 2개)
├── 01-kb/                    ← Knowledge Base
│   ├── setup-kb.sh           ← KB 생성 스크립트
│   └── data/                 ← 식당 데이터 (docx 8개 + metadata + xlsx)
├── 02-agent/                 ← AgentCore Runtime
│   ├── deploy.sh             ← 배포 스크립트
│   ├── agentcore/            ← AgentCore 설정 + CDK
│   │   ├── agentcore.json
│   │   └── cdk/
│   └── app/DiningConcierge/  ← Runtime 앱 코드
│       ├── main.py
│       ├── tools.py
│       ├── pyproject.toml
│       └── model/
├── 03-app/                   ← Streamlit 프로덕션 앱
│   ├── run.sh
│   ├── app.py                ← 채팅 UI + Memory + Web Search
│   ├── agent.py              ← 로컬 Agent 통합
│   ├── tools.py              ← KB 검색 도구
│   ├── mcp_server.py         ← MCP 예약/비용 도구
│   └── requirements.txt
├── .github/workflows/        ← GitHub Actions CI/CD
│   ├── agent.yml             ← 02-agent/** 변경 → 평가 + AgentCore deploy
│   ├── api.yml               ← 05-sam/** 변경 → SAM deploy
│   └── frontend.yml          ← 06-frontend/** 변경 → S3 + CloudFront
├── 04-pipeline/              ← CI/CD 관련 스크립트
│   └── eval_gate.py          ← Strands Evals 평가 스크립트
├── 05-sam/                   ← SAM 서버리스 API
│   ├── template.yaml         ← Lambda + API Gateway
│   ├── samconfig.toml
│   └── chat_function/
│       ├── app.py            ← Lambda 핸들러
│       └── requirements.txt
└── 06-frontend/              ← React 프론트엔드
    ├── package.json
    ├── cloudfront-url.txt
    ├── src/
    │   ├── App.js            ← Cloudscape 채팅 UI
    │   └── index.js
    └── public/
        └── index.html
```

---

## 사전 요구사항

```bash
# AWS CLI 설정 (리전: us-west-2)
aws configure  # region: us-west-2

# Node.js 20+
node --version  # v20.x

# Python 3.12+
python3 --version  # 3.12.x

# AgentCore CLI
npm install -g @aws/agentcore

# SAM CLI
pip install aws-sam-cli

# Bedrock 모델 접근 활성화 (콘솔에서)
# → Amazon Nova Lite (us.amazon.nova-lite-v1:0)
# → Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0)
```

---

## 빠른 시작 (전체 자동 배포)

```bash
cd restaurant-project
./setup.sh
```

---

## 단계별 수동 실행

### STEP 0: 인프라 배포 (CloudFormation)

S3 버킷 2개 + IAM 역할 2개를 한 번에 배포합니다.

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws cloudformation deploy \
  --template-file 00-infra.yaml \
  --stack-name dining-infra \
  --parameter-overrides AccountId=$ACCOUNT_ID \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

생성되는 리소스:
- `dining-kb-data-{AccountId}` — KB 데이터 소스 (Versioned)
- `dining-frontend-{AccountId}` — Frontend 정적 호스팅
- `dining-kb-role` — Bedrock KB S3/Embed/OpenSearch 접근
- `dining-gateway-role` — AgentCore Web Search Gateway

---

### STEP 1: Knowledge Base 생성

```bash
cd 01-kb && bash setup-kb.sh
```

스크립트 동작:
1. S3에 식당 데이터(docx 8개 + metadata JSON) 업로드
2. Bedrock KB 생성 (OpenSearch Serverless + Titan Embed v2, 1024차원)
3. Data Source 추가 및 동기화 시작

완료 후 `kb-id.txt`에 KB ID 저장됨.

---

### STEP 2: AgentCore Runtime 배포

```bash
cd 02-agent && bash deploy.sh
```

스크립트 동작:
1. KB ID 자동 읽어서 tools.py 업데이트
2. CDK 의존성 설치 (npm ci + build)
3. `npx @aws/agentcore deploy --yes`

배포 후 `npx @aws/agentcore status`로 Runtime ID 확인.

---

### STEP 3: Streamlit 앱 (로컬 테스트)

```bash
cd 03-app && bash run.sh
```

**`setup.sh`가 자동으로 설정합니다:**
- `app.py`의 `RUNTIME_ARN` ← Step 2 완료 후 자동 반영
- `tools.py`의 `KB_ID` ← Step 1 완료 후 자동 반영

기능:
- AgentCore Runtime 호출 (검색/메뉴/예약/비용 도구)
- Web Search Gateway 직접 호출 (us-east-1)
- Memory 연동 (취향 저장/검색)
- 도구 호출 로그 사이드바
- 식당 상세 카드 UI

---

### STEP 4: SAM API 배포 (서버리스 백엔드)

```bash
cd 05-sam
pip install aws-sam-cli  # 설치 안 된 경우
sam build
sam deploy --guided  # 또는 sam deploy (samconfig.toml 사용)
```

배포 결과: API Gateway endpoint URL 출력됨 (예: `https://xxxx.execute-api.us-west-2.amazonaws.com/Prod`)

---

### STEP 5: React 프론트엔드 빌드 & 배포

```bash
cd 06-frontend
npm install
REACT_APP_API_URL=https://YOUR_API_GATEWAY_URL/Prod npm run build
```

S3 + CloudFront 배포 (`setup.sh --frontend`가 자동으로 수행):
1. S3에 빌드 파일 업로드
2. OAC 생성 (최초 1회)
3. CloudFront Distribution 생성 (SPA 에러 페이지 포함)
4. S3 버킷 정책 설정 (CloudFront에서만 접근)
5. `cloudfront-url.txt`에 URL 저장

수동 실행 시:
```bash
./setup.sh --frontend
```

---

### STEP 6: CI/CD (GitHub Actions)

GitHub에 push하면 변경된 경로에 따라 자동으로 해당 부분만 배포됩니다.

| 워크플로우 | 트리거 경로 | 동작 |
|-----------|------------|------|
| `agent.yml` | `02-agent/**` | Strands Evals 평가 → AgentCore deploy |
| `api.yml` | `05-sam/**` | SAM build → SAM deploy |
| `frontend.yml` | `06-frontend/**` | npm build → S3 sync → CloudFront 무효화 |

**사전 설정 (GitHub repo):**
1. Settings → Secrets and variables → Actions
2. 아래 Secrets 등록:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`

```bash
# 예: 에이전트 코드 수정 후
git add 02-agent/
git commit -m "에이전트 시스템 프롬프트 수정"
git push origin main
# → agent.yml 워크플로우만 자동 실행 (평가 통과 시 배포)
```

---

## 완료된 작업

| 단계 | 내용 | 상태 |
|------|------|------|
| STEP 1~5 | KB 생성, 데이터 업로드/동기화 | ✅ |
| STEP 6~20 | Strands Agent 개발 + AgentCore Runtime 배포 | ✅ |
| STEP 21 | MCP 서버 (예약/비용 3개 도구) | ✅ |
| STEP 22 | AgentCore Memory 연동 | ✅ (인덱싱 지연 이슈 존재) |
| STEP 23 | 코드 리팩토링 + 프로덕션 보강 | ✅ |
| STEP 24 | Web Search Gateway 연동 (us-east-1) | ✅ |
| STEP 25 | CI/CD — GitHub Actions (경로별 자동 배포) | ✅ |
| SAM API | Lambda + API Gateway | ✅ |
| Frontend | React + Cloudscape 채팅 UI | ✅ |
| CloudFront | S3 정적 호스팅 | ✅ |

---

## 미해결 이슈 & 남은 작업

### 🟡 Memory 인덱싱 안정화

**현황**: batch_create_memory_records → get_memory_record 정상, RetrieveMemoryRecords 0건  
**우회**: 직접 get_memory_record로 조회 후 prompt 주입 방식 사용 중  
**확인**: 시간 경과 후 자동 해결 가능 (벡터 인덱싱 지연)

### 🟡 Gateway 보안 강화

**현재**: authorizer-type: NONE (인증 없이 접근)  
**프로덕션**: AWS_IAM으로 전환 필요

---

## 리소스 정리 (Workshop 계정)

| 리소스 | ID / 이름 | 리전 |
|--------|-----------|------|
| KB | RIFBMADYWG | us-west-2 |
| Runtime | DiningConcierge_DiningConcierge-LEm0AP8Vi2 | us-west-2 |
| Memory | DiningConcierge_dining_memory-R5zXit9OAR | us-west-2 |
| Gateway | dining-web-search-gateway-fiahbr5mdx | us-east-1 |
| S3 (KB data) | dining-kb-data-902777495046 | us-west-2 |
| S3 (Frontend) | dining-frontend-902777495046 | us-west-2 |
| CloudFront | d3t06p9k7ww2xw.cloudfront.net | Global |
| SAM Stack | dining-sam-api | us-west-2 |

---

## 주의사항

- `03-app/tools.py`, `05-sam/chat_function/app.py`의 `KB_ID`는 `setup.sh`가 자동 반영
- `03-app/app.py`의 `RUNTIME_ARN`은 `setup.sh`가 자동 반영
- Web Search Gateway는 **us-east-1 전용** (cross-region 호출)
- AgentCore Memory 인덱싱에 시간 소요 (10분~)
- SAM deploy 시 `--guided` 옵션으로 최초 설정 후 `samconfig.toml`에 저장됨
- Frontend의 `REACT_APP_API_URL`은 SAM 배포 후 자동 설정됨
