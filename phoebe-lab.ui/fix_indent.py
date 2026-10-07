import re

with open('ui/phoebe_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

code = code.replace(
    "#         api=self.phoebe_api,\n                        on_value_changed=self.compute_and_plot",
    "#         api=self.phoebe_api,\n                #         on_value_changed=self.compute_and_plot"
)

with open('ui/phoebe_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed indentation.")
