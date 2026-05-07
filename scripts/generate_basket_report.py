# -*- coding: utf-8 -*-
"""
Per-basket report. For each portfolio in data/input/portfolios/baskets/
computes:
  1) Cumulative return over the factor-model window (constant-weights backtest)
  2) Factor loadings (style z-scores + top industry weights)
  3) Risk decomposition: factor vs idio, top factor contributors

Outputs a single HTML file with a summary table + per-basket sections.

Usage: py scripts/generate_basket_report.py [--out PATH]
"""

import argparse
import base64
import io
import os
import sqlite3
from datetime import datetime
from html import escape

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, 'data', 'model')
DB_PATH = os.path.join(ROOT, 'data', 'db', 'market_data.db')
BASKETS_DIR = os.path.join(ROOT, 'data', 'input', 'portfolios', 'Baskets', 'analyst_weighted')
DEFAULT_OUT = os.path.join(ROOT, 'data', 'eda', 'basket_report.html')

STYLE_COLS = ['size', 'beta', 'momentum', 'residvol', 'nlsize',
              'btop', 'liquidity', 'earnyild', 'growth', 'leverage']


def fig_to_b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def load_basket(path):
    df = pd.read_csv(path, sep=';')
    df['shares'] = pd.to_numeric(df['shares'], errors='coerce')
    df = df.dropna(subset=['shares', 'ticker'])
    return df


def get_latest_prices(conn, tickers):
    out = {}
    for t in tickers:
        row = conn.execute(
            "SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
            (t,)).fetchone()
        out[t] = row[0] if row else np.nan
    return out


def compute_weights(basket_df, prices):
    rows = []
    for _, r in basket_df.iterrows():
        p = prices.get(r['ticker'], np.nan)
        if pd.notna(p) and p > 0:
            rows.append({'ticker': r['ticker'], 'shares': r['shares'],
                         'price': p, 'mv': p * r['shares']})
    w_df = pd.DataFrame(rows)
    if len(w_df) == 0:
        return w_df
    w_df['weight'] = w_df['mv'] / w_df['mv'].sum()
    return w_df


def build_returns_panel(factor_exp_df):
    """Wide ticker-by-date returns matrix from the factor exposures file."""
    pivot = factor_exp_df.pivot_table(index='date', columns='ticker',
                                      values='return', aggfunc='first')
    pivot.index = pd.to_datetime(pivot.index)
    return pivot.sort_index()


def precompute_idio_vols(factor_exp_df, factor_ret_df):
    """One residual std per ticker, annualized. Returns dict ticker -> idio_vol."""
    out = {}
    factor_ret_df = factor_ret_df.copy()
    factor_ret_df.index = pd.to_datetime(factor_ret_df.index)
    fr_dates = set(factor_ret_df.index)

    for t, g in factor_exp_df.groupby('ticker'):
        g = g.sort_values('date').copy()
        g['date'] = pd.to_datetime(g['date'])
        if len(g) < 60:
            continue
        residuals = []
        for _, row in g.iterrows():
            d = row['date']
            if d not in fr_dates:
                continue
            fr = factor_ret_df.loc[d]
            pred = fr.get('Country', 0)
            sec = row.get('sector', '')
            if isinstance(sec, str) and sec in fr.index:
                pred += fr[sec]
            for sf in STYLE_COLS:
                if sf in row.index and sf in fr.index:
                    val = row[sf]
                    if pd.notna(val):
                        pred += val * fr[sf]
            r = row['return']
            if pd.notna(r):
                residuals.append(r - pred)
        if len(residuals) > 30:
            out[t] = float(np.std(residuals) * np.sqrt(252))
    return out


def analyze(name, basket_df, weights_df, factor_exp_df, factor_ret_df,
            factor_cov_df, returns_panel, idio_vols, start_date):
    res = {'name': name,
           'n_in': len(basket_df),
           'n_priced': len(weights_df),
           'total_mv': weights_df['mv'].sum() if len(weights_df) else 0,
           'cost_date': basket_df.iloc[0].get('costdate') if len(basket_df) else None}

    if len(weights_df) == 0:
        res['error'] = 'no priced positions'
        return res

    latest_date = factor_exp_df['date'].max()
    latest = factor_exp_df[factor_exp_df['date'] == latest_date].set_index('ticker')

    matched = [t for t in weights_df['ticker'] if t in latest.index]
    res['n_matched'] = len(matched)
    res['unmatched'] = [t for t in weights_df['ticker'] if t not in latest.index]

    if not matched:
        res['error'] = 'no factor data for any position'
        return res

    w_full = dict(zip(weights_df['ticker'], weights_df['weight']))
    w = np.array([w_full[t] for t in matched])
    w = w / w.sum()  # renormalize over matched

    # Style exposures
    style_exp = {f: float(np.sum(w * latest.loc[matched, f].fillna(0).values))
                 for f in STYLE_COLS if f in latest.columns}
    res['style_exposures'] = style_exp

    # Industry exposures (using sector column)
    factor_names = factor_cov_df.columns.tolist()
    industry_factors = [f for f in factor_names if f not in ['Country'] + STYLE_COLS]
    industry_exp = {}
    secs = latest.loc[matched, 'sector'].fillna('').values
    for ind in industry_factors:
        mask = (secs == ind)
        if mask.any():
            industry_exp[ind] = float(w[mask].sum())
    res['industry_exposures'] = industry_exp

    # b vector aligned with covariance
    b = np.zeros(len(factor_names))
    for i, f in enumerate(factor_names):
        if f == 'Country':
            b[i] = 1.0
        elif f in style_exp:
            b[i] = style_exp[f]
        elif f in industry_exp:
            b[i] = industry_exp[f]
    omega = factor_cov_df.values
    factor_var_ann = float(b @ omega @ b) * 252
    res['factor_var_ann'] = factor_var_ann
    res['factor_vol_ann'] = np.sqrt(max(factor_var_ann, 0))
    per_factor_var = b * (omega @ b) * 252
    res['per_factor_var'] = dict(zip(factor_names, per_factor_var))

    # Idio
    idio_var = sum(w[i]**2 * idio_vols.get(t, 0.30)**2 for i, t in enumerate(matched))
    res['idio_var'] = idio_var
    res['idio_vol'] = np.sqrt(idio_var)

    total_var = factor_var_ann + idio_var
    res['total_var'] = total_var
    res['total_vol'] = np.sqrt(total_var)
    res['pct_factor'] = 100 * factor_var_ann / total_var if total_var > 0 else 0
    res['pct_idio'] = 100 * idio_var / total_var if total_var > 0 else 0

    # Full daily-return series for trailing-return calcs and z-scores
    cost_date = pd.to_datetime(basket_df['costdate'].min())
    rets_full = returns_panel.reindex(columns=matched).fillna(0)
    port_ret_full = (rets_full * w).sum(axis=1)

    # Cumulative return: from uniform start_date forward
    start = pd.Timestamp(start_date)
    in_window = port_ret_full[port_ret_full.index >= start]
    cum = (1 + in_window).cumprod()
    res['cost_date'] = cost_date.strftime('%Y-%m-%d')
    res['cum_returns'] = cum
    res['start_date'] = start.strftime('%Y-%m-%d')
    res['n_days'] = len(cum)
    if len(cum) > 0:
        final = float(cum.iloc[-1])
        res['total_return_pct'] = (final - 1) * 100
        res['ann_return_pct'] = (final**(252/len(cum)) - 1) * 100
    else:
        res['total_return_pct'] = 0
        res['ann_return_pct'] = 0

    # Daily returns full history; expose for cross-basket correlation
    res['daily_returns'] = port_ret_full

    # Trailing-period returns
    for window_days, key in [(1,'ret_1d'),(5,'ret_5d'),(21,'ret_21d'),
                              (63,'ret_63d'),(126,'ret_126d'),(252,'ret_252d')]:
        if len(port_ret_full) >= window_days:
            r = float((1 + port_ret_full.tail(window_days)).prod() - 1) * 100
            res[key] = r
    # Backwards-compat
    res['ret_1m'] = res.get('ret_21d')

    # Z-score of latest 5-day return vs trailing daily-return distribution
    last_5d_ret = float((1 + port_ret_full.tail(5)).prod() - 1) if len(port_ret_full) >= 5 else None
    for window in (63, 126, 252, 504):
        if last_5d_ret is None:
            continue
        hist = port_ret_full.iloc[-(window + 5):-5]
        if len(hist) >= max(20, window // 2) and hist.std() > 0:
            mu_5d = hist.mean() * 5
            sigma_5d = hist.std() * (5 ** 0.5)
            res[f'z_5d_{window}d'] = float((last_5d_ret - mu_5d) / sigma_5d)

    # Risk / risk-adjusted return stats over the full available history
    daily = port_ret_full.dropna()
    if len(daily) > 30:
        ann_ret = float((1 + daily).prod() ** (252 / len(daily)) - 1) * 100
        ann_vol = float(daily.std() * (252 ** 0.5)) * 100
        neg_only = daily[daily < 0]
        downside_dev = float(neg_only.std() * (252 ** 0.5)) * 100 if len(neg_only) > 5 else None
        pos_sum = float(daily[daily > 0].sum())
        neg_sum = float(-daily[daily < 0].sum())
        res['ann_vol_pct'] = ann_vol
        res['sharpe'] = ann_ret / ann_vol if ann_vol > 0 else None
        res['downside_dev_pct'] = downside_dev
        res['sortino'] = ann_ret / downside_dev if downside_dev else None
        res['profit_factor'] = pos_sum / neg_sum if neg_sum > 0 else None

    return res


def section_html(res):
    if res.get('error'):
        return (f"<section><h3>{escape(res['name'])}</h3>"
                f"<p style='color:#a33'>Skipped: {escape(res['error'])} "
                f"({res['n_in']} positions, {res['n_priced']} priced)</p></section>")

    # Plot 1: cumulative return from uniform start_date
    fig1, ax1 = plt.subplots(figsize=(10, 3))
    ax1.plot(res['cum_returns'].index, (res['cum_returns'] - 1) * 100, lw=1.5)
    ax1.axhline(0, color='k', lw=0.5)
    ax1.set_ylabel('Cumulative return %')
    ax1.set_title(f"Constant-weight backtest from {res['start_date']} ({res['n_days']} trading days). "
                  f"Basket formed {res['cost_date']}.")
    ax1.grid(alpha=0.3)
    cum_b64 = fig_to_b64(fig1)

    # Plot 2: style exposures
    fig2, ax2 = plt.subplots(figsize=(8, 3))
    se = res['style_exposures']
    keys = list(se.keys())
    vals = [se[k] for k in keys]
    colors = ['#2d8a2d' if v > 0 else '#cc3333' for v in vals]
    ax2.bar(keys, vals, color=colors)
    ax2.axhline(0, color='k', lw=0.5)
    ax2.set_ylabel('z-score tilt')
    ax2.set_title('Style factor exposures')
    plt.setp(ax2.get_xticklabels(), rotation=30, ha='right')
    style_b64 = fig_to_b64(fig2)

    # Plot 3: top factor risk contributors
    pfv = res['per_factor_var']
    sorted_pfv = sorted(pfv.items(), key=lambda kv: abs(kv[1]), reverse=True)[:10]
    fig3, ax3 = plt.subplots(figsize=(8, 3.5))
    fnames = [k[:30] for k, _ in sorted_pfv]
    pcts = [v / res['total_var'] * 100 if res['total_var'] > 0 else 0
            for _, v in sorted_pfv]
    colors3 = ['#2d8a2d' if v > 0 else '#cc3333' for v in pcts]
    ax3.barh(range(len(fnames)), pcts, color=colors3)
    ax3.set_yticks(range(len(fnames)))
    ax3.set_yticklabels(fnames, fontsize=8)
    ax3.invert_yaxis()
    ax3.axvline(0, color='k', lw=0.5)
    ax3.set_xlabel('% of total variance')
    ax3.set_title('Top 10 factor risk contributors')
    contrib_b64 = fig_to_b64(fig3)

    # Industry exposures (top 5)
    ind_top = sorted(res['industry_exposures'].items(),
                     key=lambda kv: kv[1], reverse=True)[:5]
    ind_html = '<br>'.join(f"{escape(k)}: {v*100:.1f}%" for k, v in ind_top if v > 0)

    return f"""
<section id="{escape(res['name'])}">
  <h3>{escape(res['name'])}</h3>
  <div class="stats">
    <span><b>Positions:</b> {res['n_priced']} priced ({res['n_matched']} in factor model)</span>
    <span><b>Cost date:</b> {res['cost_date']}</span>
    <span><b>Window:</b> {res['start_date']} to latest ({res['n_days']}d)</span>
    <span><b>Cumulative return:</b> {res['total_return_pct']:+.1f}%</span>
    <span><b>Annualized:</b> {res['ann_return_pct']:+.1f}%</span>
    <span><b>Total vol:</b> {res['total_vol']*100:.1f}%</span>
    <span><b>Factor / idio:</b> {res['pct_factor']:.0f}% / {res['pct_idio']:.0f}%</span>
  </div>
  <p><b>Top sector weights:</b><br>{ind_html or '—'}</p>
  <img src="data:image/png;base64,{cum_b64}" />
  <div class="row">
    <img src="data:image/png;base64,{style_b64}" class="half" />
    <img src="data:image/png;base64,{contrib_b64}" class="half" />
  </div>
</section>
"""


def summary_table(all_res):
    def fmt(v, suffix='%', signed=True):
        if v is None:
            return '–'
        return (f"{v:+.2f}{suffix}" if signed else f"{v:.2f}{suffix}")

    rows = []
    for r in all_res:
        if r.get('error'):
            rows.append(f"<tr><td><a href='#{escape(r['name'])}'>{escape(r['name'])}</a></td>"
                        f"<td colspan='12' style='color:#a33'>{escape(r['error'])}</td></tr>")
            continue
        rows.append(
            f"<tr>"
            f"<td><a href='#{escape(r['name'])}'>{escape(r['name'])}</a></td>"
            f"<td>{r['n_priced']}/{r['n_in']}</td>"
            f"<td>{r['total_return_pct']:+.1f}%</td>"
            f"<td>{r['ann_return_pct']:+.1f}%</td>"
            f"<td>{r['total_vol']*100:.1f}%</td>"
            f"<td>{r['pct_factor']:.0f}%</td>"
            f"<td>{r['pct_idio']:.0f}%</td>"
            f"<td>{fmt(r.get('ret_1d'))}</td>"
            f"<td>{fmt(r.get('ret_5d'))}</td>"
            f"<td>{fmt(r.get('ret_1m'))}</td>"
            f"<td>{fmt(r.get('z_5d_63d'), '', True)}</td>"
            f"<td>{fmt(r.get('z_5d_126d'), '', True)}</td>"
            f"<td>{fmt(r.get('z_5d_252d'), '', True)}</td>"
            f"</tr>")
    return ("<table><thead><tr>"
            "<th>Basket</th><th>Priced/In</th><th>Cum return (since start)</th><th>Annualized</th>"
            "<th>Total vol</th><th>Factor %</th><th>Idio %</th>"
            "<th>1D</th><th>5D</th><th>1M</th>"
            "<th>z₅ᴅ vs 63d</th><th>z₅ᴅ vs 126d</th><th>z₅ᴅ vs 252d</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>")


def _ok_results(all_res):
    return [r for r in all_res if not r.get('error') and 'cum_returns' in r]


def build_quadrant_chart(all_res):
    """Visual 7: 5D vs 21D return scatter — Leaders / Fading / Recovering / Laggards."""
    rows = [(r['name'], r.get('ret_5d', 0), r.get('ret_21d', 0)) for r in _ok_results(all_res)
            if 'ret_5d' in r and 'ret_21d' in r]
    if not rows:
        return ''
    fig, ax = plt.subplots(figsize=(11, 6))
    leaders = fading = recovering = laggards = 0
    for name, x, y in rows:
        if x >= 0 and y >= 0:
            color = '#2d8a2d'; leaders += 1
        elif x < 0 and y >= 0:
            color = '#cc8a2d'; fading += 1
        elif x >= 0 and y < 0:
            color = '#2d8acc'; recovering += 1
        else:
            color = '#cc3333'; laggards += 1
        ax.scatter(x, y, s=80, c=color, alpha=0.75, edgecolor='white', linewidth=0.5)
        ax.annotate(name[:18], (x, y), fontsize=6.5, alpha=0.85, xytext=(5, 3), textcoords='offset points')
    ax.axhline(0, color='gray', lw=0.8); ax.axvline(0, color='gray', lw=0.8)
    ax.set_xlabel('5D return %'); ax.set_ylabel('21D return %')
    ax.set_title(f'Factor Rotation Quadrant — Leaders {leaders} / Fading {fading} / Recovering {recovering} / Laggards {laggards}')
    ax.grid(alpha=0.3)
    return f'<img src="data:image/png;base64,{fig_to_b64(fig)}" />'


def build_leaderboard(all_res, metric='ret_5d', label='5D return'):
    """Visual 2: Top 10 / Bottom 10 baskets ranked by `metric`."""
    rows = [(r['name'], r.get(metric)) for r in _ok_results(all_res) if r.get(metric) is not None]
    if not rows:
        return ''
    rows.sort(key=lambda kv: kv[1], reverse=True)
    top = rows[:10]
    bot = rows[-10:][::-1]
    def render(rows, color):
        items = ''.join(f'<tr><td>{i+1}</td><td>{escape(n)}</td>'
                        f'<td style="color:{color};text-align:right;font-weight:600">{v:+.2f}%</td></tr>'
                        for i, (n, v) in enumerate(rows))
        return f'<table style="font-size:0.85em">{items}</table>'
    return (f'<div class="row"><div class="half"><h4>Top 10 — {label}</h4>{render(top, "#2d8a2d")}</div>'
            f'<div class="half"><h4>Bottom 10 — {label}</h4>{render(bot, "#cc3333")}</div></div>')


def build_zscore_visual(all_res):
    """Visual 3: top/bottom z-scores at multiple windows. Static — one panel per window."""
    windows = [63, 126, 252, 504]
    panels = []
    for w in windows:
        rows = [(r['name'], r.get(f'z_5d_{w}d')) for r in _ok_results(all_res) if r.get(f'z_5d_{w}d') is not None]
        if not rows:
            continue
        rows.sort(key=lambda kv: kv[1], reverse=True)
        top = rows[:10]; bot = rows[-10:][::-1]
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        axes[0].barh([x[0][:22] for x in top][::-1], [x[1] for x in top][::-1], color='#2d8a2d')
        axes[0].set_title(f'Top 10 z-scores ({w}d)'); axes[0].axvline(0, color='k', lw=0.5)
        axes[0].set_xlabel('z-score'); axes[0].grid(alpha=0.3, axis='x')
        axes[1].barh([x[0][:22] for x in bot][::-1], [x[1] for x in bot][::-1], color='#cc3333')
        axes[1].set_title(f'Bottom 10 z-scores ({w}d)'); axes[1].axvline(0, color='k', lw=0.5)
        axes[1].set_xlabel('z-score'); axes[1].grid(alpha=0.3, axis='x')
        plt.setp([a.get_yticklabels() for a in axes], fontsize=8)
        panels.append(f'<img src="data:image/png;base64,{fig_to_b64(fig)}" />')
    return '<p><i>Latest 5-day return as z-score vs the trailing daily-return distribution. |z| &gt; 2 = unusual.</i></p>' + ''.join(panels)


def build_cumulative_overlay_topbottom(all_res, n=5):
    """Visual 5: Cumulative return overlay — top n + bottom n by total return."""
    ok = _ok_results(all_res)
    if not ok:
        return ''
    ok = sorted(ok, key=lambda r: r.get('total_return_pct', 0), reverse=True)
    top = ok[:n]; bot = ok[-n:]
    fig, ax = plt.subplots(figsize=(11, 5))
    for r in top:
        ax.plot(r['cum_returns'].index, (r['cum_returns'] - 1) * 100, lw=1.6, label=f'↑ {r["name"]}', alpha=0.9)
    for r in bot:
        ax.plot(r['cum_returns'].index, (r['cum_returns'] - 1) * 100, lw=1.4, ls='--', label=f'↓ {r["name"]}', alpha=0.7)
    ax.axhline(0, color='k', lw=0.5); ax.grid(alpha=0.3)
    ax.set_ylabel('Cumulative return %'); ax.set_title(f'Cumulative Returns — Top {n} (solid) and Bottom {n} (dashed)')
    ax.legend(fontsize=7, ncol=2, loc='upper left')
    return f'<img src="data:image/png;base64,{fig_to_b64(fig)}" />'


def build_period_returns_table(all_res):
    """Visual 1+4: leaderboard of all baskets across periods + key stats."""
    cols = [('ret_1d','1D'),('ret_5d','5D'),('ret_21d','21D'),('ret_63d','63D'),
            ('ret_126d','126D'),('ret_252d','252D'),('ann_vol_pct','Vol%'),
            ('sharpe','Sharpe'),('sortino','Sortino'),('profit_factor','PF')]
    def fmt(v, dec=2, suf='%', signed=True):
        if v is None: return '–'
        s = f'{v:+.{dec}f}{suf}' if signed else f'{v:.{dec}f}{suf}'
        return s
    head = ''.join(f'<th>{l}</th>' for _, l in cols)
    body = []
    for r in sorted(_ok_results(all_res), key=lambda x: x.get('ret_252d') or x.get('total_return_pct', 0), reverse=True):
        cells = []
        for k, _ in cols:
            v = r.get(k)
            if k == 'ann_vol_pct':
                cells.append(f'<td>{fmt(v, 1, "%", signed=False)}</td>')
            elif k in ('sharpe', 'sortino', 'profit_factor'):
                cells.append(f'<td>{fmt(v, 2, "", signed=True)}</td>')
            else:
                cells.append(f'<td>{fmt(v, 2, "%")}</td>')
        body.append(f'<tr><td><a href="#{escape(r["name"])}">{escape(r["name"])}</a></td>{"".join(cells)}</tr>')
    return (f'<table><thead><tr><th>Basket</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def build_correlation_table(all_res, n=5):
    """Visual 6: Top / Bottom basket-pair correlations across daily-return series."""
    ok = [r for r in _ok_results(all_res) if 'daily_returns' in r and len(r['daily_returns']) > 60]
    if len(ok) < 4:
        return ''
    df = pd.DataFrame({r['name']: r['daily_returns'] for r in ok}).dropna(how='all')
    corr = df.corr().fillna(0)
    pairs = []
    names = corr.columns.tolist()
    for i, a in enumerate(names):
        for b in names[i+1:]:
            pairs.append((a, b, corr.loc[a, b]))
    pairs.sort(key=lambda x: x[2], reverse=True)
    top = pairs[:10]; bot = pairs[-10:][::-1]
    def render(rows, color):
        items = ''.join(f'<tr><td>{escape(a)}</td><td>{escape(b)}</td>'
                        f'<td style="color:{color};text-align:right;font-weight:600">{v:+.2f}</td></tr>'
                        for a, b, v in rows)
        return f'<table style="font-size:0.85em"><thead><tr><th>Basket A</th><th>Basket B</th><th>ρ</th></tr></thead><tbody>{items}</tbody></table>'
    return (f'<div class="row"><div class="half"><h4>Top 10 most correlated</h4>{render(top, "#2d8a2d")}</div>'
            f'<div class="half"><h4>Top 10 most negatively correlated</h4>{render(bot, "#cc3333")}</div></div>')


def build_preferred_visuals_section(all_res):
    parts = ['<h2 id="preferred-visuals">Preferred Visuals</h2>']
    parts.append('<h3>Factor Rotation Quadrant</h3>')
    parts.append(build_quadrant_chart(all_res))
    parts.append('<h3>Top / Bottom Performers</h3>')
    parts.append(build_leaderboard(all_res, 'ret_5d', '5D return'))
    parts.append(build_leaderboard(all_res, 'ret_21d', '21D return'))
    parts.append('<h3>Top / Bottom Z-Scores (latest 5d return vs trailing history)</h3>')
    parts.append(build_zscore_visual(all_res))
    parts.append('<h3>Cumulative Returns — Top &amp; Bottom 5</h3>')
    parts.append(build_cumulative_overlay_topbottom(all_res, 5))
    parts.append('<h3>Factor Deep Dive — All Periods &amp; Risk Stats</h3>')
    parts.append(build_period_returns_table(all_res))
    parts.append('<h3>Top / Bottom Basket Correlations</h3>')
    parts.append(build_correlation_table(all_res))
    return '\n'.join(parts)


def overlay_returns_plot(all_res):
    fig, ax = plt.subplots(figsize=(11, 5))
    drawn = 0
    for r in all_res:
        if r.get('error') or 'cum_returns' not in r:
            continue
        ax.plot(r['cum_returns'].index, (r['cum_returns'] - 1) * 100,
                lw=0.9, alpha=0.75, label=r['name'])
        drawn += 1
    ax.axhline(0, color='k', lw=0.5)
    ax.set_ylabel('Cumulative return %')
    ax.set_title(f'All baskets — constant-weight backtest from each basket\'s cost_date ({drawn} baskets)')
    ax.grid(alpha=0.3)
    ax.legend(fontsize=6, ncol=4, loc='upper left')
    return fig_to_b64(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=DEFAULT_OUT)
    p.add_argument('--baskets-dir', default=BASKETS_DIR)
    p.add_argument('--label', default='', help='Label appended to report heading')
    p.add_argument('--start-date', default='2025-01-01',
                   help='Uniform start date for cumulative-return chart (default: 2025-01-01)')
    args = p.parse_args()

    print(f"Loading factor model data...")
    factor_exp_df = pd.read_csv(os.path.join(MODEL_DIR, 'russell3000_factor_exposures_historical.csv'))
    factor_ret_df = pd.read_csv(os.path.join(MODEL_DIR, 'barra_factor_returns.csv'), index_col=0)
    factor_cov_df = pd.read_csv(os.path.join(MODEL_DIR, 'barra_factor_covariance.csv'), index_col=0)

    returns_panel = build_returns_panel(factor_exp_df)
    print(f"  Returns panel: {returns_panel.shape[0]} dates x {returns_panel.shape[1]} tickers")

    print("Pre-computing idio vols for all tickers (this is the slow step)...")
    idio_vols = precompute_idio_vols(factor_exp_df, factor_ret_df)
    print(f"  Computed idio vol for {len(idio_vols)} tickers")

    basket_files = sorted(f for f in os.listdir(args.baskets_dir) if f.endswith('.csv'))
    print(f"\nProcessing {len(basket_files)} baskets from {args.baskets_dir}...")

    conn = sqlite3.connect(DB_PATH)
    all_res = []
    for f in basket_files:
        path = os.path.join(args.baskets_dir, f)
        name = os.path.splitext(f)[0]
        basket_df = load_basket(path)
        prices = get_latest_prices(conn, basket_df['ticker'].tolist())
        weights_df = compute_weights(basket_df, prices)
        res = analyze(name, basket_df, weights_df, factor_exp_df,
                      factor_ret_df, factor_cov_df, returns_panel, idio_vols,
                      args.start_date)
        all_res.append(res)
        status = res.get('error', f"{res['n_matched']}/{res['n_priced']} matched, ret {res.get('total_return_pct', 0):+.0f}%")
        print(f"  {name:40s}  {status}")
    conn.close()

    print(f"\nBuilding HTML report...")
    overlay_b64 = overlay_returns_plot(all_res)
    preferred = build_preferred_visuals_section(all_res)
    sections = '\n'.join(section_html(r) for r in all_res)
    summary = summary_table(all_res)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Basket Report</title>
<style>
 body {{ font-family: -apple-system, Segoe UI, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 20px; color: #222; }}
 h1, h2, h3 {{ color: #1a3a6c; }}
 section {{ border-top: 1px solid #ccc; padding-top: 16px; margin-top: 24px; }}
 .stats {{ display: flex; flex-wrap: wrap; gap: 18px; font-size: 0.9em; margin: 8px 0; }}
 table {{ border-collapse: collapse; width: 100%; font-size: 0.88em; }}
 th, td {{ border-bottom: 1px solid #eee; padding: 5px 8px; text-align: right; }}
 th:first-child, td:first-child {{ text-align: left; }}
 thead th {{ background: #f0f4f8; }}
 tbody tr:hover {{ background: #fafafa; }}
 .row {{ display: flex; gap: 10px; }}
 .row img.half {{ width: 49%; height: auto; }}
 img {{ max-width: 100%; }}
 a {{ color: #1a3a6c; text-decoration: none; }}
 a:hover {{ text-decoration: underline; }}
</style></head><body>
<h1>Basket Risk &amp; Return Report{' — ' + escape(args.label) if args.label else ''}</h1>
<p>Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}. Each basket backtested with constant weights from
<b>{args.start_date}</b> (uniform across baskets) to {factor_exp_df['date'].max()}. Basket sized to a $1M nominal
at its earliest cost_date. Trailing returns and z-scores are computed over the full available history.
Z-score uses 1-day return mean/std scaled to 5-day equivalent, latest 5d return excluded from the trailing window.
Risk decomposition uses the factor model estimated over the full window
({factor_exp_df['date'].min()} → {factor_exp_df['date'].max()}, {factor_exp_df['date'].nunique()} trading days).</p>

{preferred}

<h2>Summary</h2>
{summary}
<h2>Cumulative returns — all baskets</h2>
<img src="data:image/png;base64,{overlay_b64}" />
<h2>Per-basket detail</h2>
{sections}
</body></html>
"""

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write(html)
    print(f"\nReport written to {args.out}")
    print(f"  Size: {os.path.getsize(args.out)/1024:.0f} KB")


if __name__ == '__main__':
    main()
