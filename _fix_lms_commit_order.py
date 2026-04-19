"""
Fix SQLite write lock deadlock in lms_admin/routes.py.
Pattern to fix: log_activity(...multiline...) immediately followed by conn.commit()
Fix: swap so conn.commit() comes FIRST, then log_activity()
"""

filepath = 'modules/lms_admin/routes.py'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

output = []
i = 0
swapped = 0

while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    # Detect start of log_activity( call
    if stripped.startswith('log_activity('):
        indent = line[:len(line) - len(line.lstrip())]
        # Collect the full log_activity block until closing )
        block = [line]
        i += 1
        while i < len(lines):
            block.append(lines[i])
            if lines[i].strip() == ')':
                i += 1
                break
            i += 1
        # Now check: is the next non-empty line conn.commit()?
        # Skip any blank lines between
        blank_lines = []
        while i < len(lines) and lines[i].strip() == '':
            blank_lines.append(lines[i])
            i += 1

        if i < len(lines) and lines[i].strip() == 'conn.commit()':
            commit_line = lines[i]
            i += 1
            # Swap: output commit first, then blank lines (if any), then log block
            output.append(commit_line)
            output.extend(blank_lines)
            output.extend(block)
            swapped += 1
        else:
            # Not the pattern we want - output as-is
            output.extend(block)
            output.extend(blank_lines)
    else:
        output.append(line)
        i += 1

print(f"Swapped {swapped} log_activity/conn.commit() pairs")

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(output)
print("Done - file written.")
