ATTRIBUTION_FIELDS = (
    "gclid",
    "gbraid",
    "wbraid",
    "fbclid",
    "fbc",
    "fbp",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "landing_page",
    "referrer",
)
ATTRIBUTION_VALUE_MAX_LENGTH = 512


def clean_attribution(raw):
    """Keeps only known marketing attribution keys with non-empty string values."""
    if not isinstance(raw, dict):
        return None

    cleaned = {}
    for field in ATTRIBUTION_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str):
            continue
        value = value.strip()[:ATTRIBUTION_VALUE_MAX_LENGTH]
        if value:
            cleaned[field] = value

    return cleaned or None
