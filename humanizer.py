# humanizer.py
import re
import random
import logging
from llm_client import call_llm
import config

logger = logging.getLogger(__name__)

class Humanizer:
    def __init__(self):
        pass

    def humanize(self, text: str) -> str:
        try:
            system_prompt = config.HUMANIZE_PROMPT.format(text=text)
            result = call_llm(
                prompt="",
                system=system_prompt,
                model="fast",
                num_predict=3000
            )
            result = self._second_pass(result)
            return self._post_process(result)
        except Exception as e:
            logger.error(f"Ошибка гуманизации: {e}", exc_info=True)
            return text

    def _second_pass(self, text: str) -> str:
        try:
            system_prompt = (
                "Перепиши текст ещё естественнее. Разнообразь вводные слова, длину предложений. "
                "Без шаблонных фраз.\n\n"
                f"Текст: {text}"
            )
            result = call_llm(
                prompt="",
                system=system_prompt,
                model="fast",
                num_predict=3000
            )
            return result
        except Exception:
            return text

    def _post_process(self, text: str) -> str:
        markers = [
            r'в заключение|подводя итог|в итоге|таким образом',
            r'во-первых|во-вторых|в-третьих',
            r'следует отметить|важно подчеркнуть'
        ]
        for m in markers:
            text = re.sub(m, '', text, flags=re.IGNORECASE)

        text = re.sub(r'(?i)(кажется|отсутствует|текст для редактирования|ваш запрос|если вы отправите|я готов|уважаемый коллега)', '', text)

        fillers = [
            'кстати', 'следует отметить', 'интересно, что',
            'что примечательно', 'стоит заметить', 'обратите внимание'
        ]
        sentences = text.split('. ')
        if len(sentences) > 4:
            for i in range(1, len(sentences) - 1, 2):
                if random.random() < 0.3:
                    sentences[i] = f"{random.choice(fillers)}, {sentences[i]}"
            text = '. '.join(sentences)
        return text

    def humanize_diploma(self, text: str) -> str:
        """Гуманизирует целый дипломный текст с использованием специального промпта."""
        try:
            sections = re.split(r'(=== .+? ===)', text)
            result = []
            for i in range(0, len(sections), 2):
                if i+1 < len(sections):
                    header = sections[i]
                    body = sections[i+1]
                    if 'СПИСОК ЛИТЕРАТУРЫ' in header.upper() or 'ПРИЛОЖЕНИ' in header.upper():
                        result.append(header + body)
                        continue
                    system_prompt = config.HUMANIZE_DIPLOMA_PROMPT.format(text=body)
                    humanized_body = call_llm(
                        prompt="",
                        system=system_prompt,
                        model="fast",
                        num_predict=6000
                    )
                    humanized_body = re.sub(r'(?i)(кажется|отсутствует|текст для редактирования|ваш запрос|если вы отправите|я готов|уважаемый коллега)', '', humanized_body)
                    result.append(header + humanized_body)
                else:
                    result.append(sections[i])
            return ''.join(result)
        except Exception as e:
            logger.error(f"Ошибка гуманизации диплома: {e}", exc_info=True)
            return text