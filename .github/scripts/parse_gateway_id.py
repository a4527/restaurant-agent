import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('gatewayId', ''))
except Exception:
    print('')
