# chart_generator.py — генерация таблиц и графиков
import io
import re
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Any
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from llm_client import call_llm
import config

logger = logging.getLogger(__name__)

# Исправленная загрузка шрифтов
try:
    import matplotlib.font_manager as fm
    font_paths = [
        "C:/Windows/Fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        str(config.FONTS_DIR / "DejaVuSans.ttf"),
        str(config.FONTS_DIR / "LiberationSans-Regular.ttf"),
    ]
    for fp in font_paths:
        if Path(fp).exists():
            fm.fontManager.addfont(fp)
            plt.rcParams['font.family'] = ['sans-serif']
            plt.rcParams['font.sans-serif'] = [Path(fp).stem]
            break
    else:
        plt.rcParams['font.family'] = ['sans-serif']
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Liberation Sans']
except Exception as e:
    logger.warning(f"Не удалось настроить шрифты matplotlib: {e}")

def generate_table_data(text: str, topic: str, context: str = "", num_tables: int = 2, max_retries: int = 2) -> List[Dict]:
    prompt = (
        f"Ты — аналитик данных. Проанализируй следующий текст на тему '{topic}' и предложи {num_tables} таблиц, "
        "которые могли бы визуализировать ключевые данные.\n\n"
        f"Контекст: {context[:2000]}\n\n"
        f"Текст:\n{text[:3000]}\n\n"
        "Для каждой таблицы укажи: название, заголовки столбцов (массив), строки данных (массив массивов), подпись.\n"
        "Ответ дай в формате JSON-массива. Пример:\n"
        "[\n"
        "  {\n"
        "    \"title\": \"Сравнение характеристик\",\n"
        "    \"headers\": [\"Параметр\", \"Решение A\", \"Решение B\"],\n"
        "    \"rows\": [[\"Скорость\", \"100\", \"150\"], [\"Цена\", \"500\", \"700\"]],\n"
        "    \"caption\": \"Таблица 1 – Сравнение характеристик\"\n"
        "  }\n"
        "]\n"
        "Если данные не подходят для таблиц, верни пустой массив []."
    )
    for attempt in range(max_retries):
        try:
            raw = call_llm(prompt, system="Ты — аналитик данных. Отвечай только JSON.", model="fast", num_predict=2000)
            raw = re.sub(r'```json\s*|```', '', raw).strip()
            data = json.loads(raw)
            if isinstance(data, list):
                valid = []
                for item in data:
                    if isinstance(item, dict) and 'headers' in item and 'rows' in item and item.get('title'):
                        valid.append(item)
                if valid:
                    return valid[:num_tables]
        except Exception as e:
            logger.warning(f"Table generation attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return []

def render_table_as_image(table_data: Dict, font_size: int = 10, dpi: int = config.CHART_DPI) -> io.BytesIO:
    headers = table_data.get('headers', [])
    rows = table_data.get('rows', [])
    title = table_data.get('title', 'Таблица')
    caption = table_data.get('caption', '')
    if not headers or not rows:
        raise ValueError("Table has no headers or rows")
    n_cols = len(headers)
    n_rows = len(rows) + 1
    col_widths = []
    for col_idx in range(n_cols):
        max_len = len(headers[col_idx]) if col_idx < len(headers) else 0
        for row in rows:
            if col_idx < len(row):
                max_len = max(max_len, len(str(row[col_idx])))
        col_widths.append(max(8, max_len + 2))
    row_height = font_size * 1.8
    fig_width = sum(col_widths) * 0.12 + 1.5
    fig_height = n_rows * row_height * 0.02 + 1.5
    fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=dpi)
    ax.axis('off')
    cell_text = [headers] + rows
    tb = ax.table(cellText=cell_text, loc='center', cellLoc='center',
                  colWidths=[w / sum(col_widths) for w in col_widths])
    tb.auto_set_font_size(False)
    tb.set_fontsize(font_size)
    for col in range(n_cols):
        cell = tb[(0, col)]
        cell.set_facecolor('#4472C4')
        cell.set_text_props(color='white', weight='bold')
    for i in range(1, n_rows):
        for j in range(n_cols):
            cell = tb[(i, j)]
            if i % 2 == 1:
                cell.set_facecolor('#D9E1F2')
            else:
                cell.set_facecolor('#E9EDF4')
    for (i, j), cell in tb.get_celld().items():
        cell.set_linewidth(0.5)
    if title:
        ax.set_title(title, fontsize=font_size + 4, weight='bold', pad=20)
    if caption:
        ax.text(0.5, -0.05, caption, transform=ax.transAxes, ha='center', va='top',
                fontsize=font_size - 2, style='italic')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.1, dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf

def generate_chart_data(text: str, topic: str, chart_types: List[str] = None, max_retries: int = 2) -> List[Dict]:
    if chart_types is None:
        chart_types = ['bar', 'pie', 'line']
    prompt = (
        f"Проанализируй текст на тему '{topic}' и предложи до 3 графиков для визуализации данных.\n"
        f"Текст:\n{text[:3000]}\n\n"
        "Для каждого графика укажи: название, тип (bar, pie, line), метки, значения, подписи осей, подпись.\n"
        "Ответ в формате JSON-массива. Пример:\n"
        "[\n"
        "  {\n"
        "    \"title\": \"Распределение бюджета\",\n"
        "    \"type\": \"pie\",\n"
        "    \"labels\": [\"Разработка\", \"Тестирование\", \"Внедрение\"],\n"
        "    \"values\": [40, 30, 30],\n"
        "    \"caption\": \"Рисунок 1 – Распределение бюджета\"\n"
        "  }\n"
        "]\n"
        "Если данные не подходят для графиков, верни пустой массив []."
    )
    for attempt in range(max_retries):
        try:
            raw = call_llm(prompt, system="Ты — аналитик данных. Отвечай только JSON.", model="fast", num_predict=2000)
            raw = re.sub(r'```json\s*|```', '', raw).strip()
            data = json.loads(raw)
            if isinstance(data, list):
                valid = []
                for item in data:
                    if 'title' in item and 'type' in item and 'labels' in item:
                        if item['type'] in chart_types and ('values' in item or 'series' in item):
                            valid.append(item)
                return valid[:3]
        except Exception as e:
            logger.warning(f"Chart generation attempt {attempt+1} failed: {e}")
            time.sleep(1)
    return []

def render_chart(chart_data: Dict, dpi: int = config.CHART_DPI) -> io.BytesIO:
    chart_type = chart_data.get('type', 'bar')
    title = chart_data.get('title', 'График')
    labels = chart_data.get('labels', [])
    values = chart_data.get('values', [])
    series = chart_data.get('series', [])
    xlabel = chart_data.get('xlabel', '')
    ylabel = chart_data.get('ylabel', '')
    caption = chart_data.get('caption', '')

    fig, ax = plt.subplots(figsize=(8, 5), dpi=dpi)

    if chart_type == 'pie':
        if not values:
            raise ValueError("No values for pie chart")
        ax.pie(values, labels=labels, autopct='%1.1f%%', startangle=90,
               colors=plt.cm.Paired(range(len(values))))
        ax.axis('equal')
        ax.set_title(title, weight='bold', pad=20)
        if caption:
            ax.text(0.5, -0.1, caption, transform=ax.transAxes, ha='center', fontsize=10, style='italic')

    elif chart_type == 'bar':
        if series:
            n_series = len(series)
            x = np.arange(len(labels))
            width = 0.8 / n_series if n_series > 0 else 0.8
            for i, s in enumerate(series):
                offset = (i - (n_series - 1) / 2) * width
                ax.bar(x + offset, s.get('values', []), width=width, label=s.get('label', f'Ряд {i+1}'))
            ax.set_xticks(x)
            ax.set_xticklabels(labels)
            ax.legend()
        else:
            ax.bar(labels, values, color=plt.cm.Paired(range(len(values))))
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_title(title, weight='bold', pad=20)
        if caption:
            ax.text(0.5, -0.12, caption, transform=ax.transAxes, ha='center', fontsize=10, style='italic')

    elif chart_type == 'line':
        if series:
            for s in series:
                ax.plot(labels, s.get('values', []), marker='o', label=s.get('label', ''))
            ax.legend()
        else:
            ax.plot(labels, values, marker='o', linestyle='-')
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.set_title(title, weight='bold', pad=20)
        if caption:
            ax.text(0.5, -0.12, caption, transform=ax.transAxes, ha='center', fontsize=10, style='italic')
    else:
        raise ValueError(f"Unknown chart type: {chart_type}")

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.2, dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return buf