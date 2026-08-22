# diploma_generator.py — пошаговая генерация с адаптивным объёмом
import re
import logging
import time
from datetime import datetime

from llm_client import call_llm
from gost_standards import get_system_prompt, WORK_TYPES, get_extra_section_prompt
from sources_fetcher import fetch_sources, format_bibliography
from data_collector import DataCollector
from chart_generator import generate_table_data, render_table_as_image, generate_chart_data, render_chart
from utils_common import clean_markdown
from humanizer import Humanizer
from utils.diploma_utils import parse_diploma_text

logger = logging.getLogger(__name__)
_data_collector = DataCollector()

def _clean_subsection_content(text: str) -> str:
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = re.sub(r'^\s*\d+\.\d+\s*\.?\s*', '', line)
        line = re.sub(r'^\s*\d+\.\s*', '', line)
        if re.search(r'(кажется|отсутствует|текст для редактирования|ваш запрос|уважаемый коллега)', line, re.I):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)

def _ensure_valid_structure(structure, work_type):
    wt = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])
    required_chapters = wt['chapters']
    required_subs = wt['subsections_per_chapter']

    if not structure or not isinstance(structure, list) or len(structure) == 0:
        logger.warning(f"Структура пуста, создаём дефолтную для {work_type}")
        return _create_default_structure(work_type, required_chapters, required_subs)

    valid = True
    for ch in structure:
        if not ch.get('title') or not isinstance(ch.get('subsections'), list) or len(ch['subsections']) == 0:
            valid = False
            break
    if not valid:
        return _create_default_structure(work_type, required_chapters, required_subs)

    if len(structure) < required_chapters:
        for i in range(len(structure) + 1, required_chapters + 1):
            structure.append({"title": f"Глава {i}", "subsections": [f"{i}.{j}" for j in range(1, required_subs+1)]})
    for ch_idx, ch in enumerate(structure, start=1):
        if len(ch['subsections']) < required_subs:
            for j in range(len(ch['subsections'])+1, required_subs+1):
                ch['subsections'].append(f"{ch_idx}.{j}")
    return structure

def _create_default_structure(work_type, chapters_count, subs_per_chapter):
    return [{"title": f"Глава {i}", "subsections": [f"{i}.{j}" for j in range(1, subs_per_chapter+1)]} for i in range(1, chapters_count+1)]

def generate_diploma(payload: dict, user_id: int, notify_func, check_cancelled_func):
    work_type = payload['work_type']
    wt = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])
    standard = payload['standard']
    topic = payload['topic']
    goal = payload['goal']

    # Определяем параметры объёма в зависимости от типа работы
    if work_type in ['candidate', 'doctor']:
        sub_max_tokens = 6000
        intro_max_tokens = 5000
        conclusion_max_tokens = 5000
        chap_intro_tokens = 1500
        extra_tokens = 3500
        lit_tokens = 3000
        logger.info(f"Режим повышенного объёма для {work_type}")
    else:
        sub_max_tokens = 4000
        intro_max_tokens = 3500
        conclusion_max_tokens = 3500
        chap_intro_tokens = 1200
        extra_tokens = 2500
        lit_tokens = 2000

    # 1. Сбор данных из интернета (сокращённый)
    notify_func(user_id, "🔍 Собираю информацию по теме...")
    collected = _data_collector.collect(topic, max_pages=2)
    internet_context = "Собранные данные:\n"
    for res in collected["search_results"]:
        internet_context += f"- {res['title']}\n"
        if res['snippet']:
            internet_context += f"  {res['snippet']}\n"
    for page in collected["pages_text"]:
        internet_context += f"--- {page['url']} ---\n{page['text'][:600]}\n\n"
    if collected["rss_news"]:
        internet_context += "Новости:\n" + "\n".join([f"- {n['title']}" for n in collected["rss_news"]])
    if len(internet_context) > 1000:
        internet_context = internet_context[:1000] + "... (обрезано)"

    system = get_system_prompt(standard, work_type) + "\n\n" + internet_context

    # ===== ВАЖНОЕ ДОПОЛНЕНИЕ: принудительный русский язык =====
    system += "\n\nОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ. НИ СЛОВА НА АНГЛИЙСКОМ, КРОМЕ ОБЩЕПРИНЯТЫХ ТЕРМИНОВ (например, API, CPU). ВЕСЬ ТЕКСТ ДОЛЖЕН БЫТЬ НА РУССКОМ."

    # 2. Поиск источников
    sources_count = 25 if work_type in ['candidate', 'doctor'] else 15
    notify_func(user_id, f"🔍 Ищу реальные источники литературы ({sources_count})...")
    real_sources = fetch_sources(topic, count=sources_count)
    sources_text = "\n".join([f"{i+1}. {s['author']}. {s['title']} // {s['journal']} ({s['year']})" for i, s in enumerate(real_sources)]) if real_sources else "Источники не найдены."

    # 3. Подготовка структуры
    structure = _ensure_valid_structure(payload.get('structure'), work_type)
    payload['structure'] = structure
    extra_sections = wt.get('extra_sections', [])
    subs_count = len(structure[0]['subsections']) if structure else 3

    # Словарь для хранения сгенерированных частей
    parts = {}
    context_summary = f"Тема: {topic}\nЦель: {goal}\n"

    total_steps = 1 + len(structure) * (1 + subs_count) + 1 + len(extra_sections) + 1
    step = 0

    # ---- ВВЕДЕНИЕ ----
    step += 1
    notify_func(user_id, f"📝 Генерирую введение ({step}/{total_steps})...")
    intro_prompt = (
        f"Напиши развёрнутое ВВЕДЕНИЕ для {work_type} на тему '{topic}'. "
        f"Цель: {goal}. "
        f"Структура: актуальность (с обоснованием), объект, предмет, цель, задачи (5-7), методы, научная новизна, практическая значимость, структура работы. "
        f"Объём: не менее {intro_max_tokens//2} символов. Приведи конкретные факты, статистику, цитаты из источников. "
        f"Используй источники: {sources_text[:600]}. "
        f"Пиши академическим языком, но избегай шаблонных фраз. Начни сразу с текста, без вступлений. "
        f"ВСЕГДА ОТВЕЧАЙ НА РУССКОМ ЯЗЫКЕ."
    )
    intro = _call_with_retry(intro_prompt, system, "powerful", max_tokens=intro_max_tokens, max_retries=3)
    intro = clean_markdown(intro)
    check_cancelled_func()
    parts["ВВЕДЕНИЕ"] = intro
    context_summary += f"Введение: {intro[:300]}...\n"

    # ---- ГЛАВЫ ----
    for ch_idx, chapter in enumerate(structure, start=1):
        original_title = chapter['title']
        if re.search(r'^глава\s+\d+', original_title, re.I):
            ch_title_display = re.sub(r'(\d+)', str(ch_idx), original_title, count=1)
        else:
            ch_title_display = f"Глава {ch_idx}. {original_title}"

        ch_key = f"ГЛАВА {ch_idx}. {original_title}".upper()

        step += 1
        notify_func(user_id, f"📖 Генерирую {ch_title_display} ({step}/{total_steps})...")

        # Вступление к главе
        chapter_intro_prompt = (
            f"Напиши вступительный абзац для главы '{original_title}' (около {chap_intro_tokens//2} символов) "
            f"для {work_type} на тему '{topic}'. Укажи, какие вопросы будут рассмотрены, и как они связаны с общей целью работы. "
            f"Опиши структуру главы и её место в исследовании. "
            f"ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ."
        )
        ch_intro = _call_with_retry(chapter_intro_prompt, system, "fast", max_tokens=chap_intro_tokens, max_retries=2)
        ch_intro = clean_markdown(ch_intro)
        check_cancelled_func()

        chapter_text = f"{ch_title_display}\n{ch_intro}\n\n"

        # Подразделы
        for sub_idx, sub_title in enumerate(chapter['subsections'], start=1):
            sub_prompt = (
                f"Напиши подробное содержание подраздела '{sub_title}' (не менее {sub_max_tokens//2} символов) "
                f"для главы '{original_title}' в рамках {work_type} на тему '{topic}'. "
                f"Цель: {goal}. "
                f"Раскрой тему максимально детально: приведи конкретные технологии, версии, числовые данные, примеры, расчёты, сравнительные таблицы. "
                f"Используй не менее 5 источников из списка для цитирования: {sources_text[:500]}. "
                f"Проанализируй различные точки зрения, сделай собственные выводы. "
                f"Избегай общих фраз, пиши содержательно, с глубокой аргументацией. "
                f"Оформи текст как научный, но без шаблонных оборотов. "
                f"Начни сразу с содержания, без повторения названия подраздела. "
                f"ВСЕГДА ОТВЕЧАЙ НА РУССКОМ ЯЗЫКЕ."
            )
            sub_content = _call_with_retry(sub_prompt, system, "fast", max_tokens=sub_max_tokens, max_retries=3)
            sub_content = clean_markdown(sub_content)
            sub_content = _clean_subsection_content(sub_content)
            check_cancelled_func()
            chapter_text += f"{ch_idx}.{sub_idx} {sub_title}\n{sub_content}\n\n"

        parts[ch_key] = chapter_text
        context_summary += f"{ch_title_display}: {chapter_text[:300]}...\n"

    # ---- ДОПОЛНИТЕЛЬНЫЕ РАЗДЕЛЫ ----
    if extra_sections:
        step += 1
        notify_func(user_id, f"📋 Генерирую дополнительные разделы ({step}/{total_steps})...")
        for sec_name in extra_sections:
            prompt = get_extra_section_prompt(sec_name, topic, goal, context_summary)
            # Добавляем требование русского языка
            prompt += "\n\nОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ."
            content = _call_with_retry(prompt, None, "fast", max_tokens=extra_tokens, max_retries=2)
            content = clean_markdown(content)
            check_cancelled_func()
            parts[sec_name.upper()] = content

    # ---- ЗАКЛЮЧЕНИЕ ----
    step += 1
    notify_func(user_id, f"📝 Генерирую заключение ({step}/{total_steps})...")
    conclusion_prompt = (
        f"Напиши развёрнутое ЗАКЛЮЧЕНИЕ для {work_type} на тему '{topic}'. "
        f"Цель: {goal}. "
        f"Подведи итоги по каждой задаче, оцени достижение цели, сформулируй основные выводы и практические рекомендации. "
        f"Укажи направления для дальнейшего развития. "
        f"Объём: не менее {conclusion_max_tokens//2} символов. "
        f"Используй ссылки на собственные результаты, не повторяй текст предыдущих разделов. "
        f"ВСЕГДА ОТВЕЧАЙ НА РУССКОМ ЯЗЫКЕ."
    )
    conclusion = _call_with_retry(conclusion_prompt, system, "fast", max_tokens=conclusion_max_tokens, max_retries=2)
    conclusion = clean_markdown(conclusion)
    check_cancelled_func()
    parts["ЗАКЛЮЧЕНИЕ"] = conclusion

    # ---- СПИСОК ЛИТЕРАТУРЫ ----
    step += 1
    notify_func(user_id, f"📚 Генерирую список литературы ({step}/{total_steps})...")
    if real_sources:
        bibliography = format_bibliography(real_sources, standard)
    else:
        from gost_standards import get_bibliography_prompt
        lit_prompt = get_bibliography_prompt(standard, min_sources=sources_count) + f"\n\nТема: {topic}\nИсточники: {payload.get('sources', '')}"
        lit_prompt += "\n\nОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ."
        bibliography = _call_with_retry(lit_prompt, None, "fast", max_tokens=lit_tokens, max_retries=2)
    bibliography = clean_markdown(bibliography)
    check_cancelled_func()
    parts["СПИСОК ЛИТЕРАТУРЫ"] = bibliography

    # ---- ПРОВЕРКА НАЛИЧИЯ ВСЕХ ГЛАВ ----
    expected_chapters = len(structure)
    actual_chapter_keys = [k for k in parts.keys() if any(x in k.upper() for x in ['ГЛАВА', 'ГЛАВ'])]
    if len(actual_chapter_keys) < expected_chapters:
        logger.warning(f"Сгенерировано только {len(actual_chapter_keys)} глав из {expected_chapters}, добавляем недостающие.")
        for ch_idx in range(1, expected_chapters + 1):
            ch_title = structure[ch_idx-1]['title']
            key = f"ГЛАВА {ch_idx}. {ch_title}".upper()
            if key not in parts:
                parts[key] = f"Содержание главы {ch_idx} будет доработано позже. Пожалуйста, проверьте."

    # ---- СБОРКА ИТОГОВОГО ТЕКСТА (СТРОГО ПО ПОРЯДКУ) ----
    order = ["ВВЕДЕНИЕ"]
    for ch_idx in range(1, expected_chapters+1):
        ch_title = structure[ch_idx-1]['title']
        key = f"ГЛАВА {ch_idx}. {ch_title}".upper()
        order.append(key)
    order.append("ЗАКЛЮЧЕНИЕ")
    order.append("СПИСОК ЛИТЕРАТУРЫ")
    for sec in extra_sections:
        order.append(sec.upper())

    result_text = ""
    for heading in order:
        if heading in parts:
            result_text += f"=== {heading} ===\n{parts[heading]}\n\n"
        else:
            logger.error(f"Раздел {heading} отсутствует даже после проверки! Добавляем экстренную заглушку.")
            result_text += f"=== {heading} ===\n(Раздел не сгенерирован – проверьте логи)\n\n"

    # ---- ГЕНЕРАЦИЯ ТАБЛИЦ И ГРАФИКОВ ----
    notify_func(user_id, "📊 Генерирую таблицы и графики...")
    images = {}
    table_counter = 1
    figure_counter = 1

    table_data_list = generate_table_data(result_text, topic, context_summary, num_tables=3)
    for td in table_data_list:
        try:
            img_bytes = render_table_as_image(td)
            images[f"table_{table_counter}"] = img_bytes.getvalue()
            table_counter += 1
        except Exception as e:
            logger.error(f"Table render error: {e}")

    chart_data_list = generate_chart_data(result_text, topic)
    for cd in chart_data_list:
        try:
            img_bytes = render_chart(cd)
            images[f"figure_{figure_counter}"] = img_bytes.getvalue()
            figure_counter += 1
        except Exception as e:
            logger.error(f"Chart render error: {e}")

    if images:
        markers_text = ""
        for i in range(1, table_counter):
            markers_text += f"\n[ТАБЛИЦА {i}]"
        for i in range(1, figure_counter):
            markers_text += f"\n[РИСУНОК {i}]"
        if "=== ЗАКЛЮЧЕНИЕ ===" in result_text:
            result_text = result_text.replace("=== ЗАКЛЮЧЕНИЕ ===", markers_text + "\n\n=== ЗАКЛЮЧЕНИЕ ===")
        else:
            result_text += markers_text
        payload['images'] = images

    # ---- ОЦЕНКА ОБЪЁМА ----
    clean_text = re.sub(r'\[ТАБЛИЦА\s*\d+\]', '', result_text)
    clean_text = re.sub(r'\[(РИСУНОК|ГРАФИК)\s*\d+\]', '', clean_text)
    char_count = len(clean_text)
    estimated_pages = max(1, round(char_count / 1800))
    payload['volume_pages'] = estimated_pages
    logger.info(f"Расчётное количество страниц: {estimated_pages} (символов: {char_count})")
    if estimated_pages < wt['min_pages']:
        logger.warning(f"Объём ({estimated_pages} стр.) меньше минимального для {work_type} ({wt['min_pages']} стр.). Рекомендуется увеличить max_tokens или добавить подразделы.")

    # ---- ГУМАНИЗАЦИЯ ----
    try:
        h = Humanizer()
        result_text = h.humanize_diploma(result_text)
        result_text = h.humanize(result_text)
        result_text = re.sub(r'(?i)(кажется|отсутствует|текст для редактирования|ваш запрос|если вы отправите|я готов|уважаемый коллега)', '', result_text)
        logger.info("Диплом гуманизирован (двойной проход).")
    except Exception as e:
        logger.error(f"Гуманизация не удалась: {e}")

    return result_text


def _call_with_retry(prompt, system, model, max_tokens, max_retries=3):
    """Вызывает LLM с уменьшением max_tokens при 413 и паузами при 429."""
    current_tokens = max_tokens
    for attempt in range(max_retries):
        try:
            return call_llm(
                prompt=prompt,
                system=system,
                model=model,
                num_predict=current_tokens,
                temperature=0.85,
                top_p=0.9,
                retries=2
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "payload too large" in error_msg or "413" in error_msg:
                current_tokens = max(500, current_tokens // 2)
                logger.warning(f"413 – уменьшаем max_tokens до {current_tokens}, повторяем...")
                time.sleep(1)
                continue
            elif "rate_limit" in error_msg or "429" in error_msg:
                wait = 5 * (attempt + 1) + 2
                logger.warning(f"429 – ждём {wait} секунд и повторяем...")
                time.sleep(wait)
                continue
            else:
                logger.warning(f"Ошибка (попытка {attempt+1}): {e}")
                time.sleep(2)
                continue
    logger.error(f"Не удалось сгенерировать раздел после {max_retries} попыток.")
    return f"[ОШИБКА ГЕНЕРАЦИИ – попробуйте позже]"