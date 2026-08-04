# 수동 설정 가이드

> `./setup.sh --all` 실행 시 아래 항목이 **모두 자동으로 설정됩니다.**
> 이 문서는 트러블슈팅이나 개별 재실행 시 참고용입니다.

---

## 자동 설정 항목 (setup.sh가 처리)

| # | 항목 | 반영 파일 |
|---|------|-----------|
| 1 | KB_ID | `03-app/tools.py`, `02-agent/app/DiningConcierge/tools.py` |
| 2 | RUNTIME_ARN | `03-app/app.py`, `05-sam/template.yaml` |
| 3 | MEMORY_ID | `03-app/app.py` |
| 4 | GATEWAY_WEB_SEARCH_URL | `03-app/app.py` |
| 5 | CloudFront Distribution | 자동 생성 + `06-frontend/cloudfront-url.txt` |

---

## 트러블슈팅: Web Search Gateway

Gateway는 `setup.sh`에서 AgentCore CLI로 자동 생성됩니다.  
수동으로 확인/재생성이 필요한 경우:

```bash
cd 02-agent

# Gateway 상태 확인
npx @aws/agentcore status

# 수동 추가 (이미 있으면 에러 무시)
npx @aws/agentcore add gateway \
  --name dining-web-search \
  --protocol-type MCP \
  --authorizer-type NONE

npx @aws/agentcore add gateway-target \
  --name web-search \
  --gateway dining-web-search \
  --type connector \
  --connector web-search

npx @aws/agentcore deploy --yes
```

---

## 트러블슈팅: Memory

Memory도 `setup.sh`에서 자동 생성됩니다.  
수동으로 확인/재생성이 필요한 경우:

```bash
cd 02-agent

# Memory 상태 확인
npx @aws/agentcore status

# 수동 추가
npx @aws/agentcore add memory \
  --name dining_memory \
  --strategies USER_PREFERENCE,SEMANTIC \
  --expiry 30

npx @aws/agentcore deploy --yes
```

### Memory 인덱싱 지연 이슈

**현상**: `batch_create_memory_records` 후 `retrieve_memory_records`에서 0건 반환  
**원인**: 벡터 인덱싱에 시간 소요 (최대 10분)  
**우회**: `03-app/app.py`에서 `get_memory_record`로 직접 조회 후 prompt 주입 방식 사용 중

---

## 트러블슈팅: Runtime ARN / Memory ID 추출 실패

`setup.sh`가 자동 추출에 실패하면 수동으로:

```bash
# Runtime ARN 확인
npx @aws/agentcore status
# → "arn:aws:bedrock-agentcore:us-west-2:ACCOUNT:runtime/..."

# 03-app/app.py에 직접 반영
sed -i 's|RUNTIME_ARN = ".*"|RUNTIME_ARN = "YOUR_ARN"|' 03-app/app.py
```
