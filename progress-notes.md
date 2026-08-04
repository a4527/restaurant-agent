# DiningConcierge 프로젝트 진행 기록

> AWS Bedrock AgentCore 기반 강남 식당 추천 AI 에이전트 — 풀스택 구축 과정
> 리전: us-west-2 | 마지막 업데이트: 2026-08-04

---

## 전체 아키텍처

```
사용자 (브라우저)
  ↓
CloudFront → S3 (React 정적 파일)
  ↓ POST /chat
API Gateway → Lambda (프록시)
  ↓
AgentCore Runtime (풀기능 에이전트)
  ├─ search_restaurants → Bedrock KB (OpenSearch Serverless)
  ├─ get_menu → Bedrock KB
  ├─ MCP 서버 → 예약/비용 도구
  ├─ Web Search Gateway (us-east-1)
  └─ Memory (취향 저장/검색)
  ↓
Bedrock Nova Lite → 응답 생성
```

---

## STEP 1 — 인프라 + Knowledge Base 구축

### 무엇을 했나
- **CloudFormation**으로 기반 인프라 배포: S3 버킷 2개 + IAM 역할 2개
- **OpenSearch Serverless** 컬렉션 생성 (VECTORSEARCH 타입)
  - 암호화/네트워크/데이터접근 정책 3종 설정
  - 벡터 인덱스 생성 (1024차원, faiss/hnsw)
- **Bedrock Knowledge Base** 생성
  - Titan Embed V2로 식당 문서 8개 임베딩
  - S3 → 청킹 → 임베딩 → OpenSearch 저장 (Ingestion)
- 메타데이터 필터링 (카테고리/가격대), 하이브리드 검색, 리랭킹 비교 테스트

### 왜 필요한가
- RAG의 근간: 에이전트가 식당 정보를 검색할 수 있는 벡터 DB가 있어야 함
- Knowledge Base가 S3 문서를 자동으로 청킹+임베딩하여 관리형 RAG 파이프라인 제공
- OpenSearch Serverless는 인프라 관리 없이 벡터 검색 가능

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| AWS 콘솔 → S3 → `dining-kb-data-*` | `restaurant-docs/` 폴더 내 17개 파일 목록 |
| AWS 콘솔 → OpenSearch Serverless → Collections | 컬렉션 ACTIVE 상태 |
| AWS 콘솔 → Bedrock → Knowledge Bases | KB 상태 Active + Sync 완료 |
| AWS 콘솔 → Bedrock → KB → Test | 테스트 질문 + 검색 결과 화면 |
| 터미널 | `setup-kb.sh` 실행 결과 (KB ID 출력) |

---

## STEP 2 — Strands Agent 개발 + 도구 통합

### 무엇을 했나
- **Strands Agents SDK**로 AI 에이전트 개발
  - `search_restaurants`: KB 벡터 검색 (카테고리 필터 포함)
  - `get_menu`: 특정 식당 메뉴/가격 조회
- **MCP 서버** (Model Context Protocol) 구현
  - `check_reservation`: 예약 가능 여부 조회
  - `create_reservation`: 예약 생성
  - `estimate_cost`: 인원/메뉴별 비용 산정
- 에이전트가 질문에 따라 도구를 자동 선택+체이닝
  - 예: "이탈리안 추천 → 예산 확인 → 예약" = 3개 도구 순차 호출

### 왜 필요한가
- LLM 단독으로는 실시간 데이터(식당 정보, 예약 현황)에 접근 불가
- 도구(Tool Use)를 통해 에이전트가 외부 시스템과 상호작용
- MCP는 도구를 별도 서버로 분리하여 독립적으로 개발/배포 가능

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| 터미널 | 에이전트 실행 → 도구 호출 로그 (search → menu → reservation 체이닝) |
| Streamlit 앱 | 채팅 화면 + 사이드바 도구 호출 로그 |
| Streamlit 앱 | 식당 카드 UI (이름/카테고리/가격/위치/분위기) |
| 코드 | `tools.py`, `mcp_server.py` 핵심 부분 하이라이트 |

---

## STEP 3 — AgentCore Runtime 배포

### 무엇을 했나
- **AgentCore CLI**로 에이전트를 관리형 런타임에 배포
  - `agentcore create` → CDK 프로젝트 생성
  - `agentcore deploy --yes` → CloudFormation 스택 → Runtime READY
- 코드 패키징: `pyproject.toml` 의존성 + `main.py` 엔트리포인트
- Runtime이 자동 스케일링 + HTTPS 엔드포인트 제공

### 왜 필요한가
- 로컬 에이전트를 프로덕션 환경에서 안정적으로 서빙
- 서버 관리 없이 AgentCore가 인프라 자동 처리 (스케일링, 모니터링)
- Lambda, Streamlit 등 어디서든 Runtime을 호출 가능

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| 터미널 | `npx @aws/agentcore deploy --yes` 실행 결과 |
| 터미널 | `npx @aws/agentcore status` → READY 상태 + ARN |
| AWS 콘솔 → Bedrock → AgentCore → Runtimes | Runtime 상세 화면 |

---

## STEP 4 — Memory + Web Search Gateway

### 무엇을 했나
- **AgentCore Memory** 생성
  - 전략: USER_PREFERENCE + SEMANTIC
  - 사용자 취향 자동 저장 ("매운 거 좋아해" → 기억)
  - 다음 대화에서 취향 반영한 추천
- **Web Search Gateway** 생성 (us-east-1)
  - MCP 프로토콜 기반 웹 검색 게이트웨이
  - 실시간 정보 필요 시 자동 호출 (날씨, 이벤트, 최신 뉴스)
  - Streamlit 앱에서 직접 호출 → prompt 주입 방식

### 왜 필요한가
- **Memory**: 대화 맥락 유지 + 개인화. 매번 취향을 반복 입력하지 않아도 됨
- **Web Search**: KB에 없는 실시간 정보(영업시간 변경, 주변 이벤트 등) 보완
- 두 기능 모두 에이전트의 답변 품질을 크게 향상시킴

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| AWS 콘솔 → AgentCore → Memory | Memory 상세 (전략, 상태) |
| AWS 콘솔 → AgentCore → Gateways (us-east-1) | Gateway READY 상태 |
| Streamlit 앱 | 취향 저장 후 다음 대화에서 반영된 추천 결과 |
| Streamlit 앱 | 웹 검색 결과가 포함된 답변 (예: "강남역 주변 축제") |

---

## STEP 5 — SAM API (서버리스 백엔드)

### 무엇을 했나
- **AWS SAM**으로 Lambda + API Gateway 배포
  - Lambda: AgentCore Runtime 프록시 (직접 에이전트 실행 X)
  - `POST /chat` → Lambda → `invoke_runtime()` → Runtime → 응답
- 권한: `bedrock-agentcore:InvokeRuntime`
- CORS 설정: 프론트엔드에서 직접 API 호출 가능

### 왜 필요한가
- 브라우저에서 AgentCore Runtime을 직접 호출하려면 AWS 자격증명 필요 → 불가능
- Lambda가 프록시 역할: 프론트 → (공개 API) → Lambda → (IAM 인증) → Runtime
- SAM으로 선언형 배포: `template.yaml` 하나로 Lambda + API Gateway + IAM 자동 구성

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| 터미널 | `sam build && sam deploy` 결과 (API URL 출력) |
| 터미널 | `curl -X POST .../chat -d '{"message":"이탈리안 추천"}` 테스트 결과 |
| AWS 콘솔 → API Gateway | REST API 리소스 (`/chat` POST) |
| AWS 콘솔 → Lambda | 함수 설정 (환경변수 RUNTIME_ARN) |

---

## STEP 6 — React 프론트엔드 + CloudFront

### 무엇을 했나
- **React + Cloudscape Design System** 채팅 UI
  - `ChatBubble`, `Avatar` 컴포넌트 (AWS 공식 디자인)
  - 실시간 로딩 인디케이터
  - 반응형 레이아웃
- **CloudFront + S3** 정적 호스팅
  - OAC(Origin Access Control)로 S3 직접 접근 차단
  - SPA 라우팅: 403/404 → `/index.html` 리다이렉트
  - HTTPS 자동 (CloudFront 기본 인증서)
- `setup.sh --frontend`로 빌드 → S3 업로드 → CloudFront 생성 자동화

### 왜 필요한가
- 사용자가 접근하는 최종 인터페이스
- CloudFront: 글로벌 CDN으로 빠른 응답 + HTTPS + S3 직접 노출 방지
- Cloudscape: AWS 콘솔과 동일한 UI 일관성 + 접근성(a11y) 기본 지원

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| 브라우저 | CloudFront URL 접속 → 채팅 화면 (초기 상태) |
| 브라우저 | 대화 진행 중 화면 (사용자 + AI 메시지) |
| 브라우저 | 로딩 인디케이터 표시 상태 |
| AWS 콘솔 → CloudFront | Distribution 상태 (Enabled, Domain) |
| AWS 콘솔 → S3 → `dining-frontend-*` | 빌드 파일 목록 |

---

## STEP 7 — CI/CD (GitHub Actions)

### 무엇을 했나
- **GitHub Actions 워크플로우 3개** (경로별 자동 배포)
  - `agent.yml`: `02-agent/**` 변경 → Strands Evals 평가 → AgentCore deploy
  - `api.yml`: `05-sam/**` 변경 → SAM build → SAM deploy
  - `frontend.yml`: `06-frontend/**` 변경 → npm build → S3 sync → CloudFront 무효화
- **Strands Evals 평가 게이트** (`eval_gate.py`)
  - 3개 테스트 케이스 (도구 호출 + 응답 내용 검증)
  - 평균 0.7 미만 시 배포 차단
- 모노레포 구조: 한 번의 `git push`로 변경된 부분만 자동 배포

### 왜 필요한가
- 수동 배포 실수 방지 + 코드 변경 → 배포 자동화
- 평가 게이트: 에이전트 품질이 떨어지면 프로덕션에 나가지 않도록 방어
- 경로 필터: 프론트엔드만 고쳐도 에이전트가 재배포되지 않음 (독립 파이프라인)

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| GitHub → Actions 탭 | 3개 워크플로우 목록 |
| GitHub → Actions → agent.yml 실행 | evaluate → deploy 스테이지 통과 |
| GitHub → Actions → frontend.yml 실행 | build → S3 sync → invalidate 통과 |
| GitHub → repo Settings → Secrets | AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY 등록 화면 |
| 터미널 | `git push` 후 워크플로우 자동 트리거 확인 |

---

## STEP 8 — 전체 자동화 (`setup.sh --all`)

### 무엇을 했나
- **원커맨드 재현 스크립트** 완성
  - 새 AWS 계정에서 `./setup.sh --all` 한 번으로 전체 인프라 구축
  - 모든 ID/ARN/URL이 자동으로 코드에 반영 (수동 설정 0개)
- **멱등성 보장**: 이미 존재하는 리소스는 건너뛰고 재사용
- 단계별 선택 실행 가능: `--kb`, `--agent`, `--sam`, `--frontend` 등

### 자동화된 항목
| 항목 | 이전 | 현재 |
|------|------|------|
| OpenSearch 컬렉션 | 수동 콘솔 생성 | 스크립트 자동 생성 + ACTIVE 대기 |
| KB_ID → 코드 반영 | 수동 복붙 | `sed`로 자동 |
| RUNTIME_ARN → 코드 반영 | 수동 복붙 | `agentcore status` 파싱 → 자동 |
| Memory 생성 | 대화형 CLI | `--name --strategies` 비대화형 |
| Web Search Gateway | 수동 콘솔 | `agentcore add gateway` 자동 |
| CloudFront | 콘솔에서 수동 | CLI로 자동 생성 (OAC + 버킷 정책 포함) |
| CI/CD | CodePipeline + CodeBuild | GitHub Actions (AWS 리소스 불필요) |

### 왜 필요한가
- 재현성: 워크샵/데모에서 다른 계정으로 즉시 재현
- 온보딩: 새 팀원이 `./setup.sh --all` 한 번으로 전체 환경 구축
- 유지보수: 인프라를 코드로 관리 (IaC)

### 📸 필요한 캡처
| 위치 | 캡처 내용 |
|------|-----------|
| 터미널 | `./setup.sh --all` 전체 실행 로그 (주요 단계 출력) |
| 터미널 | 최종 "✅ 설정 완료!" 메시지 |
| 브라우저 | CloudFront URL에서 정상 동작하는 채팅 화면 |

---

## 현재 리소스 현황

| 리소스 | ID / 이름 | 리전 |
|--------|-----------|------|
| S3 (KB data) | `dining-kb-data-678498164624` | us-west-2 |
| S3 (Frontend) | `dining-frontend-678498164624` | us-west-2 |
| OSS 컬렉션 | `dining-kb-collection` (`wcuhxgd2o1syxk3axwnb`) | us-west-2 |
| Knowledge Base | `LOAIJ2HJXE` | us-west-2 |
| AgentCore Runtime | `DiningConcierge_DiningConcierge-aLEpSdHOiw` | us-west-2 |
| SAM Stack | `dining-sam-api` | us-west-2 |
| CloudFront | `d2x89fcv3dzcu5.cloudfront.net` | Global |
| IAM 역할 | `dining-kb-role`, `dining-gateway-role` | Global |

---

## 기술 스택 요약

| 레이어 | 기술 |
|--------|------|
| LLM | Amazon Nova Lite (`us.amazon.nova-lite-v1:0`) |
| 임베딩 | Amazon Titan Embed V2 (1024차원) |
| 벡터 DB | OpenSearch Serverless (VECTORSEARCH) |
| RAG | Bedrock Knowledge Base |
| 에이전트 | Strands Agents SDK |
| 도구 프로토콜 | MCP (Model Context Protocol) |
| 런타임 | Bedrock AgentCore Runtime |
| 메모리 | AgentCore Memory (USER_PREFERENCE + SEMANTIC) |
| 웹 검색 | AgentCore Web Search Gateway |
| 백엔드 | Lambda (Python 3.12) + API Gateway (SAM) |
| 프론트엔드 | React + Cloudscape Design System |
| 호스팅 | CloudFront + S3 (OAC) |
| CI/CD | GitHub Actions (경로 필터 + Strands Evals 게이트) |
| IaC | CloudFormation + AgentCore CDK + SAM |

---

*마지막 업데이트: 2026-08-04*
