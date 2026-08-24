"""Parser utilities for YouTube comment counts, dates/time, and string normalization."""

import re
from typing import Optional


def parse_comment_count(raw_text: Optional[str]) -> int:
    """
    Parse a comment count string into an integer.
    Handles formats like:
      - "4"
      - "4 Comments"
      - "4 comentarios"
      - "501"
      - "1,234 Comments"
      - "1.234 comentarios"
      - "12 345 comentarios"
      - "1.5K Comments"
      - "2.3M Comments"
      - "10 mil comentarios"
    
    Returns 0 if no integer is found or parsing fails.
    """
    if not raw_text:
        return 0

    text = raw_text.strip()
    if not text:
        return 0

    # Match word multipliers first before single letters:
    # "millones", "million", "mil", "k", "m", "b"
    k_m_pattern = re.search(
        r'([\d]+(?:[\.,][\d]+)?)\s*(millones|million|mil|[kmbt])\b',
        text,
        re.IGNORECASE
    )
    if k_m_pattern:
        num_str = k_m_pattern.group(1).replace(',', '.')
        unit = k_m_pattern.group(2).lower()
        try:
            val = float(num_str)
            if unit in ('k', 'mil'):
                return int(val * 1000)
            elif unit in ('m', 'million', 'millones'):
                return int(val * 1_000_000)
            elif unit in ('b', 'billion'):
                return int(val * 1_000_000_000)
        except ValueError:
            pass

    # Extract digits with optional grouping separators (. , space)
    # E.g. "1,234", "1.234", "12 345", "4"
    match = re.search(r'([\d]+[\d\s,\.]*)', text)
    if not match:
        return 0

    num_candidate = match.group(1).strip()

    # Clean separators
    if ',' in num_candidate and '.' in num_candidate:
        if num_candidate.rfind(',') > num_candidate.rfind('.'):
            cleaned = num_candidate.replace('.', '').replace(',', '.')
        else:
            cleaned = num_candidate.replace(',', '')
    elif ',' in num_candidate:
        cleaned = num_candidate.replace(',', '')
    elif '.' in num_candidate:
        parts = num_candidate.split('.')
        if len(parts) > 1 and len(parts[-1]) == 3:
            cleaned = num_candidate.replace('.', '')
        else:
            cleaned = num_candidate
    else:
        cleaned = num_candidate.replace(' ', '')

    try:
        cleaned_num = float(re.sub(r'[^\d.]', '', cleaned))
        return int(cleaned_num)
    except (ValueError, TypeError):
        digits = re.sub(r'[^\d]', '', text)
        return int(digits) if digits else 0


def parse_relative_time_months(time_str: Optional[str]) -> Optional[float]:
    """
    Parse a relative time string into an approximate number of months.
    
    Examples:
      - "just now", "moments ago", "hace un momento" -> 0.0
      - "45 seconds ago", "hace 45 segundos" -> 0.0
      - "10 minutes ago", "hace 10 minutos" -> 0.0
      - "3 hours ago", "hace 3 horas" -> 0.0
      - "2 days ago", "hace 2 días" -> 0.06
      - "3 weeks ago", "hace 3 semanas" -> 0.75
      - "1 month ago", "hace 1 mes" -> 1.0
      - "6 months ago (edited)", "hace 6 meses" -> 6.0
      - "7 months ago", "hace 7 meses" -> 7.0
      - "1 year ago", "hace 1 año" -> 12.0
      - "2 years ago", "hace 2 años" -> 24.0
      
    Returns None if string cannot be parsed as a time expression.
    """
    if not time_str:
        return None

    cleaned = time_str.strip().lower()
    # Remove edit annotations: "(edited)", "(editado)", "edited", etc.
    cleaned = re.sub(r'\(edit(ed|ado)\)', '', cleaned).strip()
    cleaned = re.sub(r'\bedit(ed|ado)\b', '', cleaned).strip()

    if not cleaned:
        return None

    # Immediate / very recent
    if any(term in cleaned for term in ["just now", "moment", "ahora", "recién", "recientemente", "instant"]):
        return 0.0

    # Extract number and time unit
    match = re.search(
        r'(\d+)\s*(second|sec|segundo|seg|minute|min|minuto|hour|hr|hora|day|día|dia|week|sem|semana|month|mo|mes|meses|year|yr|año|anio)',
        cleaned,
        re.IGNORECASE
    )

    if not match:
        # Check singular forms without explicit number (e.g. "a month ago", "un mes", "a year ago")
        if re.search(r'\b(a|an|un|una)\s+(second|segundo|minute|minuto|hour|hora|day|día|dia)', cleaned):
            return 0.0
        if re.search(r'\b(a|an|un|una)\s+(week|semana)', cleaned):
            return 0.25
        if re.search(r'\b(a|an|un|una)\s+(month|mes)', cleaned):
            return 1.0
        if re.search(r'\b(a|an|un|una)\s+(year|año|anio)', cleaned):
            return 12.0
        return None

    amount = float(match.group(1))
    unit = match.group(2).lower()

    if unit.startswith(('second', 'sec', 'seg', 'minute', 'min', 'hour', 'hr', 'hora')):
        return 0.0
    elif unit.startswith(('day', 'día', 'dia')):
        return amount / 30.0
    elif unit.startswith(('week', 'sem', 'semana')):
        return amount / 4.33
    elif unit.startswith(('month', 'mo', 'mes')):
        return amount
    elif unit.startswith(('year', 'yr', 'año', 'anio')):
        return amount * 12.0

    return None


def is_within_time_limit(time_str: Optional[str], max_months: Optional[int] = 6) -> bool:
    """
    Check if a comment's published relative time is within the allowed threshold.
    
    If max_months is 6:
      - <= 6 months -> True
      - >= 7 months -> False
      - >= 1 year -> False
      
    If max_months is None: returns True (unfiltered).
    """
    if max_months is None:
        return True

    if not time_str:
        # If time string is missing, default to True (don't blindly discard)
        return True

    months = parse_relative_time_months(time_str)
    if months is None:
        return True

    # If months <= max_months (e.g. 6.0 <= 6), it is accepted.
    # If 7.0 > 6, it is rejected.
    return months <= float(max_months)
