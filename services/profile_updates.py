"""Validation and comparison rules for student profile update requests."""

PROFILE_UPDATE_FIELDS = (
    'full_name', 'phone', 'email', 'address', 'gender', 'education_level',
    'qualification', 'employment_status', 'date_of_birth', 'parent_name',
    'parent_contact', 'father_name', 'mother_name', 'tenth_institution',
    'tenth_board', 'tenth_year', 'tenth_percentage', 'puc_institution',
    'puc_board', 'puc_stream', 'puc_year', 'puc_percentage',
)

_CANONICAL_CHOICES = {
    'gender': {'male': 'male', 'female': 'female', 'other': 'other', '': ''},
    'employment_status': {
        'unemployed': 'unemployed', 'employed': 'employed',
        'student': 'student', '': '',
    },
    'education_level': {
        'school': 'School',
        'pre-university': 'Pre-University',
        'diploma': 'Diploma',
        'undergraduate': 'Undergraduate',
        'postgraduate': 'Postgraduate',
        'doctoral': 'Doctoral',
        'technical': 'Technical',
        'professional': 'Professional',
        '': '',
    },
}

_CASE_INSENSITIVE_FIELDS = {'gender', 'employment_status', 'education_level', 'email'}


def normalize_profile_value(field, value):
    """Return a trimmed, canonical value or reject an invalid controlled value."""
    if field not in PROFILE_UPDATE_FIELDS:
        raise ValueError(f'Unsupported profile field: {field}')
    normalized = '' if value is None else str(value).strip()
    choices = _CANONICAL_CHOICES.get(field)
    if choices is not None:
        key = normalized.casefold()
        if key not in choices:
            raise ValueError(f'Invalid value for {field.replace("_", " ")}')
        return choices[key]
    return normalized


def profile_values_equal(field, first, second):
    """Compare semantically, ignoring formatting that does not change the value."""
    left = normalize_profile_value(field, first)
    right = normalize_profile_value(field, second)
    if field in _CASE_INSENSITIVE_FIELDS:
        return left.casefold() == right.casefold()
    return left == right


def material_profile_changes(current, requested):
    """Whitelist, normalize and return only genuine changes."""
    changes = {}
    for field, value in (requested or {}).items():
        if field not in PROFILE_UPDATE_FIELDS:
            continue
        normalized = normalize_profile_value(field, value)
        current_value = current.get(field) if hasattr(current, 'get') else current[field]
        if not profile_values_equal(field, normalized, current_value):
            changes[field] = normalized
    return changes


def profile_changes_from_form(current, form):
    """Compare only controls that were actually submitted by the profile form."""
    submitted = {
        field: form.get(field)
        for field in PROFILE_UPDATE_FIELDS
        if field in form
    }
    return material_profile_changes(current, submitted)
