# data_collector.py
import requests
import feedparser
import logging
import time
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import config

logger = logging.getLogger(__name__)

# Список RSS-лент для резервирования (если одна упадёт, попробуем следующую)
RSS_FEEDS = [
    "https://news.yandex.ru/index.rss",
    "https://lenta.ru/rss",
    "https://ria.ru/export/rss2/archive/index.xml",
    "https://www.interfax.ru/rss.asp",
]


class DataCollector:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        self.timeout = config.DATA_COLLECTOR_TIMEOUT
        # Отключаем проверку SSL для проблемных хостов (опционально, но может быть небезопасно)
        # self.session.verify = False

    def search(self, query: str, num: int = 5):
        try:
            with DDGS() as ddgs:
                results = []
                for r in ddgs.text(query, max_results=num):
                    results.append({
                        "title": r.get("title"),
                        "link": r.get("href"),
                        "snippet": r.get("body")
                    })
                return results
        except Exception as e:
            logger.error(f"DuckDuckGo search error: {e}", exc_info=True)
            return []

    def scrape_page(self, url: str) -> str:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text(separator="\n")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines)[:5000]
        except requests.exceptions.Timeout:
            logger.warning(f"Таймаут при загрузке {url}")
            return ""
        except Exception as e:
            logger.error(f"Scrape error for {url}: {e}", exc_info=True)
            return ""

    def get_rss_news(self, feed_url: str, limit: int = 5):
        """Пытается получить новости из RSS, при ошибке возвращает пустой список."""
        try:
            # Увеличиваем таймаут и добавляем повторные попытки
            for attempt in range(2):
                try:
                    resp = self.session.get(feed_url, timeout=self.timeout)
                    resp.raise_for_status()
                    feed = feedparser.parse(resp.text)
                    entries = []
                    for entry in feed.entries[:limit]:
                        entries.append({
                            "title": entry.get("title"),
                            "link": entry.get("link"),
                            "summary": entry.get("summary", "")[:200]
                        })
                    return entries
                except requests.exceptions.SSLError as e:
                    logger.warning(f"SSL ошибка при запросе {feed_url}, попытка {attempt+1}: {e}")
                    time.sleep(1)  # небольшая пауза перед повторной попыткой
                except Exception as e:
                    logger.warning(f"Ошибка RSS для {feed_url}: {e}")
                    break  # другие ошибки не повторяем
            return []
        except Exception as e:
            logger.error(f"RSS error for {feed_url}: {e}", exc_info=True)
            return []

    def collect(self, query: str, max_pages: int = 2):
        context = {
            "query": query,
            "search_results": [],
            "pages_text": [],
            "rss_news": []
        }
        # Поиск
        search_res = self.search(query, num=max_pages)
        context["search_results"] = search_res

        # Скрапинг страниц
        for res in search_res[:max_pages]:
            link = res.get("link")
            if link:
                text = self.scrape_page(link)
                if text:
                    context["pages_text"].append({"url": link, "text": text[:3000]})

        # RSS – пробуем по очереди несколько лент, пока одна не даст результат
        for feed in RSS_FEEDS:
            news = self.get_rss_news(feed, limit=3)
            if news:
                context["rss_news"] = news
                logger.info(f"RSS данные получены из {feed}")
                break
        else:
            logger.warning("Не удалось получить RSS-новости ни из одного источника")

        return context