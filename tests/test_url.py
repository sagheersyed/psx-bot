import urllib.request

res = urllib.request.urlopen('http://127.0.0.1:5000/low_float')
html = res.read().decode('utf-8')
print('Status:', res.status)
print('Length:', len(html))
print('Has viewMain:', 'id="viewMain"' in html)
print('Has viewLowFloat:', 'id="viewLowFloat"' in html)
print('Has lowFloatGrid:', 'id="lowFloatGrid"' in html)
