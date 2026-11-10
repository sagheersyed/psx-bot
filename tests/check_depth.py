import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
html_path = Path(__file__).resolve().parent.parent / "web" / "templates" / "index.html"
with open(html_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

depth = 0
for i, l in enumerate(lines[104:535], start=105):
    opens = l.count('<div')
    closes = l.count('</div')
    depth += opens - closes
    if depth <= 2:
        print(f'Line {i:4d}: depth={depth} | {l.strip()[:60]}')
