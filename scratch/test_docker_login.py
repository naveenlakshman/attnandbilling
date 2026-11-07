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

# 5. Check converted leads list on test2.localhost
r_test2_leads = s.get('http://localhost:8080/leads/list?status_filter=converted', headers={'Host': 'test2.localhost'})
print('TEST2 CONVERTED LEADS GET:', r_test2_leads.status_code)
print('Has lshdksjhd lead:', 'lshdksjhd' in r_test2_leads.text)

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

# 7b. Attendance dashboard on test2.localhost
r_test2_att = s.get('http://localhost:8080/attendance/dashboard', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST ATTENDANCE DASHBOARD GET:', r_test2_att.status_code)

r_test2_leave = s.get('http://localhost:8080/attendance/leave-requests', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST LEAVE REQUESTS GET:', r_test2_leave.status_code)
print('Leaked Sindhu S in leave requests:', 'Sindhu S' in r_test2_leave.text)
print('Leaked Divyashree A in leave requests:', 'Divyashree' in r_test2_leave.text)
r_test2_newbatch = s.get('http://localhost:8080/attendance/batches/new', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST CREATE BATCH FORM GET:', r_test2_newbatch.status_code, 'Has 12-hour select:', 'start_period' in r_test2_newbatch.text)

r_test2_assign = s.get('http://localhost:8080/attendance/batches/370/assign-students', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST ASSIGN STUDENTS GET:', r_test2_assign.status_code)
print('Leaked Global IT student 1516720 Madava Lead1 in assign students:', 'Madava Lead1' in r_test2_assign.text)

r_test2_mark = s.get('http://localhost:8080/attendance/mark-attendance', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST MARK ATTENDANCE GET:', r_test2_mark.status_code)
print('Leaked Global IT branch "Head Office" in mark attendance:', 'Head Office' in r_test2_mark.text)
print('Leaked Global IT branch "Hoskote Branch" in mark attendance:', 'Hoskote Branch' in r_test2_mark.text)

r_test2_pattern = s.get('http://localhost:8080/attendance/attendance-pattern', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST ATTENDANCE PATTERN GET:', r_test2_pattern.status_code)
print('Leaked Global IT branch "Head Office" in attendance pattern:', 'Head Office' in r_test2_pattern.text)
print('Leaked Global IT branch "Hoskote Branch" in attendance pattern:', 'Hoskote Branch' in r_test2_pattern.text)

r_test2_lms = s.get('http://localhost:8080/lms_admin/dashboard', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST LMS DASHBOARD GET:', r_test2_lms.status_code)
print('Leaked Global IT programs (17 active programs):', '>17<' in r_test2_lms.text)

r_test2_fin = s.get('http://localhost:8080/billing/dashboard', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST FINANCE DASHBOARD GET:', r_test2_fin.status_code)

r_test2_rep = s.get('http://localhost:8080/reports/', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST REPORTS DASHBOARD GET:', r_test2_rep.status_code)

r_test2_usr = s.get('http://localhost:8080/users', headers={'Host': 'test2.localhost'})
print('TEST2.LOCALHOST USERS GET:', r_test2_usr.status_code)

# 8. Primary Admin Login & Phase 6 Endpoints
s_admin = requests.Session()
r_adm_login = s_admin.get('http://localhost:8080/login')
m_adm = re.search(r'meta name="csrf-token" content="([^"]+)"', r_adm_login.text)
csrf_adm = m_adm.group(1) if m_adm else ''

r_adm_post = s_admin.post(
    'http://localhost:8080/login',
    data={'csrf_token': csrf_adm, 'username': 'admin', 'password': 'adminpassword123'},
    allow_redirects=True
)

r_att_dash = s_admin.get('http://localhost:8080/attendance/dashboard')
print('PRIMARY ADMIN ATTENDANCE DASHBOARD GET:', r_att_dash.status_code)

r_att_batches = s_admin.get('http://localhost:8080/attendance/batches')
print('PRIMARY ADMIN ATTENDANCE BATCHES GET:', r_att_batches.status_code)

r_att_leaves = s_admin.get('http://localhost:8080/attendance/leave-requests')
print('PRIMARY ADMIN ATTENDANCE LEAVE REQUESTS GET:', r_att_leaves.status_code)

r_rep_dash = s_admin.get('http://localhost:8080/reports/')
print('PRIMARY ADMIN REPORTS DASHBOARD GET:', r_rep_dash.status_code)

r_rep_daily = s_admin.get('http://localhost:8080/reports/daily')
print('PRIMARY ADMIN REPORTS DAILY GET:', r_rep_daily.status_code)

r_rep_monthly = s_admin.get('http://localhost:8080/reports/attendance/monthly')
print('PRIMARY ADMIN REPORTS MONTHLY ATTENDANCE GET:', r_rep_monthly.status_code)

r_rep_export = s_admin.get('http://localhost:8080/reports/export/students')
print('PRIMARY ADMIN REPORTS EXPORT STUDENTS CSV GET:', r_rep_export.status_code)

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
