# sources_fetcher.py
import requests
import logging
import hashlib
import json
import sqlite3
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import config

logger = logging.getLogger(__name__)
CACHE_DB = config.DATA_DIR / "sources_cache.db"
CACHE_TTL_DAYS = 7

def _init_cache():
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources_cache (
            topic_hash TEXT PRIMARY KEY,
            sources TEXT,
            fetched_at TEXT
        )
    """)
    conn.commit()
    conn.close()

_init_cache()

def _get_cache(topic: str) -> Optional[List[Dict]]:
    h = hashlib.sha256(topic.encode('utf-8')).hexdigest()
    conn = sqlite3.connect(str(CACHE_DB))
    row = conn.execute("SELECT sources, fetched_at FROM sources_cache WHERE topic_hash=?", (h,)).fetchone()
    conn.close()
    if row:
        fetched_at = datetime.fromisoformat(row[1])
        if datetime.now() - fetched_at < timedelta(days=CACHE_TTL_DAYS):
            return json.loads(row[0])
        # Если устарело, удаляем запись
        conn = sqlite3.connect(str(CACHE_DB))
        conn.execute("DELETE FROM sources_cache WHERE topic_hash=?", (h,))
        conn.commit()
        conn.close()
    return None

def _set_cache(topic: str, sources: List[Dict]):
    h = hashlib.sha256(topic.encode('utf-8')).hexdigest()
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute(
        "INSERT OR REPLACE INTO sources_cache (topic_hash, sources, fetched_at) VALUES (?,?,?)",
        (h, json.dumps(sources, ensure_ascii=False), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def fetch_sources(topic: str, count: int = 15, max_retries: int = 2) -> List[Dict]:
    cached = _get_cache(topic)
    if cached:
        logger.info(f"Sources: возвращено {len(cached)} источников из кеша")
        return cached[:count]

    sources = []
    try:
        crossref_results = _fetch_crossref(topic, count * 2)
        sources.extend(crossref_results)
        logger.info(f"CrossRef: найдено {len(crossref_results)} записей")
    except Exception as e:
        logger.warning(f"CrossRef error: {e}", exc_info=True)

    if len(sources) < count:
        try:
            oa_results = _fetch_openalex(topic, count * 2)
            sources.extend(oa_results)
            logger.info(f"OpenAlex: найдено {len(oa_results)} записей")
        except Exception as e:
            logger.warning(f"OpenAlex error: {e}", exc_info=True)

    seen = set()
    unique = []
    for s in sources:
        key = s.get('doi') or s.get('title', '')[:50]
        if key and key not in seen:
            seen.add(key)
            unique.append(s)
    unique = unique[:count]
    if unique:
        _set_cache(topic, unique)
    return unique

def _fetch_crossref(topic: str, limit: int) -> List[Dict]:
    url = "https://api.crossref.org/works"
    params = {"query": topic, "rows": limit, "sort": "relevance", "select": "title,author,container-title,issued,DOI,type"}
    resp = requests.get(url, params=params, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    items = data.get('message', {}).get('items', [])
    results = []
    for item in items:
        title = item.get('title', [''])[0] if item.get('title') else ''
        if not title:
            continue
        author_list = item.get('author', [])
        author = ", ".join([f"{a.get('family', '')} {a.get('given', '')}".strip() for a in author_list[:3]])
        if not author:
            author = "Unknown"
        journal = item.get('container-title', [''])[0] if item.get('container-title') else ''
        issued = item.get('issued', {}).get('date-parts', [[0]])[0]
        year = issued[0] if issued else 0
        doi = item.get('DOI', '')
        url_link = f"https://doi.org/{doi}" if doi else ''
        pub_type = item.get('type', 'journal-article')
        results.append({
            'author': author,
            'title': title,
            'journal': journal,
            'year': year,
            'doi': doi,
            'url': url_link,
            'type': pub_type
        })
    return results

def _fetch_openalex(topic: str, limit: int) -> List[Dict]:
    url = "https://api.openalex.org/works"
    params = {"search": topic, "per-page": limit, "sort": "relevance_score"}
    resp = requests.get(url, params=params, timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    items = data.get('results', [])
    results = []
    for item in items:
        title = item.get('title', '')
        if not title:
            continue
        authorships = item.get('authorships', [])
        authors = []
        for a in authorships[:3]:
            author_obj = a.get('author', {})
            display_name = author_obj.get('display_name', '')
            if display_name:
                authors.append(display_name)
        author = ", ".join(authors) if authors else "Unknown"
        journal = item.get('primary_location', {}).get('source', {}).get('display_name', '')
        year = item.get('publication_year', 0)
        doi = item.get('doi', '').replace('https://doi.org/', '')
        url_link = item.get('doi', '')
        pub_type = item.get('type', 'journal-article')
        results.append({
            'author': author,
            'title': title,
            'journal': journal,
            'year': year,
            'doi': doi,
            'url': url_link,
            'type': pub_type
        })
    return results

def format_bibliography(sources: List[Dict], standard: str = "gost_7.32-2017") -> str:
    lines = []
    for s in sources:
        author = s['author']
        if not author or author.strip() in ('', 'Unknown', 'Б.и.', 'Б.м.'):
            author = "Б.м."
        title = s['title']
        journal = s['journal'] if s['journal'] else "Б.и."
        year = s['year'] if s['year'] else "б.г."
        doi = s['doi']

        if standard.startswith("gost"):
            line = f"{author}. {title} // {journal}. — {year}."
            if doi:
                line += f" — DOI: {doi}."
        else:
            line = f"{author}. {title}. {journal}, {year}."
        lines.append(line)
    return "\n".join(lines)