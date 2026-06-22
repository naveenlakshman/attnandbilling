# Security Review & Hardening Strategy

This document reviews the security posture of the existing Flask ERP system, highlights critical vulnerabilities, and defines how the target Django implementation will resolve these risks using framework built-ins and security patterns.

---

## 1. Audit of Current Flask Security Vulnerabilities

A security review of the Flask codebase reveals critical gaps in authorization, file exposure, rate limiting, and session control.

### A. CRM Lead Mutation Authorization Bypass
* **Vulnerability**: While the CRM list view filters leads based on the assigned counselor (if the user lacks cross-branch permissions), the mutation views (`/leads/<lead_id>/edit`, `/leads/<lead_id>/delete`, `/leads/<lead_id>/reassign`) only verify that the user is logged in. They do not verify if the logged-in user is the counselor assigned to the lead.
* **Impact**: Any authenticated user can mutate, delete, or reassign any prospect in the database by guessing the integer `lead_id` in the HTTP post payload (Insecure Direct Object Reference - IDOR).
* **Django Mitigation**: Implement custom view-level permissions. In class-based views, override the `get_object()` method to check user permissions or use a helper mixin:
  ```python
  from django.core.exceptions import PermissionDenied
  from django.contrib.auth.mixins import LoginRequiredMixin
  from django.views.generic import UpdateView
  
  class LeadUpdateView(LoginRequiredMixin, UpdateView):
      model = Lead
      
      def get_object(self, queryset=None):
          obj = super().get_object(queryset)
          # Enforce owner authorization check
          if not self.request.user.is_superuser:
              if not self.request.user.can_view_all_branches and obj.assigned_to != self.request.user:
                  raise PermissionDenied("You do not own this lead.")
          return obj
  ```

### B. Unauthenticated LMS Content Downloads
* **Vulnerability**: Lesson slides and PDFs inside `/static/lms/` and `/uploads/content/` are served directly by the web server (Nginx/Flask static router). There is no verification that the request originates from a student currently enrolled in the corresponding program.
* **Impact**: Anyone with a direct link (e.g., shared by a student or indexed by a bot) can download courseware PDFs and videos without an active enrollment.
* **Django Mitigation**: Configure the server to serve these files through a Django controller checking active permissions, or utilize secure pre-signed cloud URLs:
  1. Under cloud deployments (e.g. AWS S3), store LMS files in a private bucket. Create an access view that validates student enrollment and redirects using short-lived pre-signed S3 URLs (e.g. 5-minute expiration).
  2. Under local deployment, store files in a folder outside the public web root and serve them using Django's `FileResponse` with an authorization guard:
     ```python
     @login_required
     def serve_private_lms(request, file_path):
         # Verify if student has active access to the program mapping
         if not check_lms_access(request.user, file_path):
             raise PermissionDenied("Access to this resource is restricted.")
         
         response = FileResponse(open(os.path.join(PRIVATE_MEDIA_ROOT, file_path), 'rb'))
         response['Content-Type'] = 'application/pdf'  # Dynamically set mimetype
         return response
     ```

### C. Student Leave Document Authorization Leak
* **Vulnerability**: The leave proof document route `/uploads/leave_docs/<filename>` verifies that the viewer is authenticated, but does not check the identity of the requester.
* **Impact**: Any authenticated student can download medical certificates or personal leave letters uploaded by other students by guessing the filename.
* **Django Mitigation**: Store leave documents under a restricted media prefix and serve them via a controller that verifies the requester is either a staff member or the specific student who submitted the corresponding `LeaveRequest` record.

### D. Isolated Rate-Limiter State
* **Vulnerability**: The Flask application configures rate limits on the `/login` route using an in-memory (`memory://`) storage backend.
* **Impact**: In a multi-worker production server (Gunicorn with 4 workers), the login rate-limiting counters are isolated per process. An attacker can distribute brute-force attempts across processes, increasing the effective limit by a factor of 4.
* **Django Mitigation**: Install `django-ratelimit` or use `django-redis` as the cache storage provider, sharing rate-limit state globally across all app nodes:
  ```python
  # settings.py
  CACHES = {
      'default': {
          'BACKEND': 'django_redis.cache.RedisCache',
          'LOCATION': 'redis://127.0.0.1:6379/1',
      }
  }
  
  # views.py
  from ratelimit.decorators import ratelimit
  
  @ratelimit(key='ip', rate='5/m', method='POST', block=True)
  def erp_login(request):
      # Login validation logic
      pass
  ```

---

## 2. Hardening with Django Built-ins

Django provides native security protections that will replace Flask’s manual wrappers:

### A. CSRF (Cross-Site Request Forgery) Protection
* **Current State**: Handled manually via Flask-WTF. Some custom AJAX endpoints bypass this check, creating entry points for session hijacking.
* **Django Implementation**: Standardized across all views by default using `django.middleware.csrf.CsrfViewMiddleware`. Every POST request must pass a CSRF token. AJAX headers will automatically extract `csrftoken` from cookies.

### B. SQL Injection Mitigation
* **Current State**: Flask uses manual string construction or parameters on sqlite connection cursors.
* **Django Implementation**: The Django ORM utilizes parameterized SQL queries for all QuerySets, preventing SQL injection vulnerabilities.

### C. Security Middleware Configuration
To prevent browser-level exploits, the following headers will be active in Django settings:
```python
# settings/production.py
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
```

---

## 3. Student Portal Session Isolation

To guarantee that students cannot escalate permissions to access ERP administration utilities, Django will enforce strict session isolation:

1. **Custom Middleware Guard**:
   Define middleware that verifies the user's role prefix against path categories:
   * Paths prefixed with `/erp/` or admin routes will immediately redirect to login if `request.user.is_staff == False`.
   * Paths prefixed with `/student/` will be rejected if the user is a staff member but does not have a linked student profile.
2. **Deactivation Hook**:
   If an administrator changes a user's status (`is_active = False`) or deactivates a student's portal access, Django's middleware will check active session tokens and invalidate them, forcing immediate logout.
