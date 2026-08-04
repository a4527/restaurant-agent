import json
import os
import boto3


RUNTIME_ARN = os.environ.get(
    "RUNTIME_ARN",
    "arn:aws:bedrock-agentcore:us-west-2:678498164624:runtime/DiningConcierge_DiningConcierge-aLEpSdHOiw",
)
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
    # Handle CORS preflight
    http_method = event.get("httpMethod", "")
    if http_method == "OPTIONS":
        return build_response(200, {"message": "OK"})

    try:
        body = json.loads(event.get("body", "{}"))
        message = body.get("message", "")
        session_id = body.get("session_id", "default")

        if not message:
            return build_response(400, {"error": "message field is required"})

        # AgentCore Runtime 호출
        response = agentcore_client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            payload=json.dumps({
                "prompt": message,
            }).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )

        # 스트리밍 응답 파싱 (text/event-stream)
        stream_data = response["response"].read().decode("utf-8")

        # SSE 형식에서 텍스트 추출
        reply_parts = []
        for line in stream_data.split("\n"):
            if line.startswith("data: "):
                try:
                    event_data = json.loads(line[6:])
                    # contentBlockDelta에서 텍스트 추출
                    delta = event_data.get("event", {}).get("contentBlockDelta", {})
                    text = delta.get("delta", {}).get("text", "")
                    if text:
                        reply_parts.append(text)
                    # 에러 체크
                    if "error" in event_data:
                        reply_parts.append(event_data["error"])
                except json.JSONDecodeError:
                    pass

        reply = "".join(reply_parts) if reply_parts else "응답을 생성하지 못했습니다."

        return build_response(200, {"reply": reply})

    except Exception as e:
        print(f"Error: {str(e)}")
        return build_response(500, {"error": str(e)})
