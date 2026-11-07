"""Regression checks for profile score item counts and applicable education fields."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.students.routes import calculate_profile_completion, calculate_profile_score


def main():
    student = {
        'full_name': 'Test Student', 'phone': '9999999999', 'email': 'test@example.com',
        'address': 'Address', 'gender': 'Female', 'education_level': 'School',
        'qualification': 'Studying 9th', 'employment_status': 'Student',
        'date_of_birth': '2010-01-01', 'parent_name': 'Parent',
        'parent_contact': '8888888888', 'father_name': 'Father', 'mother_name': 'Mother',
        'student_signature_filename': 'student.png', 'parent_signature_filename': '',
    }
    documents = [{'category': 'qualification'}, {'category': 'identity'}]

    completion = calculate_profile_completion(student, documents)
    assert completion['total_items'] == 18
    assert completion['filled_count'] == 16
    assert completion['missing_count'] == 2
    assert completion['missing_labels'] == ['Parent Signature', 'Address Document']
    assert completion['score'] == 88
    assert calculate_profile_score(student, documents) == completion['score']

    student['parent_signature_filename'] = 'parent.png'
    documents.append({'category': 'address'})
    complete = calculate_profile_completion(student, documents)
    assert complete['score'] == 100
    assert complete['missing_count'] == 0
    print('PASS: Profile score reports the exact applicable missing-item count.')


if __name__ == '__main__':
    main()
