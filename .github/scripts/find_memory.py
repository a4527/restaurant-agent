import sys, json
data = json.load(sys.stdin)
found = [m['id'] for m in data.get('memories', [])
         if 'dining' in m.get('name', '').lower() and m.get('status') == 'ACTIVE']
print(found[0] if found else '')
