import requests

s = requests.Session()
r = s.get('http://localhost:8080/login', headers={'Host': 'test2.localhost'})
tok = r.text.split('csrf-token" content="')[1].split('"')[0]

r2 = s.post(
    'http://localhost:8080/login',
    data={'username': 'test2', 'password': 'Password123!', 'csrf_token': tok},
    headers={'Host': 'test2.localhost'}
)

r3 = s.get('http://localhost:8080/lms_admin/certificates', headers={'Host': 'test2.localhost'})
print("STATUS:", r3.status_code)
print("TITLE:", r3.text.split('<title>')[1].split('</title>')[0])
print("Has GIT-CERT:", 'GIT-CERT' in r3.text)
print("Has Parinav:", 'Parinav' in r3.text)
