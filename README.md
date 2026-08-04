# DiningConcierge — 강남 식당 추천 AI 에이전트

> AWS Bedrock AgentCore 기반 풀스택 AI 에이전트  
> 새 AWS 계정에서 `./setup.sh --all` 한 번으로 전체 인프라 + 앱 재현 가능

---

## 프로젝트 개요

강남 지역 식당 8곳의 정보를 Bedrock Knowledge Base(RAG)에 저장하고, Strands Agents SDK 기반 에이전트가 도구 호출(검색·메뉴·예약·비용산정)을 통해 맞춤 추천하는 풀스택 AI 애플리케이션입니다.

**핵심 특징:**
- 자연어 질문 → AI가 자동으로 적절한 도구를 선택하여 답변
- 벡터 검색 기반 식당 추천 (분위기, 가격대, 메뉴 유형별)
- MCP 프로토콜로 예약·비용 산정 도구 연동
- 사용자 취향 기억 (AgentCore Memory)
- 실시간 웹 검색으로 최신 정보 보완
- 무중단 배포 + 품질 게이트 기반 CI/CD

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│  사용자 (브라우저)                                                    │
└──────────────┬──────────────────────────────────────────────────────┘
               ▼
┌──────────────────────────┐
│  CloudFront (CDN)        │ ← 06-frontend
│  └─ S3 (React 정적 파일) │
└──────────────┬───────────┘
               │ POST /chat
               ▼
┌──────────────────────────┐
│  API Gateway → Lambda    │ ← 05-sam
│  (경량 프록시, 256MB)     │
│  boto3 invoke만 수행      │
└──────────────┬───────────┘
               │ invoke_agent_runtime()
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  AgentCore Runtime (풀기능 에이전트)                     ← 02-agent │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Strands Agent (도구 자동 선택)                               │  │
│  │                                                               │  │
│  │  ├─ search_restaurants → Bedrock KB (벡터 검색)    ← 01-kb   │  │
│  │  ├─ get_menu → Bedrock KB (식당명 필터)                       │  │
│  │  ├─ MCP Server (stdio) → 예약 / 비용 산정 도구              │  │
│  │  ├─ Web Search Gateway (us-east-1) → 실시간 웹 검색          │  │
│  │  └─ Memory → 사용자 취향 저장/검색                            │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│                    Bedrock Nova Lite → 응답 생성                    │
└──────────────────────────────────────────────────────────────────┘
```

### 요청 흐름

1. 사용자가 React 채팅 UI에서 메시지 입력
2. `POST /chat` → API Gateway → Lambda (프록시)
3. Lambda가 `invoke_agent_runtime()`으로 AgentCore Runtime 호출
4. Runtime 내 Strands Agent가 질문을 분석하여 **도구 자동 선택**:
   - 식당 검색 → KB 벡터 검색 (분위기·가격대·유형)
   - 메뉴 조회 → KB 검색 (식당명 필터)
   - 예약 → MCP 서버 호출
   - 비용 산정 → MCP 서버 호출
   - 실시간 정보 → Web Search Gateway
   - 취향 기억 → Memory 저장/검색
5. Agent가 도구 결과를 종합하여 Nova Lite로 자연어 응답 생성
6. 스트리밍 응답 → Lambda 조합 → JSON 반환 → 프론트엔드 렌더링

### 계층별 역할 분리

| 계층 | 역할 | 특징 |
|------|------|------|
| CloudFront + S3 | 정적 파일 서빙 | OAC로 S3 직접 접근 차단 |
| Lambda | Runtime 프록시 | 에이전트 로직 없음, boto3만 사용 (경량) |
| AgentCore Runtime | 전체 에이전트 로직 | KB·MCP·Memory·WebSearch 통합 |
| Bedrock KB | 벡터 검색 (RAG) | OpenSearch Serverless + Titan Embed v2 |

> **설계 철학**: Lambda는 순수 프록시로 유지하여 에이전트 로직 변경 시 Lambda 재배포가 불필요합니다. 에이전트 코드는 AgentCore Runtime에만 존재하며 독립 배포됩니다.

---

## 디렉토리 구조

```
restaurant-project/
├── README.md                 ← 이 파일
├── MANUAL-SETUP.md           ← 트러블슈팅 참조
├── TROUBLESHOOTING.md        ← 문제 해결 가이드
├── setup.sh                  ← 전체 자동 재현 스크립트 (멱등)
├── progress-notes.md         ← 개발 진행 기록
│
├── 00-infra.yaml             ← CloudFormation (S3 ×2 + IAM ×2)
│
├── 01-kb/                    ← Knowledge Base
│   ├── setup-kb.sh           ← KB 자동 생성 (OpenSearch → 인덱스 → KB → 동기화)
│   └── data/                 ← 식당 데이터 (docx 8개 + metadata)
│
├── 02-agent/                 ← AgentCore Runtime
│   ├── deploy.sh             ← 배포 스크립트
│   ├── agentcore/            ← agentcore.json + CDK 설정
│   └── app/DiningConcierge/  ← 에이전트 코드
│       ├── main.py           ← 엔트리포인트 (Strands Agent)
│       ├── tools.py          ← KB 검색 도구
│       └── mcp_server.py     ← MCP 예약/비용 도구
│
├── 03-app/                   ← Streamlit 로컬 테스트 (선택)
│
├── 04-pipeline/              ← 평가 게이트
│   └── eval_gate.py          ← Strands Evals (3케이스, ≥0.7 PASS)
│
├── 05-sam/                   ← SAM 서버리스 API
│   ├── template.yaml         ← Lambda + API Gateway
│   └── chat_function/app.py  ← invoke_agent_runtime() 프록시
│
├── 06-frontend/              ← React 프론트엔드
│   ├── package.json          ← React 18 + Cloudscape
│   └── src/App.js            ← 채팅 UI
│
└── .github/workflows/        ← CI/CD
    ├── agent.yml             ← 에이전트 평가 + 배포
    ├── api.yml               ← SAM 배포
    └── frontend.yml          ← 프론트엔드 배포
```

---

## 빠른 시작

### 사전 요구사항

```bash
# AWS CLI (리전: us-west-2)
aws configure  # region: us-west-2

# Node.js 20+, Python 3.12+
node --version && python3 --version

# AgentCore CLI
npm install -g @aws/agentcore

# SAM CLI
pip install aws-sam-cli

# Bedrock 모델 접근 활성화 (AWS 콘솔)
# → Amazon Nova Lite (us.amazon.nova-lite-v1:0)
# → Amazon Titan Text Embeddings V2 (amazon.titan-embed-text-v2:0)
```

### 전체 자동 배포 (원커맨드)

```bash
cd restaurant-project
./setup.sh --all
```

완료 후 `06-frontend/cloudfront-url.txt`에 접속 URL이 저장됩니다.

> **멱등성 보장**: 여러 번 실행해도 안전합니다. 기존 리소스는 재사용하고 없는 것만 생성합니다.

### setup.sh 단계별 동작

| 단계 | 옵션 | 수행 내용 |
|------|------|-----------|
| STEP 0 | `--infra` | CloudFormation 배포 — S3 버킷 2개 + IAM 역할 2개 |
| STEP 1 | `--kb` | OpenSearch 컬렉션 + 벡터 인덱스(1024dim) + KB 생성 + 데이터 동기화 |
| STEP 2 | `--agent` | Memory + Gateway 생성 + AgentCore CDK 배포 + ARN/ID를 SSM에 자동 저장 + `.env` 생성 |
| STEP 3 | `--app` | Streamlit venv 구성 (로컬 테스트 전용, 선택) |
| STEP 4 | `--sam` | SAM build + deploy (SSM에서 RUNTIME_ARN 자동 읽어서 주입) |
| STEP 5 | `--frontend` | npm build + S3 업로드 + OAC + CloudFront 생성 |
| STEP 6 | `--pipeline` | GitHub Actions 설정 안내 |

- `./setup.sh` (인자 없음): STEP 0~3만 실행 (로컬 개발 환경)
- `./setup.sh --all`: STEP 0~6 전체 실행 (프로덕션 배포)

> **수동 설정 불필요**: 모든 ID, ARN, URL이 단계 간 자동 반영됩니다.  
> **코드 수정 없음**: ID/ARN은 코드가 아닌 SSM Parameter Store와 `.env`로 관리됩니다.

### 환경변수 관리 구조

모든 ID/ARN/URL은 코드에 하드코딩되지 않습니다:

```
[setup.sh --agent] → 배포 완료
         │
         ├─ SSM /dining/RUNTIME_ARN  ← api.yml이 읽어서 Lambda에 주입
         ├─ SSM /dining/MEMORY_ID    ← (참조용)
         ├─ SSM /dining/GATEWAY_URL  ← (참조용)
         └─ 03-app/.env              ← 로컬 앱이 읽음

[api.yml] → SAM 배포
         │
         └─ SSM /dining/API_URL      ← frontend.yml이 읽어서 React 빌드에 주입

[로컬 앱] → 03-app/.env 파일 읽음
         (cp .env.example .env 후 값 입력, 또는 setup.sh 자동 생성)
```

---

## 배포 전략 (무중단)

모든 계층이 blue-green 방식으로 동작하여 **배포 중에도 서비스가 정상 유지**됩니다.

| 계층 | 배포 방식 | 다운타임 |
|------|-----------|----------|
| AgentCore Runtime | 새 버전 준비 완료(READY) → 트래픽 전환 | 없음 |
| Lambda (SAM) | 새 코드 업로드 → 다음 호출부터 적용 | 없음 |
| CloudFront + S3 | 새 파일 업로드 → 캐시 무효화 | 없음 |

### 독립 배포의 장점

```
에이전트 프롬프트 수정 → 02-agent만 배포 (Lambda·프론트 영향 없음)
API 로직 변경 → 05-sam만 배포 (에이전트·프론트 영향 없음)
UI 수정 → 06-frontend만 배포 (백엔드 영향 없음)
```

---

## CI/CD (GitHub Actions)

코드를 push하면 **변경된 경로에 해당하는 워크플로우만** 자동 실행됩니다.

### 워크플로우 구성

| 파일 | 트리거 경로 | 파이프라인 |
|------|------------|-----------|
| `agent.yml` | `02-agent/**`, `04-pipeline/**` | Strands Evals 평가 → (≥0.7 PASS) → CDK bootstrap → AgentCore deploy |
| `api.yml` | `05-sam/**` | SAM build → SAM deploy |
| `frontend.yml` | `06-frontend/**` | npm build → S3 sync → CloudFront 무효화 |

### 평가 게이트 (Strands Evals)

에이전트 코드 변경 시 **품질 검증을 통과해야만 배포**됩니다.

| 테스트 케이스 | 검증 내용 |
|--------------|-----------|
| 이탈리안 추천 | `search_restaurants` 호출 + "트라토리아" 포함 |
| 메뉴 조회 | `get_menu` 호출 + "갈비" 포함 |
| 조용한 일식당 | `search_restaurants` 호출 + "오마카세" 포함 |

- 3개 케이스 평균 점수 **≥ 0.7**: PASS → 배포 진행
- 3개 케이스 평균 점수 **< 0.7**: FAIL → 배포 차단 (프로덕션 보호)

### GitHub Secrets 설정

```
Settings → Secrets and variables → Actions에 등록:

- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_SESSION_TOKEN        ← 워크샵/임시 자격증명 사용 시 필수
```

### 자격증명 만료 시 갱신 방법

워크샵/임시 계정은 자격증명이 주기적으로 만료됩니다. 만료 시 Actions에서 아래 오류가 발생합니다:
```
Error: The security token included in the request is expired
```

**갱신 절차:**

1. 워크샵 포털에서 새 자격증명 발급
2. 로컬 환경 갱신:
```bash
# ~/.aws/credentials 파일 업데이트
aws configure
# 또는 직접 편집: ~/.aws/credentials
```
3. GitHub Secrets 갱신:
```
GitHub 레포 → Settings → Secrets and variables → Actions
→ AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN 세 개 모두 Update
```
4. 실패한 워크플로우 재실행:
```
GitHub Actions → 실패한 워크플로우 → Re-run failed jobs
```

### 사용 예시

```bash
# 에이전트 시스템 프롬프트 수정
git add 02-agent/
git commit -m "에이전트: 추천 톤 변경"
git push origin main
# → agent.yml만 실행: 평가 통과 시에만 배포

# 프론트엔드 UI 수정
git add 06-frontend/
git commit -m "채팅 UI 스타일 개선"
git push origin main
# → frontend.yml만 실행: 빌드 → S3 → CloudFront 무효화
```

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| LLM | Amazon Nova Lite (`us.amazon.nova-lite-v1:0`) |
| 임베딩 | Amazon Titan Embed V2 (1024차원) |
| 벡터 DB | OpenSearch Serverless (VECTORSEARCH) |
| RAG | Bedrock Knowledge Base |
| 에이전트 프레임워크 | Strands Agents SDK |
| 도구 프로토콜 | MCP (Model Context Protocol, stdio) |
| 에이전트 런타임 | Bedrock AgentCore Runtime |
| 메모리 | AgentCore Memory (USER_PREFERENCE + SEMANTIC) |
| 웹 검색 | AgentCore Web Search Gateway (us-east-1) |
| 백엔드 | Lambda Python 3.12 + API Gateway (SAM) |
| 프론트엔드 | React 18 + Cloudscape Design System |
| 호스팅 | CloudFront + S3 (OAC) |
| CI/CD | GitHub Actions (경로 필터 + 평가 게이트) |
| IaC | CloudFormation + AgentCore CDK + SAM |

---

## 현재 상태 & 로드맵

### 현재 배포 상태

| 환경 | 기능 | 상태 |
|------|------|------|
| **프로덕션** (CloudFront → Lambda → Runtime) | KB 검색 + MCP(예약/비용) + Memory + Web Search 풀기능 | ✅ 배포 중 |
| **로컬** (Streamlit, `03-app/`) | KB + MCP(예약/비용) + Memory + Web Search 풀기능 | ✅ 동작 |

### 최근 주요 변경 (2026-08-05)

- **Runtime 풀기능화**: `main.py`에 MCP(예약/비용), Memory, Web Search Gateway 통합
- **프론트엔드 업그레이드**: 다중 세션 관리, 도구 호출 로그, Memory 현황, 식당 카드 UI
- **Lambda 개선**: session_id/actor_id/conversation_context 전달, tool_calls 반환
- **평가 게이트 확장**: 예약/비용 케이스 추가 (총 5케이스)
- **setup.sh 개선**: Gateway/Memory ID를 main.py에도 자동 반영
- **Memory 버그 수정**: API 응답 키 `memoryRecords` → `memoryRecordSummaries` 수정

### 로드맵

| 순서 | 작업 | 설명 |
|------|------|------|
| 1 | 프로덕션 풀기능 테스트 | CloudFront URL에서 예약/Memory/WebSearch 동작 확인 |
| 2 | Memory 임계값 최적화 | `test_memory_threshold.py`로 중복 감지 임계값 조정 |
| 3 | eval 임계값 최적화 | `test_eval_threshold.py`로 배포 기준점 검증 |
| 4 | Gateway 보안 강화 | 현재 `authorizer-type: NONE` → `AWS_IAM`으로 전환 |

---

## 알려진 이슈

| 상태 | 이슈 | 현황 / 우회 |
|------|------|-------------|
| ✅ | Memory `memoryRecords` → `memoryRecordSummaries` | API 응답 키 변경으로 항상 0건 반환되던 문제 수정 완료 |
| ✅ | `runtimeSessionId` 최소 33자 요구사항 | Frontend + Lambda 패딩 처리로 해결 |
| ✅ | RUNTIME_ARN SSM 저장 시 문자열 잘림 | AWS CLI 직접 조회로 변경하여 해결 |
| ✅ | CDK 배포 시 Memory/Gateway 충돌 | agentcore.json에서 제거, CLI로 별도 관리 |
| 🟡 | Gateway 보안 | 현재 `authorizer-type: NONE`. 프로덕션 전환 시 `AWS_IAM`으로 변경 필요 |
| 🟡 | `<thinking>` 태그 노출 | Runtime 응답에 추론 과정 포함됨. Lambda 및 app.py에서 필터링 처리 중 |
| 🟡 | MCP 예약 데이터 휘발 | mcp_server.py의 예약 데이터는 메모리 기반 → Runtime 재시작 시 초기화됨 (데모용) |
| 🟡 | Web Search | 워크샵 계정에서 web-search 커넥터 미지원. Gateway 없이 동작 |

---

## 참고사항

- Web Search Gateway는 **us-east-1 전용** (cross-region 호출)
- AgentCore Memory 인덱싱에 최대 10분 소요
- SAM 최초 배포 시 `--guided` 사용 → `samconfig.toml`에 설정 저장
- 워크샵/임시 계정 사용 시 GitHub Secrets에 `AWS_SESSION_TOKEN` 등록 필요
- 문제 발생 시 `TROUBLESHOOTING.md` 및 `MANUAL-SETUP.md` 참조
