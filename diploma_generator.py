# diploma_generator.py — генерация диплома (вынесено из task_queue)
import re
import logging
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
    """
    Удаляет повторяющуюся нумерацию в начале абзацев вида "1.1 ", "1.1." и т.п.
    Также удаляет строки, которые явно являются служебными или не относятся к теме.
    """
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        # Убираем нумерацию вида "X.Y " или "X.Y." в начале строки
        line = re.sub(r'^\s*\d+\.\d+\s*\.?\s*', '', line)
        # Убираем нумерацию вида "X. " (если осталась)
        line = re.sub(r'^\s*\d+\.\s*', '', line)
        # Если строка содержит явно служебные фразы, пропускаем её
        if re.search(r'(кажется|отсутствует|текст для редактирования|ваш запрос|уважаемый коллега)', line, re.I):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)

def _ensure_valid_structure(structure, work_type):
    """
    Проверяет, что структура валидна и содержит все необходимые главы с подразделами.
    Если нет — создаёт структуру по умолчанию.
    """
    wt = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])
    required_chapters = wt['chapters']
    required_subs = wt['subsections_per_chapter']

    if not structure or not isinstance(structure, list) or len(structure) == 0:
        logger.warning(f"Структура пуста или невалидна, создаём дефолтную для {work_type}")
        return _create_default_structure(work_type, required_chapters, required_subs)

    valid = True
    for ch in structure:
        if not ch.get('title') or not isinstance(ch.get('subsections'), list) or len(ch['subsections']) == 0:
            valid = False
            break

    if not valid:
        logger.warning(f"Структура содержит пустые главы, создаём дефолтную для {work_type}")
        return _create_default_structure(work_type, required_chapters, required_subs)

    if len(structure) < required_chapters:
        logger.info(f"Добавляем недостающие главы до {required_chapters}")
        for i in range(len(structure) + 1, required_chapters + 1):
            chapter_title = f"Глава {i}"
            subs = [f"Подраздел {i}.{j}" for j in range(1, required_subs + 1)]
            structure.append({"title": chapter_title, "subsections": subs})

    for ch_idx, ch in enumerate(structure, start=1):
        subs = ch.get('subsections', [])
        if len(subs) < required_subs:
            current = len(subs)
            for j in range(current + 1, required_subs + 1):
                subs.append(f"Подраздел {ch_idx}.{j}")
            ch['subsections'] = subs
            logger.info(f"Добавлены недостающие подразделы в главу {ch_idx}")

    return structure

def _create_default_structure(work_type, chapters_count, subs_per_chapter):
    structure = []
    for i in range(1, chapters_count + 1):
        chapter_title = f"Глава {i}"
        subs = [f"Подраздел {i}.{j}" for j in range(1, subs_per_chapter + 1)]
        structure.append({"title": chapter_title, "subsections": subs})
    return structure

def generate_diploma(payload: dict, user_id: int, notify_func, check_cancelled_func):
    """
    Генерирует полный текст диплома с таблицами, графиками и реальными источниками.
    """
    work_type = payload['work_type']
    wt = WORK_TYPES.get(work_type, WORK_TYPES['diploma'])
    num_predict = wt.get('num_predict', 16000)
    standard = payload['standard']
    topic = payload['topic']
    goal = payload['goal']

    # Сбор данных из интернета
    notify_func(user_id, "🔍 Собираю информацию по вашей теме из интернета...")
    collected = _data_collector.collect(topic, max_pages=3)
    internet_context = "Собранные данные из интернета:\n"
    for res in collected["search_results"]:
        internet_context += f"- {res['title']} ({res['link']})\n"
        if res['snippet']:
            internet_context += f"  {res['snippet']}\n"
    internet_context += "\nСодержание страниц:\n"
    for page in collected["pages_text"]:
        internet_context += f"--- {page['url']} ---\n{page['text'][:1500]}\n\n"
    if collected["rss_news"]:
        internet_context += "Свежие новости по теме:\n"
        for news in collected["rss_news"]:
            internet_context += f"- {news['title']} ({news['link']})\n"

    base_system = get_system_prompt(standard, work_type)
    system = base_system + "\n\n" + internet_context

    # Проверка и восстановление структуры
    raw_structure = payload.get('structure')
    structure = _ensure_valid_structure(raw_structure, work_type)
    payload['structure'] = structure

    extra_sections = wt.get('extra_sections', [])
    subsections_per_chapter = len(structure[0]['subsections']) if structure else 0

    notify_func(user_id, "🔍 Ищу реальные источники литературы...")
    real_sources = fetch_sources(topic, count=15)
    sources_text = "\n".join([f"{i+1}. {s['author']}. {s['title']} // {s['journal']} ({s['year']})" for i, s in enumerate(real_sources)]) if real_sources else "Источники не найдены."

    parts = []
    context = f"Тема: {topic}\nЦель: {goal}\n"
    if real_sources:
        context += f"Доступные источники для цитирования:\n{sources_text}\n\n"

    total_steps = 1 + len(structure) * (1 + subsections_per_chapter) + 1 + len(extra_sections) + 1
    step = 0
    intro = ""

    # 1. Введение
    step += 1
    notify_func(user_id, f"📝 Генерирую введение ({step}/{total_steps})...")
    intro_prompt = (
        f"Напиши ВВЕДЕНИЕ для {work_type} на тему \"{topic}\". "
        f"Цель работы: {goal}. "
        f"Используй структуру: актуальность, объект, предмет, цель, задачи, методы, научная новизна, практическая значимость. "
        f"Объём введения должен быть не менее 3000 символов. "
        f"Если есть реальные источники, ссылайся на них в тексте (например, [1], [2] или (Автор, год)). "
        f"Список источников для цитирования:\n{sources_text}\n"
        f"Начни сразу с текста. Не используй маркдаун и специальные символы."
    )
    intro = call_llm(intro_prompt, system, model="powerful", num_predict=num_predict)
    intro = clean_markdown(intro)
    check_cancelled_func()
    parts.append(("ВВЕДЕНИЕ", intro))
    context += f"Введение: {intro[:500]}...\n"

    # 2. Главы
    for ch_idx, chapter in enumerate(structure, start=1):
        original_title = chapter['title']
        if re.search(r'^глава\s+\d+', original_title, re.I):
            chapter_title = re.sub(r'(\d+)', str(ch_idx), original_title, count=1)
        else:
            chapter_title = f"Глава {ch_idx}. {original_title}"
        subs = chapter['subsections']

        step += 1
        notify_func(user_id, f"📖 Генерирую {chapter_title} ({step}/{total_steps})...")
        chapter_intro_prompt = (
            f"Напиши вступительный абзац для главы {ch_idx} '{original_title}' для {work_type} на тему '{topic}'. "
            f"Кратко опиши, что будет рассмотрено в этой главе. "
            f"Учитывай уже написанное содержание: {context[:1500]}"
        )
        chapter_intro = call_llm(chapter_intro_prompt, system, model="powerful", num_predict=num_predict // 2)
        chapter_intro = clean_markdown(chapter_intro)
        chapter_intro = re.sub(r'(?i)(если присмотреться|кажется|обратите внимание|давайте рассмотрим)', '', chapter_intro)
        check_cancelled_func()
        chapter_text = f"{chapter_title}\n{chapter_intro}\n\n"

        for sub_idx, sub_title in enumerate(subs, start=1):
            sub_prompt = (
                f"Напиши содержание подраздела '{sub_title}' для главы '{original_title}' "
                f"в рамках {work_type} на тему '{topic}'. "
                f"Цель работы: {goal}. "
                f"Учитывай контекст: {context[:1500]}\n"
                f"Используй реальные источники для подтверждения фактов и цитирования. "
                f"Список источников:\n{sources_text}\n"
                f"Требования: конкретные технологии, версии, числовые данные, примеры, расчёты, сравнительные таблицы. "
                f"Объём подраздела должен составлять не менее 4000 символов. "
                f"Раскрывай тему подробно, с пояснениями и аргументацией.\n"
                f"ВАЖНО: Не нумеруй подразделы в начале текста, не пиши цифры с точкой. Мы добавим нумерацию сами. "
                f"Просто текст без маркдауна."
            )
            sub_content = call_llm(sub_prompt, system, model="powerful", num_predict=num_predict)
            sub_content = clean_markdown(sub_content)
            sub_content = _clean_subsection_content(sub_content)
            check_cancelled_func()
            chapter_text += f"{ch_idx}.{sub_idx} {sub_title}\n{sub_content}\n\n"

        parts.append((chapter_title.upper(), chapter_text))
        context += f"{chapter_title}: {chapter_text[:500]}...\n"

    # 3. Дополнительные разделы (если есть)
    if extra_sections:
        step += 1
        notify_func(user_id, f"📋 Генерирую дополнительные разделы ({step}/{total_steps})...")
        for sec_name in extra_sections:
            prompt = get_extra_section_prompt(sec_name, topic, goal, context)
            content = call_llm(prompt, None, model="powerful", num_predict=num_predict // 2)
            content = clean_markdown(content)
            check_cancelled_func()
            parts.append((sec_name.upper(), content))

    # 4. Заключение
    step += 1
    notify_func(user_id, f"📝 Генерирую заключение ({step}/{total_steps})...")
    conclusion_prompt = (
        f"Напиши ЗАКЛЮЧЕНИЕ для {work_type} на тему \"{topic}\". "
        f"Цель работы: {goal}. "
        f"Кратко подведи итог по каждой задаче, оценка достижения цели, направления для дальнейшего развития. "
        f"Объём заключения должен быть не менее 2000 символов. "
        f"Не повторяй текст предыдущих разделов, дай обобщающие выводы. "
        f"Не используй служебные фразы, не обращайся к пользователю, пиши строго научный текст."
    )
    conclusion = call_llm(conclusion_prompt, system, model="powerful", num_predict=num_predict // 2)
    conclusion = clean_markdown(conclusion)
    conclusion = re.sub(r'(?i)(кажется|отсутствует|текст для редактирования|ваш запрос|если вы отправите|я готов|уважаемый коллега)', '', conclusion)
    check_cancelled_func()
    parts.append(("ЗАКЛЮЧЕНИЕ", conclusion))

    # 5. Список литературы
    step += 1
    notify_func(user_id, f"📚 Генерирую список литературы ({step}/{total_steps})...")
    if real_sources:
        bibliography = format_bibliography(real_sources, standard)
    else:
        from gost_standards import get_bibliography_prompt
        lit_prompt = get_bibliography_prompt(standard, min_sources=15) + f"\n\nТема: {topic}\nИсточники: {payload.get('sources', '')}"
        bibliography = call_llm(lit_prompt, None, model="fast", num_predict=num_predict // 2)
    bibliography = clean_markdown(bibliography)
    check_cancelled_func()
    parts.append(("СПИСОК ЛИТЕРАТУРЫ", bibliography))

    # === ИСПРАВЛЕНИЕ ПРОПАДАНИЯ ГЛАВ ===
    expected_chapters = len(structure)
    actual_chapters = len([p for p in parts if any(x in p[0].upper() for x in ['ГЛАВА', 'ГЛАВ'])])
    if actual_chapters < expected_chapters:
        logger.warning(f"Сгенерировано только {actual_chapters} глав из {expected_chapters}, добавляем недостающие")
        for ch_idx in range(actual_chapters + 1, expected_chapters + 1):
            ch_title = structure[ch_idx-1]['title'] if ch_idx-1 < len(structure) else f"Глава {ch_idx}"
            parts.append((f"ГЛАВА {ch_idx}. {ch_title}",
                          f"Содержание главы {ch_idx} не было сгенерировано. Пожалуйста, проверьте."))
    # ==========================================

    # Собираем итоговый текст
    result_text = ""
    for heading, body in parts:
        result_text += f"=== {heading} ===\n{body}\n\n"

    # Генерация таблиц и графиков
    notify_func(user_id, "📊 Генерирую таблицы и графики...")
    images = {}
    table_counter = 1
    figure_counter = 1

    table_data_list = generate_table_data(result_text, topic, context, num_tables=2)
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

    result_text = clean_markdown(result_text)

    # Проверка наличия введения
    if "=== ВВЕДЕНИЕ ===" not in result_text:
        logger.warning("Введение отсутствует в финальном тексте, вставляем заново")
        result_text = f"=== ВВЕДЕНИЕ ===\n{intro}\n\n" + result_text
    else:
        intro_match = re.search(r'=== ВВЕДЕНИЕ ===\n(.*?)(?=\n===|$)', result_text, re.DOTALL)
        if intro_match and len(intro_match.group(1).strip()) < 100:
            result_text = re.sub(r'=== ВВЕДЕНИЕ ===\n.*?(?=\n===|$)', f'=== ВВЕДЕНИЕ ===\n{intro}', result_text, flags=re.DOTALL)

    # Расчёт страниц
    clean_text = re.sub(r'\[ТАБЛИЦА\s*\d+\]', '', result_text)
    clean_text = re.sub(r'\[(РИСУНОК|ГРАФИК)\s*\d+\]', '', clean_text)
    char_count = len(clean_text)
    estimated_pages = max(1, round(char_count / 1800))
    payload['volume_pages'] = estimated_pages
    logger.info(f"Расчётное количество страниц: {estimated_pages} (символов: {char_count})")

    # Гуманизация
    try:
        h = Humanizer()
        result_text = h.humanize_diploma(result_text)
        result_text = re.sub(r'(?i)(кажется|отсутствует|текст для редактирования|ваш запрос|если вы отправите|я готов|уважаемый коллега)', '', result_text)
        logger.info("Диплом гуманизирован и очищен.")
    except Exception as e:
        logger.error(f"Ошибка гуманизации диплома: {e}", exc_info=True)

    return result_text