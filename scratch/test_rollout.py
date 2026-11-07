import requests

# 1. Test non-platform admin (test2)
s2 = requests.Session()
r = s2.get('http://localhost:8080/login', headers={'Host': 'test2.localhost'})
tok = r.text.split('csrf-token" content="')[1].split('"')[0]
s2.post('http://localhost:8080/login', data={'username': 'test2', 'password': 'Password123!', 'csrf_token': tok}, headers={'Host': 'test2.localhost'})
r_test2 = s2.get('http://localhost:8080/lms_admin/phase6/rollout', headers={'Host': 'test2.localhost'})
print("test2.localhost /lms_admin/phase6/rollout status:", r_test2.status_code)

# 2. Test platform admin (localhost)
s1 = requests.Session()
r1 = s1.get('http://localhost:8080/login', headers={'Host': 'localhost'})
tok1 = r1.text.split('csrf-token" content="')[1].split('"')[0]
s1.post('http://localhost:8080/login', data={'username': 'naveen', 'password': 'Password123!', 'csrf_token': tok1}, headers={'Host': 'localhost'})
r_primary = s1.get('http://localhost:8080/lms_admin/phase6/rollout', headers={'Host': 'localhost'})
print("localhost /lms_admin/phase6/rollout status:", r_primary.status_code)
