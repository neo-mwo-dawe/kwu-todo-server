import requests
from bs4 import BeautifulSoup

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
r = s.get('https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do', timeout=15)
print('상태코드:', r.status_code)
print('URL:', r.url)
soup = BeautifulSoup(r.text, 'html.parser')
for f in soup.find_all('form'):
    print('form action:', f.get('action'))
for i in soup.find_all('input'):
    print('input name:', i.get('name'), 'type:', i.get('type'))
