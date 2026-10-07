import re

with open('ui/phoebe_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace any sequence of whitespaces and commas that ends up as double commas or comma-newline-comma
# Specifically, we know the damage looks like:
#                adjust=True,
#            ,
#                on_value_changed=self.compute_and_plot)

# Let's just use regex to replace all occurrences of `,\s*,\s*on_value_changed` with `,\n                on_value_changed`
code = re.sub(r',\s*,\s*on_value_changed', ',\n                on_value_changed', code)

with open('ui/phoebe_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed syntax errors.")
