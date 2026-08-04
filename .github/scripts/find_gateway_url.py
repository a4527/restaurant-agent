import sys, json
data = json.load(sys.stdin)
for g in data.get('items', []):
    if g.get('name') == 'dining-web-search':
        # endpoint 필드가 있으면 사용, 없으면 gatewayId로 URL 조합
        endpoint = g.get('endpoint', '')
        if endpoint:
            print(endpoint + '/mcp')
        else:
            gid = g.get('gatewayId', '')
            if gid:
                print(f'https://{gid}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp')
        break
