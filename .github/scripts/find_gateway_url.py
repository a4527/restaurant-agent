import sys, json
data = json.load(sys.stdin)
found = [g.get('endpoint', '') + '/mcp' for g in data.get('items', [])
         if g.get('name') == 'dining-web-search' and g.get('endpoint')]
print(found[0] if found else '')
