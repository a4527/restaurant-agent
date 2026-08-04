import sys, json
data = json.load(sys.stdin)
ready = [r['agentRuntimeArn'] for r in data.get('agentRuntimes', []) if r.get('status') == 'READY']
print(ready[0] if ready else '')
