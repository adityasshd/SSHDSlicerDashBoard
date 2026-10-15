"""Publish app-owned assets through Vercel's CDN instead of Python invocations."""
from pathlib import Path
import shutil


def build():
    root = Path(__file__).resolve().parent
    shutil.copytree(root / 'src/slicing_dashboard/assets', root / 'public/assets', dirs_exist_ok=True)


if __name__ == '__main__':
    build()
