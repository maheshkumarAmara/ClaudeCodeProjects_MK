"""Template parsers, one module per distributor.

Each module exposes parse_template(path) -> {"fields": {...}, "line_items": [...]}.
Which parser a distributor uses is set on its entry in distributors.py, not here.
"""
