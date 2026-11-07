from html.parser import HTMLParser

with open(r'd:\bot\web\templates\index.html', 'r', encoding='utf-8') as f:
    content = f.read()

class TagCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []
    def handle_starttag(self, tag, attrs):
        if tag not in ['img', 'input', 'br', 'hr', 'meta', 'link']:
            self.stack.append((tag, self.getpos(), dict(attrs).get('id', '')))
    def handle_endtag(self, tag):
        if tag in ['img', 'input', 'br', 'hr', 'meta', 'link']:
            return
        if not self.stack:
            self.errors.append(f'Unexpected end tag </{tag}> at {self.getpos()}')
            return
        last, pos, el_id = self.stack.pop()
        if last != tag:
            self.errors.append(f'Mismatched <{last} id="{el_id}"> at {pos} closed by </{tag}> at {self.getpos()}')

p = TagCounter()
p.feed(content)
print('Unclosed tags count:', len(p.stack))
for t in p.stack:
    print('Unclosed:', t)
print('Tag errors count:', len(p.errors))
for err in p.errors[:10]:
    print('Error:', err)
