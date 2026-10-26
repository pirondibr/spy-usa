# -*- coding: utf-8 -*-
"""Etapa Instagram + YouTube (sem TikTok) do chatbot Radar."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FINAL_DIR = Path(__file__).resolve().parent
CORE = FINAL_DIR / "5 - metricas concorrentes.py"


def main() -> None:
    if len(sys.argv) < 2:
        print('Uso: python "5f - social ig yt.py" <cliente>')
        sys.exit(1)
    client = sys.argv[1].strip()
    mode = sys.argv[2].strip().lower() if len(sys.argv) >= 3 else "social"
    cmd = [sys.executable, str(CORE), client, mode]
    raise SystemExit(subprocess.call(cmd, cwd=str(FINAL_DIR)))


if __name__ == "__main__":
    main()
