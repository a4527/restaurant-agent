# 트러블슈팅 로그

> 프로젝트 진행 중 발생한 이슈와 해결 방법 기록

---

## 1. setup-kb.sh에서 `collectionArn: "AUTO"` 미지원

**증상**: `setup.sh --all` 실행 시 "=== 2. Knowledge Base 생성 ===" 출력 후 멈춤  
**원인**: `create-knowledge-base` API의 `collectionArn: "AUTO"` 옵션이 해당 계정/리전에서 지원되지 않음  
**에러**: `ValidationException: Value 'AUTO' failed to satisfy constraint: Member must satisfy regular expression pattern: arn:aws...`  
**해결**: `setup-kb.sh` 재작성 — OpenSearch Serverless 컬렉션을 수동으로 생성 (policies → collection → vector index → KB)

---

## 2. setup-kb.sh에서 KB 생성 실패 → `read -p` 대기

**증상**: KB 생성 실패 후 스크립트가 hang  
**원인**: 실패 시 `read -p "KB ID: "` 프롬프트에서 사용자 입력 대기  
**해결**: `read -p` 제거, 실패 시 `exit 1`로 즉시 종료하도록 변경

---

## 3. `dining-kb-role`에 aoss 권한 누락

**증상**: KB 생성 시 `security_exception 403 Forbidden`  
**원인**: IAM 역할에 `aoss:APIAccessAll` 권한이 없음  
**해결**: 
- `00-infra.yaml`에 `kb-aoss-access` 정책 추가
- 기존 환경: `aws iam put-role-policy`로 즉시 추가

---

## 4. SAM CLI 미설치

**증상**: `./setup.sh: line 115: sam: command not found`  
**해결**: `pip install aws-sam-cli --break-system-packages`

---

## 5. samconfig.toml `version` 키 누락

**증상**: SAM deploy 시 `SamConfigVersionException: 'version' key is not present`  
**해결**: `samconfig.toml` 맨 위에 `version = 0.1` 추가

---

## 6. Lambda `invoke_runtime` 메서드 없음

**증상**: API 호출 시 `'BedrockAgentCore' object has no attribute 'invoke_runtime'`  
**원인**: boto3의 bedrock-agentcore 클라이언트 메서드 이름이 다름  
**해결**: `invoke_runtime()` → `invoke_agent_runtime()` 변경

---

## 7. `invoke_agent_runtime` 파라미터 이름 불일치

**증상**: `'payload'` KeyError  
**원인**: 파라미터명 — `body` → `payload`, `runtimeArn` → `agentRuntimeArn`, 응답은 `response` (StreamingBody)  
**해결**: 
```python
response = client.invoke_agent_runtime(
    agentRuntimeArn=RUNTIME_ARN,
    payload=json.dumps({"prompt": message}).encode("utf-8"),
    contentType="application/json",
    accept="application/json",
)
stream_data = response["response"].read().decode("utf-8")
```

---

## 8. Runtime에서 KB 호출 시 인증 에러

**증상**: `ValidationException: The text field in the ContentBlock object is blank` (실제로는 tool 호출 실패)  
**원인**: AgentCore Runtime 실행 역할에 `bedrock:Retrieve` 권한 없음  
**해결**:
```bash
aws iam put-role-policy \
  --role-name AgentCore-DiningConcierge-ApplicationAgentDiningCon-XXX \
  --policy-name bedrock-kb-retrieve \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["bedrock:Retrieve","bedrock:InvokeModel"],"Resource":"*"}]}'
```

---

## 9. Runtime에 `prompt` vs `query` 필드

**증상**: `The text field in the ContentBlock object at messages.0.content.0 is blank`  
**원인**: Runtime `main.py`의 `_extract_prompt()`가 `messages` 또는 `prompt` 키를 기대하는데 `query`로 보냄  
**해결**: Lambda에서 payload를 `{"prompt": message}`로 변경

---

## 10. GitHub Actions — AWS 토큰 인증 실패

**증상**: `Error: The security token included in the request is invalid`  
**원인**: Workshop 임시 자격증명 사용 시 `AWS_SESSION_TOKEN`이 필요  
**해결**: 
- GitHub Secrets에 `AWS_SESSION_TOKEN` 추가
- 워크플로우에 `aws-session-token: ${{ secrets.AWS_SESSION_TOKEN }}` 추가

---

## 11. eval_gate.py `ModuleNotFoundError: No module named 'tools'`

**증상**: GitHub Actions evaluate 단계에서 import 실패  
**원인**: `sys.path`가 `04-pipeline/app/DiningConcierge/`를 가리키는데, 실제 경로는 `02-agent/app/DiningConcierge/`  
**해결**: 
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "02-agent", "app", "DiningConcierge"))
```

---

## 12. GitHub Actions — CDK synth 실패 (aarch64 플랫폼 불일치)

**증상**: `AgentCore CDK synthesis failed: uv install failed on platform aarch64-manylinux2014 with exit code null`  
**원인**: `@aws/agentcore-cdk` 라이브러리가 패키징 시 `uv`를 사용하여 aarch64 대상 wheel을 빌드함. GitHub Actions runner는 x86_64이지만, `uv`의 `--python-platform` 플래그가 cross-compilation을 처리함.

**시도 과정:**
1. **1차 시도 (실패)**: sed로 `aarch64-manylinux2014` → `x86_64-manylinux2014` 패치 적용  
   → 실패 원인: runner에 `uv`가 설치되어 있지 않아 패치와 무관하게 실패
2. **2차 시도 (실패)**: `uv` 설치 + x86_64 플랫폼 패치 적용  
   → 실패 원인: Runtime이 ARM64 환경이므로 x86 바이너리 거부 (`Your artifact contains binary files that are incompatible with Linux ARM64`)
3. **최종 해결**: `uv`만 설치하면 됨. 플랫폼 패치 불필요.  
   → `uv`는 x86_64 호스트에서도 `--python-platform` 플래그로 aarch64 cross-compilation을 정상 수행함

**해결**: 워크플로우에서 `npm ci` 전에 `uv`를 설치하기만 하면 됨
```yaml
- name: Install uv
  run: pip install uv
```
플랫폼 패치(sed)는 **적용하지 않음** — Runtime이 ARM64이므로 aarch64 바이너리가 올바른 대상임.

---

## 13. AgentCore Memory — retrieve 0건 반환 (API 응답 키 변경)

**증상**: 
- `create_event` 성공, Observability에서 `new memory extracted` 정상 증가
- `retrieve_memory_records`, `list_memory_records` 호출 시 0건 반환
- 에러 없이 빈 배열만 반환됨
- 40분 이상 대기해도 동일

**원인**: **API 응답 키 변경** — AgentCore Memory API가 업데이트되면서 응답 필드명이 변경됨
- 변경 전: `memoryRecords`
- 변경 후: `memoryRecordSummaries`

boto3 코드에서 `resp.get("memoryRecords", [])` 로 읽고 있었기 때문에 항상 빈 배열 반환. 데이터는 처음부터 정상 저장되어 있었음.

**발견 계기**: CLI 직접 호출 시 정상 반환됨을 확인
```bash
aws bedrock-agentcore retrieve-memory-records \
  --memory-id DiningConcierge_memory_v2-LQr1ybFdoo \
  --namespace "/users/user-taemin/preferences" \
  --search-criteria '{"searchQuery":"일식","topK":10}' \
  --region us-west-2
# → memoryRecordSummaries: [...] 정상 반환
```

**해결**: `memoryRecords` → `memoryRecordSummaries`로 변경 (retrieve, list 모두 동일)
```python
# 변경 전 (동작 안 함)
records = resp.get("memoryRecords", [])

# 변경 후 (정상 동작)
records = resp.get("memoryRecordSummaries", [])
```

**적용 파일**: `03-app/app.py` — `invoke_runtime`, `get_memory_status`, `search_memory` 함수 전부 수정

**추가 조치**: 
- MEMORY_ID를 정상 동작 확인된 `DiningConcierge_memory_v2-LQr1ybFdoo`로 업데이트
- execution role 없이 생성한 버전이 정상 동작 (built-in 전략은 execution role 불필요)

**상태**: ✅ 해결

---

## 14. runtimeSessionId 최소 33자 요구사항

**증상**: 프론트엔드에서 채팅 시 "응답을 생성하지 못했습니다." 표시

**Lambda 로그**:
```
Invalid length for parameter runtimeSessionId, value: 17, valid min length: 33
```

**원인**: 프론트엔드 `generateSessionId()`가 생성한 session_id가 17자로 `runtimeSessionId` 최소 33자 요구사항 미충족

**해결**:
```javascript
// Frontend App.js
function generateSessionId() {
  const a = Math.random().toString(36).slice(2, 12);
  const b = Date.now().toString(36);
  const c = Math.random().toString(36).slice(2, 12);
  return `${a}-${b}-${c}`; // 33자 이상 보장
}
```
```python
# Lambda app.py — 방어적 패딩
if len(session_id) < 33:
    session_id = session_id + "-" + "0" * (33 - len(session_id) - 1)
```

**상태**: ✅ 해결

---

## 15. RUNTIME_ARN SSM 저장 시 문자열 잘림

**증상**: Lambda 환경변수 `RUNTIME_ARN`이 `"arn:aws:bedrock-agentcore:us-west-"` 로 잘려서 저장됨

**원인**: `agent.yml`에서 `grep -oP 'arn:aws:bedrock-agentcore:[^\s)]+'` 패턴으로 파싱 시 줄 끝 문자(`\t`, `\r` 등)에 의해 ARN이 잘림

**해결**: grep 파싱 제거 → AWS CLI 직접 조회로 변경
```bash
RUNTIME_ARN=$(aws bedrock-agentcore-control list-agent-runtimes \
  --region us-west-2 \
  --query "agentRuntimes[?status=='READY'].agentRuntimeArn | [0]" \
  --output text)
```

**상태**: ✅ 해결

---

## 16. Lambda에 Memory 미연동으로 취향 반영 안 됨

**증상**: 프론트엔드에서 취향을 말해도 다음 대화에서 기억 못함

**원인**:
1. Lambda 환경변수에 `MEMORY_ID` 없음
2. Lambda 코드에 Memory 조회 → prompt 주입 로직 없음

**해결**:
- `template.yaml`에 `MemoryId` Parameter 추가
- `api.yml`에서 SSM `/dining/MEMORY_ID` 읽어서 SAM 배포 시 주입
- Lambda `app.py`에 `get_memory_context()` 함수 추가 → prompt 앞에 취향 주입
- `/memory` GET 엔드포인트 추가 → 프론트엔드에서 Memory 현황 조회 가능

**상태**: ✅ 해결

---

## 17. CDK 배포 시 Memory/Gateway 리소스 충돌

**증상**:
```
Memory is in transitional state CREATING. Cannot delete memory.
Connector integration web-search is not available for this account.
```

**원인**:
- Memory가 CREATING 중인데 CDK가 삭제 시도
- web-search 커넥터가 워크샵 계정에서 미지원

**해결**: `agentcore.json`에서 `memories`, `agentCoreGateways` 항목 제거 → CDK 외부에서 관리
- Memory: `agent.yml`에서 AWS CLI `create-memory`로 직접 생성 (멱등성 보장)
- Gateway: `agent.yml`에서 `npx @aws/agentcore add gateway`로 생성 시도, 실패해도 계속 진행

**상태**: ✅ 해결

---

*마지막 업데이트: 2026-08-05*
