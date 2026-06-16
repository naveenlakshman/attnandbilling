# Flask SMS Gateway Integration Guide

## Overview
Your SMS Gateway app runs as a background service on your Xiaomi phone. Your Flask app on PythonAnywhere sends SMS requests to the **Cloud Server** at `api.sms-gate.app` — the phone connects to this cloud relay, so Flask works from anywhere on the internet (no same-WiFi requirement).

---

## Phone Setup (Already Complete ✓)

**Cloud Server Details:**
- **API Endpoint:** `https://api.sms-gate.app/3rdparty/v1/message`
- **Username:** `DP4VDN`
- **Password:** `qrbwcqfz-gwayf`
- **Device ID:** `JiJwvc0JqYeBSw__15Arg`
- **Notification Channel:** SSE Only (no Firebase required)

**Local Server Details (same-WiFi fallback):**
- **IP Address:** `192.168.31.70`
- **Port:** `8080`
- **Username:** `sms`
- **Password:** `4J-WAwzD`

**Important:** Use the Cloud Server endpoint from PythonAnywhere — it works over the internet.

---

## Flask Integration (PythonAnywhere)

### 1. Install requests library
If not already installed, add to your PythonAnywhere console:
```bash
pip install requests
```

### 2. Create SMS Helper Function

Add this to your Flask app:

```python
import requests
from requests.auth import HTTPBasicAuth

def send_sms(phone_number, message_text):
    """
    Send SMS via SMS Gateway Local Server
    
    Args:
        phone_number (str): Phone number in format "+919071717162"
        message_text (str): Message text to send
    
    Returns:
        dict: Response from SMS Gateway API
    """
    
    # SMS Gateway Cloud API configuration
    GATEWAY_URL = "https://api.sms-gate.app/3rdparty/v1/message"
    GATEWAY_USER = "DP4VDN"
    GATEWAY_PASSWORD = "qrbwcqfz-gwayf"
    
    # Prepare request payload
    payload = {
        "textMessage": {
            "text": message_text
        },
        "phoneNumbers": [phone_number]
    }
    
    try:
        # Send request to SMS Gateway
        response = requests.post(
            GATEWAY_URL,
            json=payload,
            auth=HTTPBasicAuth(GATEWAY_USER, GATEWAY_PASSWORD),
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        # Check if request was successful
        if response.status_code == 200:
            result = response.json()
            print(f"SMS sent successfully! Message ID: {result.get('id')}")
            return {
                "success": True,
                "message_id": result.get('id'),
                "status": result.get('state')
            }
        else:
            print(f"Failed to send SMS. Status: {response.status_code}")
            return {
                "success": False,
                "error": response.text
            }
            
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timeout - Phone may be offline"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Connection refused - Phone/Gateway not accessible"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

### 3. Use in Your Flask Routes

**Example 1: Simple SMS Route**
```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/send-sms', methods=['POST'])
def send_sms_route():
    data = request.json
    phone = data.get('phone')
    message = data.get('message')
    
    if not phone or not message:
        return jsonify({"error": "Missing phone or message"}), 400
    
    result = send_sms(phone, message)
    return jsonify(result)

# Example: Test endpoint
@app.route('/test-sms', methods=['GET'])
def test_sms():
    result = send_sms("+919071717162", "Hello from Flask!")
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

**Example 2: Send OTP via SMS**
```python
import random
import string

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    phone = data.get('phone')
    
    if not phone:
        return jsonify({"error": "Phone number required"}), 400
    
    # Generate OTP
    otp = ''.join(random.choices(string.digits, k=6))
    
    # Send OTP via SMS
    message = f"Your verification code is: {otp}"
    result = send_sms(phone, message)
    
    if result['success']:
        # Store OTP in database with timestamp
        # user = User.create(phone=phone, otp=otp, verified=False)
        return jsonify({
            "success": True,
            "message": "OTP sent successfully",
            "otp": otp  # Remove in production!
        })
    else:
        return jsonify(result), 500
```

**Example 3: Send SMS with Retry Logic**
```python
def send_sms_with_retry(phone_number, message_text, retries=3):
    """
    Send SMS with automatic retry on failure
    """
    for attempt in range(retries):
        try:
            result = send_sms(phone_number, message_text)
            if result['success']:
                return result
            else:
                print(f"Attempt {attempt + 1} failed: {result['error']}")
                if attempt < retries - 1:
                    time.sleep(2)  # Wait 2 seconds before retry
        except Exception as e:
            print(f"Exception on attempt {attempt + 1}: {e}")
    
    return {"success": False, "error": "Failed after retries"}
```

---

## Important Considerations

### 1. **Network Requirements**
- Cloud Server works from **anywhere on the internet** — no same-WiFi requirement
- Flask on PythonAnywhere calls `https://api.sms-gate.app/3rdparty/v1/message`
- The cloud relay forwards the request to your phone via SSE connection

### 2. **Phone Must Stay Online**
- App runs as a background service
- Phone must not be turned off
- Battery optimization may kill the service — disable for this app
- Phone needs active mobile data or WiFi to maintain SSE connection to cloud

### 3. **Keep Cloud Server Enabled**
- Go to app's HOME tab
- Cloud Server toggle must be **ON**
- Credentials: username `DP4VDN`, password `qrbwcqfz-gwayf`

### 4. **Production Considerations**
- Store credentials in environment variables, not hardcoded
- Add proper error handling and logging
- Implement rate limiting
- Consider backup SMS gateway for reliability
- Set timeouts appropriately (current: 10 seconds)

### 5. **Troubleshooting**

**"Connection refused" error:**
- Check phone is on same WiFi network
- Verify Local Server is enabled in app
- Check phone IP address hasn't changed

**"Request timeout" error:**
- Phone may be offline or WiFi disconnected
- Check WiFi connectivity on phone
- Restart the SMS Gateway app

**SMS not sending:**
- Verify phone number format: `+919071717162` (with country code)
- Check message text is not empty
- Verify credentials (sms/53G491kQ)
- Check Local Server shows "running" state

---

## API Response Format

**Successful Response (HTTP 200):**
```json
{
  "deviceId": "000000000ff240e00000019e12c1b684",
  "id": "ZmL4en8J8Jz6i9M7i8vmc",
  "state": "Pending",
  "recipients": [
    {
      "phoneNumber": "+919071717162",
      "state": "Pending"
    }
  ]
}
```

**Error Response:**
```json
{
  "error": "Invalid phone number format"
}
```

---

## Environment Variable Setup (Recommended for Production)

**PythonAnywhere Web App Configuration:**

```python
import os

GATEWAY_URL = os.environ.get('SMS_GATEWAY_URL', 'http://192.168.31.70:8080/message')
GATEWAY_USER = os.environ.get('SMS_GATEWAY_USER', 'sms')
GATEWAY_PASSWORD = os.environ.get('SMS_GATEWAY_PASSWORD', '53G491kQ')
```

**Set in PythonAnywhere Dashboard:**
- Go to Web app configuration
- Add environment variables in the web app settings

---

## Testing

### From PythonAnywhere Console:
```python
import requests
from requests.auth import HTTPBasicAuth

# Test connection
response = requests.post(
    'http://192.168.31.70:8080/message',
    json={
        "textMessage": {"text": "Test SMS from Flask"},
        "phoneNumbers": ["+919071717162"]
    },
    auth=HTTPBasicAuth('sms', '53G491kQ'),
    timeout=5
)
print(response.json())
```

### From Flask App:
- Navigate to `/test-sms` endpoint to send a test message

---

## Next Steps

1. ✓ SMS Gateway app is running on your phone
2. ✓ Local Server is configured and accessible
3. → Add the Flask integration code to your PythonAnywhere app
4. → Test with the `/test-sms` endpoint
5. → Implement in your actual Flask routes
6. → Monitor error logs and adjust timeout/retry settings as needed

Once set up, you don't need to touch the app again—just send SMS requests from Flask!


Copy this into PythonAnywhere
import requests
from requests.auth import HTTPBasicAuth

def send_sms(phone_number, message_text):
    response = requests.post(
        "https://api.sms-gate.app/3rdparty/v1/message",
        json={"textMessage": {"text": message_text}, "phoneNumbers": [phone_number]},
        auth=HTTPBasicAuth("DP4VDN", "qrbwcqfz-gwayf"),
        timeout=10
    )
    return response.json()