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
        """Лёгкая гуманизация для коротких текстов."""
        try:
            system_prompt = config.HUMANIZE_PROMPT.format(text=text)
            result = call_llm(
                prompt="",
                system=system_prompt,
                model="fast",
                num_predict=3000
            )
            result = self._post_process(result)
            return result
        except Exception as e:
            logger.error(f"Ошибка гуманизации: {e}", exc_info=True)
            return text

    def humanize_diploma(self, text: str) -> str:
        """Полная гуманизация диплома с усиленным промптом."""
        try:
            sections = re.split(r'(=== .+? ===)', text)
            result = []
            for i in range(0, len(sections), 2):
                if i+1 < len(sections):
                    header = sections[i]
                    body = sections[i+1]
                    # Не гуманизируем список литературы и приложения
                    if 'СПИСОК ЛИТЕРАТУРЫ' in header.upper() or 'ПРИЛОЖЕНИ' in header.upper():
                        result.append(header + body)
                        continue
                    # Усиленный промпт
                    system_prompt = (
                        "Ты — опытный научный редактор с 15-летним стажем. Перепиши следующий академический текст так, чтобы он звучал максимально естественно, живо и убедительно, как если бы его писал учёный с большим стажем.\n\n"
                        "Требования:\n"
                        "- Избегай шаблонных фраз: «следует отметить», «важно подчеркнуть», «в заключение хочется сказать», «таким образом», «во-первых», «во-вторых» — заменяй их на разнообразные вводные конструкции.\n"
                        "- Чередуй длину предложений: короткие для акцента, длинные для объяснений.\n"
                        "- Используй активный залог чаще, чем пассивный.\n"
                        "- Добавляй оценочные суждения, сомнения, сравнения — текст должен отражать живую мысль, а не сухой пересказ.\n"
                        "- Вводи примеры из реальной практики и гипотетические наблюдения.\n"
                        "- Не теряй научную точность и фактологию.\n"
                        "- Сохрани структуру разделов, но сделай переходы между ними плавными.\n"
                        "- Старайся избегать повторений одних и тех же слов в соседних предложениях.\n"
                        "- Если есть перечисления, оформи их как связный текст.\n"
                        "- Вставь дополнительные пояснения и аргументы, чтобы увеличить объём на 15–20% без потери качества.\n\n"
                        f"Текст для редактирования:\n{body}"
                    )
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