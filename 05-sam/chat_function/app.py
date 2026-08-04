import json
import os
import re
import boto3


RUNTIME_ARN = os.environ.get("RUNTIME_ARN", "")
REGION = os.environ.get("AWS_REGION", "us-west-2")

agentcore_client = boto3.client("bedrock-agentcore", region_name=REGION)


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def lambda_handler(event, context):
    # CORS preflight
    if event.get("httpMethod", "") == "OPTIONS":
        return build_response(200, {"message": "OK"})

    if not RUNTIME_ARN:
        return build_response(500, {"error": "RUNTIME_ARN 환경변수가 설정되지 않았습니다."})

    try:
        body = json.loads(event.get("body", "{}"))
        message = body.get("message", "")
        session_id = body.get("session_id", "default-session")
        actor_id = body.get("actor_id", "anonymous")
        conversation_context = body.get("conversation_context", "")

        # runtimeSessionId 최소 33자 요구사항 충족
        if len(session_id) < 33:
            session_id = session_id + "-" + "0" * (33 - len(session_id) - 1)

        if not message:
            return build_response(400, {"error": "message field is required"})

        # AgentCore Runtime 호출
        payload = {
            "prompt": message,
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

        # SSE 파싱 — 텍스트 + 도구 호출
        reply_parts = []
        tool_calls = []
        tool_counter = 0

        for line in stream_data.split("\n"):
            if not line.startswith("data: "):
                continue
            try:
                event_data = json.loads(line[6:])
                evt = event_data.get("event", {})

                # 텍스트
                text = evt.get("contentBlockDelta", {}).get("delta", {}).get("text", "")
                if text:
                    reply_parts.append(text)

                # 도구 호출
                tool_use = evt.get("contentBlockStart", {}).get("start", {}).get("toolUse")
                if tool_use:
                    tool_counter += 1
                    tool_calls.append({
                        "order": tool_counter,
                        "name": tool_use.get("name", "unknown"),
                        "input": {},
                    })

                # 도구 입력 파라미터
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

        # <thinking> 태그 제거
        reply = re.sub(r"<thinking>.*?</thinking>\n?", "", reply, flags=re.DOTALL)

        # 응답 내용에서 도구 호출 키워드 감지 (fallback)
        if not tool_calls:
            if "search_restaurants" in stream_data:
                tool_calls.append({"order": 1, "name": "search_restaurants", "input": {}})
            if "get_menu" in stream_data:
                tool_calls.append({"order": len(tool_calls)+1, "name": "get_menu", "input": {}})
            if "check_reservation" in stream_data:
                tool_calls.append({"order": len(tool_calls)+1, "name": "check_reservation", "input": {}})
            if "create_reservation" in stream_data:
                tool_calls.append({"order": len(tool_calls)+1, "name": "create_reservation", "input": {}})
            if "estimate_cost" in stream_data:
                tool_calls.append({"order": len(tool_calls)+1, "name": "estimate_cost", "input": {}})

        return build_response(200, {
            "reply": reply.strip() or "응답을 생성하지 못했습니다.",
            "tool_calls": tool_calls,
            "session_id": session_id,
        })

    except Exception as e:
        print(f"Error: {str(e)}")
        return build_response(500, {"error": str(e)})
