# utils/file_utils.py
import os
import tempfile
import shutil
from pathlib import Path
from contextlib import contextmanager
import config
import logging
import time

logger = logging.getLogger(__name__)

@contextmanager
def safe_temp_file(suffix: str = "", prefix: str = "tmp", delete: bool = True):
    tmp = None
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, prefix=prefix, delete=False, dir=config.TEMP_DIR)
        tmp_path = tmp.name
        tmp.close()
        yield tmp_path
    finally:
        if delete and tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as e:
                logger.warning(f"Не удалось удалить {tmp_path}: {e}")

@contextmanager
def safe_temp_dir(prefix: str = "tmpdir"):
    tmpdir = tempfile.mkdtemp(prefix=prefix, dir=config.TEMP_DIR)
    try:
        yield tmpdir
    finally:
        if os.path.exists(tmpdir):
            try:
                shutil.rmtree(tmpdir)
            except OSError as e:
                logger.warning(f"Не удалось удалить папку {tmpdir}: {e}")

def cleanup_old_temp_files(max_age_seconds: int = 86400):
    now = time.time()
    count = 0
    for item in config.TEMP_DIR.iterdir():
        try:
            if item.is_file() and (now - item.stat().st_mtime) > max_age_seconds:
                item.unlink()
                count += 1
            elif item.is_dir() and (now - item.stat().st_mtime) > max_age_seconds:
                shutil.rmtree(item)
                count += 1
        except Exception:
            pass
    if count:
        logger.info(f"Очистка временных файлов: удалено {count} объектов")