import re

with open('ui/phoebe_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

replacement = """        if self.ui_hook:
            import inspect, asyncio
            res = self.ui_hook(value)
            if inspect.iscoroutine(res):
                asyncio.create_task(res)"""

code = re.sub(r"        if self\.ui_hook:\n            self\.ui_hook\(value\)", replacement, code)

with open('ui/phoebe_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)

print('Fixed ui_hook coroutine handling')
