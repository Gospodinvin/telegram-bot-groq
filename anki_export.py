# anki_export.py
import io
import random
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

try:
    import genanki
    GENANKI_AVAILABLE = True
except ImportError:
    GENANKI_AVAILABLE = False
    logger.warning("genanki не установлен. Anki-экспорт недоступен.")


class AnkiExporter:
    def __init__(self):
        if not GENANKI_AVAILABLE:
            raise ImportError("Установите: pip install genanki")
        self.model = genanki.Model(
            random.randrange(1 << 30, 1 << 31),
            'LectureX Basic',
            fields=[{'name': 'Front'}, {'name': 'Back'}],
            templates=[{
                'name': 'Card 1',
                'qfmt': '{{Front}}',
                'afmt': '{{FrontSide}}<hr id="answer">{{Back}}',
            }],
            css='.card { font-family: Arial; font-size: 20px; text-align: center; color: black; background-color: white; }'
        )

    def generate(self, cards: List[Dict[str, str]], deck_name: str = "LectureX Deck") -> io.BytesIO:
        deck = genanki.Deck(random.randrange(1 << 30, 1 << 31), deck_name)
        for c in cards:
            note = genanki.Note(
                model=self.model,
                fields=[c.get('front', ''), c.get('back', '')]
            )
            deck.add_note(note)
        buf = io.BytesIO()
        genanki.Package(deck).write_to_file(buf)
        buf.seek(0)
        return buf

    @staticmethod
    def extract_cards_from_summary(text: str) -> List[Dict[str, str]]:
        cards = []
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for line in lines:
            for sep in [' — ', ' – ', '- ', ': ', ' – ']:
                if sep in line and len(line) > 10:
                    parts = line.split(sep, 1)
                    if len(parts) == 2 and 3 <= len(parts[0]) <= 60:
                        front = parts[0].strip().strip('*- ')
                        back = parts[1].strip()
                        if len(back) > 5:
                            cards.append({"front": front, "back": back})
                            break
        if not cards:
            for i in range(0, min(len(lines) - 1, 50), 2):
                cards.append({"front": lines[i][:100], "back": lines[i+1][:200]})
        return cards[:50]