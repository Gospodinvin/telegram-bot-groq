#!/usr/bin/env python3
# check_env.py — проверка окружения
import os
import sys
import shutil
from pathlib import Path
import subprocess
from dotenv import load_dotenv

load_dotenv()


def check_fonts():
    fonts_dir = Path("fonts")
    fonts_dir.mkdir(exist_ok=True)
    required = ["LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf"]
    missing = [f for f in required if not (fonts_dir / f).exists()]
    if missing:
        print(f"⚠️ Отсутствуют шрифты: {', '.join(missing)}")
        print("   Скачайте с https://github.com/liberationfonts/liberation-fonts")
        return False
    print("✅ Все шрифты найдены")
    return True


def check_ffmpeg():
    if shutil.which("ffmpeg"):
        print("✅ ffmpeg найден")
        return True
    print("⚠️ ffmpeg не найден (нужен для видео)")
    return False


def check_graphviz():
    try:
        subprocess.run(["dot", "-V"], capture_output=True, check=True)
        print("✅ Graphviz найден")
        return True
    except:
        print("⚠️ Graphviz не найден (нужен для ментальных карт)")
        return False


def check_packages():
    required = [
        "telegram", "python-dotenv", "ollama", "faster-whisper",
        "reportlab", "docx", "python-pptx", "genanki", "PIL",
        "matplotlib", "beautifulsoup4", "duckduckgo-search", "feedparser"
    ]
    missing = []
    for pkg in required:
        try:
            __import__(pkg.replace("-", "_").replace("python-", ""))
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"❌ Отсутствуют пакеты: {', '.join(missing)}")
        print(f"   Установите: pip install {' '.join(missing)}")
        return False
    print("✅ Все пакеты установлены")
    return True


def check_env():
    required_vars = ["TELEGRAM_TOKEN", "ADMIN_ID"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"⚠️ Отсутствуют переменные в .env: {', '.join(missing)}")
        return False
    print("✅ .env корректен")
    return True


def main():
    print("=" * 60)
    print("   LectureX Bot — проверка окружения")
    print("=" * 60)
    checks = [
        ("Переменные окружения", check_env),
        ("Шрифты", check_fonts),
        ("ffmpeg", check_ffmpeg),
        ("Graphviz", check_graphviz),
        ("Python-пакеты", check_packages),
    ]
    ok = True
    for name, func in checks:
        print(f"\n📌 {name}:")
        if not func():
            ok = False
    print("\n" + "=" * 60)
    if ok:
        print("✅ Всё готово! Запускайте: python bot.py")
    else:
        print("⚠️ Есть предупреждения. Некоторые функции могут не работать.")
    print("=" * 60)


if __name__ == "__main__":
    main()