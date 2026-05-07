# -*- coding: utf-8 -*-
"""
Mirror the latest per-market EDA reports as self-contained HTML files in
data/eda_latest/.  Each market becomes one file (e.g. us.html) with all
plot images inlined as base64 — single-click open, no folder navigation.

Called from the bottom of generate_market_report.py and validate_all_markets.py.
Can also be run standalone:  py scripts/publish_latest_eda.py
"""
import base64
import os
import re
import shutil
import sys


SRC_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda')
DST_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'eda_latest')


def _inline_images(html_path, plots_root):
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    def repl(m):
        path = m.group(1)
        full = path if os.path.isabs(path) else os.path.join(plots_root, path)
        if not os.path.exists(full):
            return m.group(0)
        with open(full, 'rb') as fp:
            b64 = base64.b64encode(fp.read()).decode('ascii')
        ext = os.path.splitext(full)[1].lstrip('.').lower() or 'png'
        return f'src="data:image/{ext};base64,{b64}"'

    return re.sub(
        r'src="([^"]+\.(?:png|jpg|jpeg|gif|svg))"',
        repl, html, flags=re.IGNORECASE)


def publish():
    if not os.path.isdir(SRC_DIR):
        print(f'  publish_latest_eda: source dir not found: {SRC_DIR}')
        return
    os.makedirs(DST_DIR, exist_ok=True)
    # Wipe stale files (keep the dir itself)
    for old in os.listdir(DST_DIR):
        path = os.path.join(DST_DIR, old)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    written = 0
    for market in sorted(os.listdir(SRC_DIR)):
        src_dir = os.path.join(SRC_DIR, market)
        rpt = os.path.join(src_dir, 'report.html')
        if not os.path.isdir(src_dir) or not os.path.exists(rpt):
            continue
        out = os.path.join(DST_DIR, f'{market}.html')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(_inline_images(rpt, src_dir))
        written += 1

    # Cross-market index
    idx = os.path.join(SRC_DIR, 'index.html')
    if os.path.exists(idx):
        out = os.path.join(DST_DIR, '_index.html')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(_inline_images(idx, SRC_DIR))
        written += 1

    print(f'  Published {written} self-contained HTMLs to {DST_DIR}')


if __name__ == '__main__':
    publish()
