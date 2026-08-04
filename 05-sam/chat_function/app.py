import json
import os
import re
import boto3


RUNTIME_ARN = os.environ.get("RUNTIME_ARN", "")
MEMORY_ID = os.environ.get("MEMORY_ID", "")
REGION = os.environ.get("AWS_REGION", "us-west-2")

agentcore_client = boto3.client("bedrock-agentcore", region_name=REGION)


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def get_memory_context(actor_id: str, query: str) -> str:
    """Memory에서 취향 조회 → prompt 주입용 컨텍스트 반환"""
    if not MEMORY_ID:
        return ""
    try:
        prefs = []
        for ns in [f"/users/{actor_id}/preferences", f"/users/{actor_id}/facts"]:
            resp = agentcore_client.retrieve_memory_records(
                memoryId=MEMORY_ID,
                namespace=ns,
                searchCriteria={"searchQuery": query, "topK": 5}
            )
            for r in resp.get("memoryRecordSummaries", []):
                text = r.get("content", {}).get("text", "")
                if text and text not in prefs:
                    prefs.append(text)
        if prefs:
            return "[사용자 취향 정보]\n" + "\n".join(f"- {p}" for p in prefs) + "\n\n위 취향을 반드시 반영하여 답변하세요.\n\n"
    except Exception as e:
        print(f"Memory 조회 오류: {e}")
    return ""


def get_memory_status(actor_id: str) -> dict:
    """Memory 현황 조회 (취향 + 사실)"""
    if not MEMORY_ID:
        return {"preferences": [], "facts": [], "error": "MEMORY_ID not configured"}
    result = {"preferences": [], "facts": []}
    try:
        for ns_type in ["preferences", "facts"]:
            resp = agentcore_client.retrieve_memory_records(
                memoryId=MEMORY_ID,
                namespace=f"/users/{actor_id}/{ns_type}",
                searchCriteria={"searchQuery": "취향 선호 사실", "topK": 20}
            )
            for r in resp.get("memoryRecordSummaries", []):
                text = r.get("content", {}).get("text", "")
                if text:
                    result[ns_type].append(text)
    except Exception as e:
        result["error"] = str(e)
    return result


def lambda_handler(event, context):
    http_method = event.get("httpMethod", "")
    path = event.get("path", "")

    # CORS preflight
    if http_method == "OPTIONS":
        return build_response(200, {"message": "OK"})

    # ── GET /memory?actor_id=xxx ──────────────────────
    if http_method == "GET" and path == "/memory":
        params = event.get("queryStringParameters") or {}
        actor_id = params.get("actor_id", "anonymous")
        return build_response(200, get_memory_status(actor_id))

    # ── POST /chat ────────────────────────────────────
    if not RUNTIME_ARN:
        return build_response(500, {"error": "RUNTIME_ARN 환경변수가 설정되지 않았습니다."})

    try:
        body = json.loads(event.get("body", "{}"))
        message = body.get("message", "")
        session_id = body.get("session_id", "default-session")
        actor_id = body.get("actor_id", "anonymous")
        conversation_context = body.get("conversation_context", "")

        # runtimeSessionId 최소 33자 요구사항
        if len(session_id) < 33:
            session_id = session_id + "-" + "0" * (33 - len(session_id) - 1)

        if not message:
            return build_response(400, {"error": "message field is required"})

        # Memory에서 취향 조회 → prompt에 주입
        memory_context = get_memory_context(actor_id, message)

        payload = {
            "prompt": memory_context + conversation_context + message,
            "session_id": session_id,
            "actor_id": actor_id,
        }
        if conversation_context:
            payload["conversation_context"] = conversation_context

        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            payload=json.dumps(payload).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
            runtimeSessionId=session_id,
        )

        stream_data = response["response"].read().decode("utf-8")

        reply_parts = []
        tool_calls = []
        tool_counter = 0

        for line in stream_data.split("\n"):
            if not line.startswith("data: "):
                continue
            try:
                event_data = json.loads(line[6:])
                evt = event_data.get("event", {})

                text = evt.get("contentBlockDelta", {}).get("delta", {}).get("text", "")
                if text:
                    reply_parts.append(text)

                tool_use = evt.get("contentBlockStart", {}).get("start", {}).get("toolUse")
                if tool_use:
                    tool_counter += 1
                    tool_calls.append({
                        "order": tool_counter,
                        "name": tool_use.get("name", "unknown"),
                        "input": {},
                    })

                tool_delta = evt.get("contentBlockDelta", {}).get("delta", {}).get("toolUse", {})
                if tool_delta and tool_calls:
                    try:
                        inp = json.loads(tool_delta.get("input", "{}"))
                        tool_calls[-1]["input"] = inp
                    except Exception:
                        pass

            except json.JSONDecodeError:
                pass

        reply = "".join(reply_parts)
        reply = re.sub(r"<thinking>.*?</thinking>\n?", "", reply, flags=re.DOTALL)

        # fallback 도구 감지
        if not tool_calls:
            for tool_name in ["search_restaurants", "get_menu", "check_reservation", "create_reservation", "estimate_cost"]:
                if tool_name in stream_data:
                    tool_calls.append({"order": len(tool_calls)+1, "name": tool_name, "input": {}})

        return build_response(200, {
            "reply": reply.strip() or "응답을 생성하지 못했습니다.",
            "tool_calls": tool_calls,
            "session_id": session_id,
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return build_response(500, {"error": str(e)})
