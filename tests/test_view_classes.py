import urllib.request

html = urllib.request.urlopen('http://127.0.0.1:5000/low_float').read().decode('utf-8')
lines = html.splitlines()
for l in lines:
    if 'id="viewMain"' in l or 'id="viewLowFloat"' in l:
        print(l.strip())
