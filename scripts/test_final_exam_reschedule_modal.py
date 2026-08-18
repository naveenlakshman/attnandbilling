"""Regression checks for clickable final-exam reschedule modals."""

import os


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_path = os.path.join(root, 'templates', 'exams', 'admin_final_exam_applications.html')
    with open(template_path, encoding='utf-8') as template_file:
        template = template_file.read()

    table_end = template.index('</table>')
    modal_definition = template.index('<div class="modal fade text-start"')
    assert modal_definition > table_end, 'Reschedule modal must not be nested in the sticky Actions cell.'
    assert 'data-bs-target="#rescheduleModal{{ app.id }}"' in template
    assert 'for="rescheduleDate{{ app.id }}"' in template
    assert 'min="{{ today }}" required' in template
    assert 'Save &amp; Approve' in template
    print('PASS: Reschedule modal is outside the sticky table and remains fully clickable.')


if __name__ == '__main__':
    main()
