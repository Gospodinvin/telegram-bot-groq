# utils/diploma_utils.py
import re

def parse_diploma_text(text: str) -> list:
    """Извлекает разделы из текста диплома по маркерам === ... ==="""
    pattern = r'===\s*(.+?)\s*===\n(.*?)(?=(?:===\s*.+?\s*===|\Z))'
    matches = re.findall(pattern, text, re.DOTALL)
    return [(h.strip(), b.strip()) for h, b in matches if b.strip()]