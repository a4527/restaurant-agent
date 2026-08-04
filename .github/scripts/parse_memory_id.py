import sys, json
try:
    data = json.load(sys.stdin)
    print(data['memory']['id'])
except Exception:
    print('')
