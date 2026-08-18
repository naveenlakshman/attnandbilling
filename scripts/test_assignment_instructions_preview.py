"""Regression checks for safe rich-text assignment instruction previews."""

import os
import sys
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import Workbook
import modules.lms_admin.routes as lms_routes
from modules.lms_admin.routes import sanitize_rich_text


def main():
    html = (
        '<p><img src="data:image/png;base64,iVBORw0KGgo=" '
        'onerror="alert(1)" style="width: 120px"></p>'
        '<script>alert(2)</script>'
        '<a href="data:text/html;base64,PHNjcmlwdD4=">unsafe link</a>'
    )
    sanitized = sanitize_rich_text(html)

    assert 'data:image/png;base64,iVBORw0KGgo=' in sanitized
    assert 'style="width: 120px;"' in sanitized
    assert 'onerror' not in sanitized
    assert '<script' not in sanitized
    assert 'data:text/html' not in sanitized

    template_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'templates', 'lms_admin', 'lms_assignment_review_detail.html',
    )
    with open(template_path, encoding='utf-8') as template_file:
        template = template_file.read()
    assert '<details class="instructions">' in template
    assert '<details class="instructions" open>' not in template
    assert '<summary>Assignment instructions</summary>' in template

    workbook = Workbook()
    sheet = workbook.active
    sheet.merge_cells('A1:D1')
    sheet['A1'] = 'Project Dashboard'
    sheet['C5'] = '=SUM(1,2)'
    workbook_bytes = BytesIO()
    workbook.save(workbook_bytes)
    original_reader = lms_routes._read_submission_file_bytes
    try:
        lms_routes._read_submission_file_bytes = lambda _path: workbook_bytes.getvalue()
        preview = lms_routes._xlsx_formula_preview('test.xlsx')
    finally:
        lms_routes._read_submission_file_bytes = original_reader
    preview_sheet = preview['sheets'][0]
    assert len(preview_sheet['rows']) == 50
    assert len(preview_sheet['column_headers']) == 15
    assert preview_sheet['rows'][0][1]['coordinate'] == 'B1'
    assert preview_sheet['rows'][4][2]['formula'] == '=SUM(1,2)'
    assert preview_sheet['truncated'] is False
    print('PASS: Instructions are sanitized and the formula preview has a scrollable worksheet canvas.')


if __name__ == '__main__':
    main()
