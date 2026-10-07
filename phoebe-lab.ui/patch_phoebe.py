import re

with open('ui/phoebe_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Dataset table columns: Add filter: True to Type, Phases, Passband
def add_filter(match):
    return match.group(0).replace('}', ", 'filter': True}")

code = re.sub(r"\{'field': 'type'.*?\}", add_filter, code)
code = re.sub(r"\{'field': 'phases'.*?\}", add_filter, code)
code = re.sub(r"\{'field': 'passband'.*?\}", add_filter, code)

# 2. Add accept parameter to ui.upload
code = code.replace(
    "on_upload=self._on_file_uploaded,",
    "on_upload=self._on_file_uploaded,\n                            accept='.txt,.csv,.dat',"
)

# 3. Add compute_and_plot method after compute_model
compute_and_plot_code = """
    async def compute_and_plot(self, event=None):
        if not getattr(self, '_compute_in_progress', False):
            self._compute_in_progress = True
            try:
                await self.compute_model()
                self.on_lc_plot_button_clicked()
            finally:
                self._compute_in_progress = False
"""
if 'def compute_and_plot' not in code:
    code = code.replace('    async def compute_model(self):', compute_and_plot_code + '\n    async def compute_model(self):')

# 4. Enable adjust=True and add on_value_changed=self.compute_and_plot for add_parameter calls
# First, change adjust=False to adjust=True
code = code.replace('adjust=False,', 'adjust=True,')

# Now add on_value_changed to add_parameter calls that don't have it
def add_on_value_changed(match):
    block = match.group(0)
    if 'on_value_changed' not in block:
        return block.replace(')', ', on_value_changed=self.compute_and_plot)')
    else:
        return block.replace('self.on_ephemeris_changed', 'self.compute_and_plot')

# We need to correctly capture the full add_parameter call including newlines
code = re.sub(r'self\.add_parameter\([^)]+\)', add_on_value_changed, code)

# For direct PhoebeParameterWidget instantiations in create_compute_panel, add the hook
def add_hook_to_widget(match):
    block = match.group(0)
    if 'on_value_changed' not in block and 'ui_hook' not in block:
        return block.replace('api=self.phoebe_api', 'api=self.phoebe_api,\n                        on_value_changed=self.compute_and_plot')
    return block

# The widgets in create_compute_panel have api=self.phoebe_api
code = re.sub(r'PhoebeParameterWidget\([^)]+\)', add_hook_to_widget, code)

with open('ui/phoebe_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)
print('Patched successfully!')
