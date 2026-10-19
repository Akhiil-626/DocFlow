from typing import Any

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_cell(value: Any) -> str:
    """Sanitize a cell value to prevent CSV / Formula Injection attacks (CWE-1236).

    Any text cell starting with '=', '+', '-', '@', horizontal tab, or carriage return
    is prepended with a single quote (').
    Normal text, Unicode characters, commas, and quotes are strictly preserved.
    """
    if value is None:
        return ""

    str_val = str(value)
    if str_val and str_val.startswith(DANGEROUS_PREFIXES):
        return f"'{str_val}"

    return str_val
