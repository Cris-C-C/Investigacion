import re

with open('ui/phoebe_ui.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Fix the damaged labels
code = code.replace(', on_value_changed=self.compute_and_plot)', ')')

# 2. Add on_value_changed to all add_parameter blocks
def process_add_parameter(code):
    pos = 0
    new_code = ""
    while True:
        idx = code.find('self.add_parameter(', pos)
        if idx == -1:
            new_code += code[pos:]
            break
        
        new_code += code[pos:idx]
        
        # Find matching parenthesis
        open_parens = 0
        end_idx = idx
        for i in range(idx + 19, len(code)):
            if code[i] == '(':
                open_parens += 1
            elif code[i] == ')':
                if open_parens == 0:
                    end_idx = i
                    break
                open_parens -= 1
        
        block = code[idx:end_idx+1]
        
        # Modify block
        if 'on_value_changed' in block:
            if 'self.on_ephemeris_changed' in block:
                block = block.replace('self.on_ephemeris_changed', 'self.compute_and_plot')
        else:
            block = block[:-1] + ',\n                on_value_changed=self.compute_and_plot' + ')'
            
        new_code += block
        pos = end_idx + 1
        
    return new_code

code = process_add_parameter(code)

with open('ui/phoebe_ui.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Fixed damaged labels and added on_value_changed correctly.")
