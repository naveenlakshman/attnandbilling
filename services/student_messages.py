"""Student-facing messages keep the complete name recorded on the student profile."""
import re


def student_full_name(value):
    return ' '.join(str(value or '').split()) or 'Student'


def personalize_student_message(message, full_name):
    name = student_full_name(full_name)
    message = str(message or '').replace('{student_name}', name).replace('{full_name}', name)
    normalized = ' '.join(message.split())
    if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', normalized, re.IGNORECASE):
        return message
    return f'Dear {name},\n{message}'


def registration_message(full_name, registration_no):
    return (f'Welcome to Global IT Education, {student_full_name(full_name)}! '
            f'Your Registration Number is {registration_no}. '
            'Keep this number safe for future reference.')


def invoice_message(full_name, invoice_no, amount, download_url):
    return (f'Dear {student_full_name(full_name)}, invoice {invoice_no} for Rs.{amount:.0f} is ready. '
            f'Download your invoice: {download_url} - Global IT Education')


def receipt_message(full_name, receipt_no, amount, download_url):
    return (f'Dear {student_full_name(full_name)}, payment of Rs.{amount:.0f} received '
            f'against {receipt_no}. Download your receipt: {download_url} - Global IT Education')
