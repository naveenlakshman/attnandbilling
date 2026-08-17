"""Regression checks for safe rich-text assignment instruction previews."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    print('PASS: Embedded assignment images render while active content is removed.')


if __name__ == '__main__':
    main()
