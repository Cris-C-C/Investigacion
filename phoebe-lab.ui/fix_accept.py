import re

with open('ui/phoebe_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Remove the invalid `accept` argument
code = code.replace("accept='.txt,.csv,.dat',", "")

# 2. Add `.props('accept=".txt,.csv,.dat"')` before `.classes('w-full border-2...`
target_str = ".classes('w-full border-2 border-dashed border-gray-300 rounded-lg p-8 text-center')"
replacement = ".props('accept=\".txt,.csv,.dat\"')" + target_str

code = code.replace(target_str, replacement)

with open('ui/phoebe_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed ui.upload accept property.")
