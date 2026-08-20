# quiz_generator.py
import json
import re
import logging
from llm_client import call_llm

logger = logging.getLogger(__name__)


class QuizGenerator:
    SYSTEM_PROMPT = (
        "Ты — преподаватель, составляешь тесты по конспекту лекции. "
        "Ответь ТОЛЬКО JSON-массивом. Каждый объект:\n"
        '  {"question": "...", "options": ["A", "B", "C", "D"], "correct": 0}\n'
        "correct — индекс правильного ответа (0-3). "
        "Вопросы должны проверять понимание. Без пояснений, только JSON."
    )

    def generate(self, text: str, count: int = 5) -> list[dict]:
        prompt = f"Составь {count} вопросов по следующему конспекту:\n\n{text[:4000]}\n\nJSON:"
        try:
            raw = call_llm(prompt=prompt, system=self.SYSTEM_PROMPT, model="fast", num_predict=2000)
            return self._parse(raw, count)
        except Exception as e:
            logger.error(f"QuizGenerator: {e}", exc_info=True)
            return []

    def _parse(self, raw: str, expected: int) -> list[dict]:
        raw = raw.strip()
        if "```" in raw:
            m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
            if m:
                raw = m.group(1).strip()
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return self._validate(data, expected)
            if isinstance(data, dict) and "questions" in data:
                return self._validate(data["questions"], expected)
        except json.JSONDecodeError:
            pass
        return self._fallback_parse(raw, expected)

    def _validate(self, items: list, expected: int) -> list[dict]:
        valid = []
        for item in items:
            if not isinstance(item, dict):
                continue
            q = item.get("question", "")
            opts = item.get("options", [])
            corr = item.get("correct", 0)
            if q and len(opts) == 4 and 0 <= corr <= 3:
                valid.append({
                    "question": q,
                    "options": [str(o) for o in opts],
                    "correct": int(corr),
                })
        return valid[:expected]

    def _fallback_parse(self, raw: str, expected: int) -> list[dict]:
        questions = []
        blocks = re.split(r'\n\s*(?:Вопрос\s*\d+[.:]|(?:\d+\.\s+))', raw)
        for block in blocks[1:]:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if len(lines) < 5:
                continue
            q = lines[0]
            opts = lines[1:5]
            corr = 0
            for i, opt in enumerate(opts):
                if any(m in opt.lower() for m in ['(верно)', '(правильно)', '✓', '->']):
                    corr = i
                    opts[i] = re.sub(r'\s*[(✓->].*', '', opt).strip()
            questions.append({
                "question": q,
                "options": opts,
                "correct": corr,
            })
            if len(questions) >= expected:
                break
        return questions

    def to_poll_params(self, quiz: dict) -> dict:
        return {
            "question": quiz["question"],
            "options": quiz["options"],
            "type": "quiz",
            "correct_option_id": quiz["correct"],
            "explanation": "Правильный ответ выделен.",
            "is_anonymous": False,
        }