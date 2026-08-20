# mindmap.py
import io
import re
import logging
import tempfile
import subprocess
from pathlib import Path
import config

logger = logging.getLogger(__name__)


class MindMapGenerator:
    def __init__(self):
        self._check_dot()

    def _check_dot(self):
        try:
            subprocess.run(["dot", "-V"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.warning("Graphviz (dot) не найден. Mind map недоступны.")

    def generate(self, text: str, title: str = "Конспект") -> bytes | None:
        try:
            dot = self._build_dot(text, title)
            return self._render(dot)
        except Exception as e:
            logger.error(f"MindMap: {e}", exc_info=True)
            return None

    def _build_dot(self, text: str, title: str) -> str:
        lines = []
        lines.append('digraph MindMap {')
        lines.append('    rankdir=LR;')
        lines.append('    bgcolor="#fafafa";')
        lines.append('    node [shape=box, style="rounded,filled", fontname="DejaVuSans", fontsize=12, color="#2c3e50", fillcolor="#ecf0f1"];')
        lines.append('    edge [color="#7f8c8d", arrowhead=vee];')
        lines.append(f'    root [label="{self._esc(title)}", fillcolor="#3498db", fontcolor=white, fontsize=14, style="rounded,filled,bold"];')

        headings = self._extract_structure(text)
        if not headings:
            headings = [("Основное", text[:200])]

        for i, (head, body) in enumerate(headings, 1):
            nid = f"n{i}"
            lines.append(f'    {nid} [label="{self._esc(head)}", fillcolor="#e74c3c", fontcolor=white];')
            lines.append(f'    root -> {nid};')
            sub_lines = [l.strip() for l in body.split('\n') if l.strip()][:5]
            for j, sub in enumerate(sub_lines, 1):
                sid = f"n{i}s{j}"
                sub_text = sub[:60] + "..." if len(sub) > 60 else sub
                lines.append(f'    {sid} [label="{self._esc(sub_text)}", fillcolor="#2ecc71", fontcolor=white, fontsize=10];')
                lines.append(f'    {nid} -> {sid};')

        lines.append('}')
        return "\n".join(lines)

    def _extract_structure(self, text: str) -> list:
        pattern = r'(?:^|\n)(?:#{1,3}\s*|\d+\.\s+|\*\*\s*)([^\n]+?)(?:\*\*)?\s*\n(.*?)(?=(?:\n(?:#{1,3}\s*|\d+\.\s+|\*\*\s*)|\Z))'
        matches = re.findall(pattern, text, re.DOTALL)
        result = []
        for h, b in matches:
            h = h.strip().strip('*# ')
            b = b.strip()
            if len(h) > 3 and len(b) > 10:
                result.append((h, b))
        if not result:
            parts = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 20]
            for i, p in enumerate(parts[:6], 1):
                first_line = p.split('\n')[0][:50]
                result.append((first_line, p))
        return result[:8]

    def _render(self, dot_src: str) -> bytes:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.dot', delete=False, encoding='utf-8') as f:
            f.write(dot_src)
            dot_path = f.name

        try:
            png_path = dot_path.replace('.dot', '.png')
            result = subprocess.run(
                ['dot', '-Tpng', dot_path, '-o', png_path],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                raise RuntimeError(f"dot error: {result.stderr}")
            with open(png_path, 'rb') as f:
                return f.read()
        finally:
            Path(dot_path).unlink(missing_ok=True)
            Path(png_path).unlink(missing_ok=True)

    @staticmethod
    def _esc(s: str) -> str:
        return s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').strip()