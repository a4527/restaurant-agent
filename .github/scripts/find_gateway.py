import sys, json
data = json.load(sys.stdin)
found = [g['id'] for g in data.get('items', []) if g.get('name') == 'dining-web-search']
print(found[0] if found else '')
