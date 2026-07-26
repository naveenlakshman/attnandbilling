import requests

s = requests.Session()
r = s.get('http://localhost:8080/login', headers={'Host': 'test2.localhost'})
tok = r.text.split('csrf-token" content="')[1].split('"')[0]

r2 = s.post(
    'http://localhost:8080/login',
    data={'username': 'test2', 'password': 'Password123!', 'csrf_token': tok},
    headers={'Host': 'test2.localhost'}
)

r3 = s.get('http://localhost:8080/lms_admin/master/assignments', headers={'Host': 'test2.localhost'})
print("TITLE:", r3.text.split('<title>')[1].split('</title>')[0])
print("Has 388:", '388' in r3.text)
print("Has 345:", '345' in r3.text)
