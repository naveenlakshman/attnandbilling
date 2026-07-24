import requests
import re

print("[*] Testing Docker container authentication for test2.localhost...")

# 1. Staff Login
s = requests.Session()
r1 = s.get('http://localhost:8080/login', headers={'Host': 'test2.localhost'})
match = re.search(r'meta name="csrf-token" content="([^"]+)"', r1.text)
csrf = match.group(1) if match else ''

r2 = s.post(
    'http://localhost:8080/login',
    headers={'Host': 'test2.localhost'},
    data={'csrf_token': csrf, 'username': 'test2', 'password': 'test2password123'},
    allow_redirects=True
)
print('STAFF LOGIN SUCCESS:', r2.status_code, 'Final URL:', r2.url)

# Test /leads/
r_leads = s.get('http://localhost:8080/leads/', headers={'Host': 'test2.localhost'})
print('LEADS DASHBOARD GET:', r_leads.status_code)
print('Leaked Global IT staff "Meghana":', 'Meghana' in r_leads.text)
print('Leaked Global IT staff "Chaithra":', 'Chaithra' in r_leads.text)
print('Leaked Global IT staff "Harsha":', 'Harsha' in r_leads.text)

# Test cross-tenant direct ID isolation
# 1. Lead 349 (Global IT lead) on test2.localhost
r_lead_other = s.get('http://localhost:8080/leads/349', headers={'Host': 'test2.localhost'}, allow_redirects=True)
print('LEAD 349 ACCESS (OTHER TENANT): Has "not found":', 'not found' in r_lead_other.text.lower())

# 2. Invoice 485 (Global IT invoice) on test2.localhost
r_inv_other = s.get('http://localhost:8080/billing/invoice/485', headers={'Host': 'test2.localhost'}, allow_redirects=True)
print('INVOICE 485 ACCESS (OTHER TENANT): Has "not found":', 'not found' in r_inv_other.text.lower())

# 3. Student 1516718 (Global IT student) on test2.localhost
r_stu_other = s.get('http://localhost:8080/billing/student/1516718', headers={'Host': 'test2.localhost'}, allow_redirects=True)
print('STUDENT 1516718 ACCESS (OTHER TENANT): Has "not found":', 'not found' in r_stu_other.text.lower())

# 5. Check Global IT student registration number continuation
s_git = requests.Session()
s_git.post('http://localhost:8080/login', data={'username': 'naveen', 'password': 'password123'})
r_global_stu = s_git.get('http://localhost:8080/billing/students')
print('GLOBAL IT STUDENTS GET:', r_global_stu.status_code)
print('Has 1516721 (continued registration number):', '1516721' in r_global_stu.text)

# 6. Check /leads/followups isolation for test2.localhost
r_fol = s.get('http://localhost:8080/leads/followups', headers={'Host': 'test2.localhost'})
print('LEADS FOLLOWUPS GET:', r_fol.status_code)
print('Leaked Preethi in followups:', 'Preethi' in r_fol.text)
print('Leaked Sumaya Bhanu in followups:', 'Sumaya Bhanu' in r_fol.text)
print('Leaked Thanushree H in followups:', 'Thanushree' in r_fol.text)

# 6. Check /leads/pipeline isolation for test2.localhost
r_pipe = s.get('http://localhost:8080/leads/pipeline', headers={'Host': 'test2.localhost'})
print('LEADS PIPELINE GET:', r_pipe.status_code)
print('Leaked Preethi in pipeline:', 'Preethi' in r_pipe.text)
print('Leaked Sumaya Bhanu in pipeline:', 'Sumaya Bhanu' in r_pipe.text)

# 7. Expenses list on test2.localhost
r_exp = s.get('http://localhost:8080/billing/expenses', headers={'Host': 'test2.localhost'})
print('EXPENSES LIST GET:', r_exp.status_code)

# 2. Student Login
s2 = requests.Session()
r3 = s2.get('http://localhost:8080/student/login', headers={'Host': 'test2.localhost'})
match2 = re.search(r'name="csrf_token" value="([^"]+)"', r3.text)
csrf2 = match2.group(1) if match2 else ''

r4 = s2.post(
    'http://localhost:8080/student/login',
    headers={'Host': 'test2.localhost'},
    data={'csrf_token': csrf2, 'student_code': 'STU001', 'password': 'test2password123'},
    allow_redirects=True
)
print('STUDENT LOGIN SUCCESS:', r4.status_code, 'Final URL:', r4.url, 'Has Student Dashboard:', 'Student' in r4.text or 'Dashboard' in r4.text)
