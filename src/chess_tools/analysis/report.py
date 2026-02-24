import os
import re
import json
import html
import logging
from typing import List, Dict, Optional
from chess_tools.lib.models import CrucialMoment
from chess_tools.analysis.engine import TACTIC_LABELS, TACTIC_COLORS, MOMENT_TYPE_LABELS, SEVERITY_COLORS

logger = logging.getLogger("chess_transfer")

def generate_markdown_report(moments: List[CrucialMoment], metadata: Dict[str, str], output_dir: str = "analysis", summary: str = None):
    """
    Generates a Markdown report from the analyzed moments.
    
    Args:
        moments (List[CrucialMoment]): The list of analyzed moments.
        metadata (Dict[str, str]): Game metadata (White, Black, Date, etc.).
        output_dir (str): Directory to save the report and images.
        summary (str, optional): The LLM generated summary of the game.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Create images subdirectory
    images_dir = os.path.join(output_dir, "images")
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)

    # Create filename: Date_White_vs_Black.md
    safe_date = metadata['Date'].replace('.', '-')
    safe_white = "".join(c for c in metadata['White'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    safe_black = "".join(c for c in metadata['Black'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    filename = f"{safe_date}_{safe_white}_vs_{safe_black}.md"
    output_path = os.path.join(output_dir, filename)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# Analysis: {metadata['White']} vs {metadata['Black']}\n\n")
        f.write(f"**Date:** {metadata['Date']} | **Event:** {metadata['Event']} | **Site:** {metadata['Site']}\n\n")
        
        if not moments:
            f.write("No crucial moments (blunders/missed wins) detected for the hero in this game.\n")
            logger.info(f"Report generated (empty): {output_path}")
            return

        blunder_count = sum(1 for m in moments if m.moment_type == "blunder")
        missed_count = sum(1 for m in moments if m.moment_type in ("missed_chance", "missed_mate"))
        f.write(f"Found **{len(moments)}** crucial moments")
        if missed_count:
            f.write(f" ({blunder_count} blunder{'s' if blunder_count != 1 else ''}, {missed_count} missed opportunity{'s' if missed_count != 1 else ''})")
        f.write(".\n\n")

        for i, moment in enumerate(moments, 1):
            # Save SVG to file
            image_filename = f"{filename.replace('.md', '')}_moment_{i}.svg"
            image_path = os.path.join(images_dir, image_filename)

            if moment.svg_content:
                with open(image_path, "w") as img_file:
                    img_file.write(moment.svg_content)

            # Relative path for Markdown
            relative_image_path = f"images/{image_filename}"

            type_label = MOMENT_TYPE_LABELS.get(moment.moment_type, "Blunder")
            severity_label = moment.severity.upper()
            tactic_label = TACTIC_LABELS.get(moment.tactic_type, moment.tactic_type)
            is_missed = moment.moment_type in ("missed_chance", "missed_mate")
            if is_missed:
                tactic_label = f"Missed {tactic_label}"

            f.write(f"## Moment {i} — {type_label} [{severity_label}]\n\n")
            f.write(f"**Tactic:** {tactic_label}\n\n")
            f.write(f"![Position]({relative_image_path})\n\n")
            f.write(f"**FEN:** `{moment.fen}`\n\n")

            if is_missed:
                f.write(f"- **You Played:** **{moment.move_played_san}**\n")
                f.write(f"- **You Could Have Played:** **{moment.best_move_san}**\n")
                f.write(f"- **Eval Swing:** {moment.eval_swing} cp\n")
                if moment.best_line:
                    f.write(f"- **Best Line:** _{moment.best_line}_\n\n")
            else:
                f.write(f"- **You Played:** **{moment.move_played_san}** <span style='color:red'>(Red Arrow)</span>\n")
                f.write(f"- **Engine Best:** **{moment.best_move_san}** <span style='color:green'>(Green Arrow)</span>\n")
                f.write(f"- **Eval Swing:** {moment.eval_swing} cp\n")
                f.write(f"- **Variation:** _{moment.pv_line}_\n\n")

            if moment.tactical_alert:
                f.write(f"> **{moment.tactical_alert}**\n\n")

            if moment.refutation_line:
                f.write(f"**Refutation:** _{moment.refutation_line}_\n\n")

            f.write(f"### Coach Explanation\n")
            f.write(f"{moment.explanation}\n\n")
            f.write("---\n")
        
        if summary:
            f.write("\n" + summary + "\n")
            
    logger.info(f"Report generated: {output_path}")


def _md_to_html(text: str) -> str:
    """Lightweight markdown-to-HTML conversion for LLM summary text."""
    if not text:
        return ""
    escaped = html.escape(text)
    # Bold: **text** -> <strong>text</strong>
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    # Italic: *text* -> <em>text</em>
    escaped = re.sub(r'\*(.+?)\*', r'<em>\1</em>', escaped)
    # List items: lines starting with - or *
    escaped = re.sub(r'^[\-\*]\s+(.+)$', r'<li>\1</li>', escaped, flags=re.MULTILINE)
    # Wrap consecutive <li> in <ul>
    escaped = re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', escaped)
    # Headings: ## text -> <h3>
    escaped = re.sub(r'^##\s+(.+)$', r'<h3>\1</h3>', escaped, flags=re.MULTILINE)
    # Newlines -> <br> (but not after block elements)
    escaped = re.sub(r'(?<!</ul>)(?<!</h3>)(?<!</li>)\n', '<br>\n', escaped)
    return escaped


_HTML_STYLE = """
    :root {
        --bg-color: #1a1a1a;
        --text-color: #e0e0e0;
        --card-bg: #2a2a2a;
        --accent-color: #4a9eff;
        --muted-color: #a0a0a0;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        background-color: var(--bg-color);
        color: var(--text-color);
        padding: 20px;
        display: flex;
        flex-direction: column;
        align-items: center;
        min-height: 100vh;
    }
    .container { max-width: 800px; width: 100%; }
    a { color: var(--accent-color); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .back-link { margin-bottom: 20px; display: inline-block; font-size: 0.95rem; }
    h1 { margin-bottom: 8px; }
    .meta { color: var(--muted-color); margin-bottom: 24px; font-size: 0.95rem; }
    .summary-count { margin-bottom: 24px; font-size: 1.05rem; }
    .moment-card {
        background: var(--card-bg);
        border-radius: 10px;
        padding: 24px;
        margin-bottom: 24px;
    }
    .moment-card h2 { margin-bottom: 16px; font-size: 1.3rem; }
    .board-svg { display: flex; justify-content: center; margin-bottom: 16px; }
    .board-svg svg { max-width: 400px; width: 100%; height: auto; }
    .fen { font-family: monospace; font-size: 0.85rem; color: var(--muted-color); margin-bottom: 12px; word-break: break-all; }
    .move-info { margin-bottom: 12px; line-height: 1.7; }
    .move-played { color: #ff6b6b; font-weight: bold; }
    .move-best { color: #51cf66; font-weight: bold; }
    .eval-swing { color: var(--muted-color); }
    .variation { font-style: italic; color: var(--muted-color); }
    .tactical-alert {
        background: rgba(255, 107, 107, 0.15);
        border-left: 4px solid #ff6b6b;
        padding: 10px 14px;
        margin-bottom: 12px;
        border-radius: 0 6px 6px 0;
        font-weight: bold;
    }
    .explanation {
        border-top: 1px solid #3a3a3a;
        padding-top: 12px;
        margin-top: 12px;
        line-height: 1.6;
    }
    .explanation h3 { font-size: 1rem; margin-bottom: 8px; color: var(--accent-color); }
    .summary-section {
        background: var(--card-bg);
        border-radius: 10px;
        padding: 24px;
        margin-top: 8px;
        line-height: 1.7;
    }
    .summary-section h2 { margin-bottom: 12px; }
    .summary-section ul { padding-left: 20px; margin: 8px 0; }
    .summary-section li { margin-bottom: 4px; }
    .empty-msg { color: var(--muted-color); font-style: italic; margin-top: 20px; }
    .severity-pill {
        display: inline-block;
        font-size: 0.7rem;
        font-weight: bold;
        padding: 2px 8px;
        border-radius: 10px;
        color: #fff;
        margin-left: 8px;
        vertical-align: middle;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .tactic-badge {
        display: inline-block;
        font-size: 0.8rem;
        font-weight: 600;
        padding: 3px 10px;
        border-radius: 6px;
        color: #fff;
        margin-bottom: 12px;
    }
    .best-line {
        background: rgba(0, 102, 221, 0.15);
        border-left: 4px solid #0066dd;
        padding: 10px 14px;
        margin-bottom: 12px;
        border-radius: 0 6px 6px 0;
        font-style: italic;
        color: var(--accent-color);
    }
    .moment-type-label { font-size: 0.9rem; color: var(--muted-color); margin-left: 4px; }

    /* Index page styles */
    .report-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
        gap: 16px;
        margin-top: 24px;
    }
    .report-card {
        background: var(--card-bg);
        border-radius: 10px;
        padding: 20px;
        transition: transform 0.15s, box-shadow 0.15s;
    }
    .report-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
    .report-card h3 { margin-bottom: 8px; font-size: 1.1rem; }
    .report-card .card-meta { color: var(--muted-color); font-size: 0.9rem; margin-bottom: 10px; }
    .report-card .card-moments { color: var(--accent-color); font-weight: bold; }
    .no-reports { color: var(--muted-color); text-align: center; margin-top: 40px; font-style: italic; }
"""


def generate_html_report(moments: List[CrucialMoment], metadata: Dict[str, str],
                         output_dir: str = "docs/analysis", summary: Optional[str] = None):
    """
    Generates a self-contained HTML report with inline SVGs.

    Args:
        moments: The list of analyzed moments.
        metadata: Game metadata (White, Black, Date, etc.).
        output_dir: Directory to save the HTML report.
        summary: Optional LLM-generated game summary.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    safe_date = metadata['Date'].replace('.', '-')
    safe_white = "".join(c for c in metadata['White'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    safe_black = "".join(c for c in metadata['Black'] if c.isalnum() or c in (' ', '_')).replace(' ', '_')
    filename = f"{safe_date}_{safe_white}_vs_{safe_black}.html"
    output_path = os.path.join(output_dir, filename)

    report_meta = json.dumps({
        "date": metadata.get('Date', ''),
        "white": metadata.get('White', ''),
        "black": metadata.get('Black', ''),
        "result": metadata.get('Result', ''),
        "moment_count": len(moments),
    })

    white_esc = html.escape(metadata.get('White', '?'))
    black_esc = html.escape(metadata.get('Black', '?'))
    date_esc = html.escape(metadata.get('Date', '?'))
    event_esc = html.escape(metadata.get('Event', ''))
    site_esc = html.escape(metadata.get('Site', ''))

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="report-data" content='{html.escape(report_meta, quote=True)}'>
    <title>Analysis: {white_esc} vs {black_esc}</title>
    <style>{_HTML_STYLE}</style>
</head>
<body>
<div class="container">
    <a href="index.html" class="back-link">&larr; Back to Index</a>
    <h1>Analysis: {white_esc} vs {black_esc}</h1>
    <div class="meta"><strong>Date:</strong> {date_esc} | <strong>Event:</strong> {event_esc} | <strong>Site:</strong> {site_esc}</div>
""")

    if not moments:
        parts.append('    <p class="empty-msg">No crucial moments (blunders/missed wins) detected for the hero in this game.</p>\n')
    else:
        blunder_count = sum(1 for m in moments if m.moment_type == "blunder")
        missed_count = sum(1 for m in moments if m.moment_type in ("missed_chance", "missed_mate"))
        summary_text = f'Found <strong>{len(moments)}</strong> crucial moment{"s" if len(moments) != 1 else ""}'
        if missed_count:
            summary_text += f' ({blunder_count} blunder{"s" if blunder_count != 1 else ""}, {missed_count} missed opportunity{"s" if missed_count != 1 else ""})'
        parts.append(f'    <p class="summary-count">{summary_text}.</p>\n')

        for i, moment in enumerate(moments, 1):
            type_label = html.escape(MOMENT_TYPE_LABELS.get(moment.moment_type, "Blunder"))
            severity_label = moment.severity.upper()
            severity_color = SEVERITY_COLORS.get(moment.severity, "#7f8c8d")
            tactic_label = TACTIC_LABELS.get(moment.tactic_type, moment.tactic_type)
            tactic_color = TACTIC_COLORS.get(moment.tactic_type, "#7f8c8d")
            is_missed = moment.moment_type in ("missed_chance", "missed_mate")
            if is_missed:
                tactic_label = f"Missed {tactic_label}"

            parts.append(f'    <div class="moment-card">\n')
            parts.append(f'        <h2>Moment {i} <span class="moment-type-label">— {type_label}</span>'
                         f' <span class="severity-pill" style="background:{severity_color}">{severity_label}</span></h2>\n')
            parts.append(f'        <span class="tactic-badge" style="background:{tactic_color}">{html.escape(tactic_label)}</span>\n')

            if moment.svg_content:
                parts.append(f'        <div class="board-svg">{moment.svg_content}</div>\n')

            parts.append(f'        <div class="fen">FEN: {html.escape(moment.fen)}</div>\n')

            parts.append('        <div class="move-info">\n')
            if is_missed:
                parts.append(f'            <span class="move-played">You Played: {html.escape(moment.move_played_san)}</span><br>\n')
                parts.append(f'            <span class="move-best">You Could Have Played: {html.escape(moment.best_move_san)}</span><br>\n')
            else:
                parts.append(f'            <span class="move-played">You Played: {html.escape(moment.move_played_san)}</span><br>\n')
                parts.append(f'            <span class="move-best">Engine Best: {html.escape(moment.best_move_san)}</span><br>\n')
            parts.append(f'            <span class="eval-swing">Eval Swing: {moment.eval_swing} cp</span><br>\n')
            parts.append(f'            <span class="variation">Variation: {html.escape(moment.pv_line)}</span>\n')
            parts.append('        </div>\n')

            if is_missed and moment.best_line:
                parts.append(f'        <div class="best-line">You could have played: {html.escape(moment.best_line)}</div>\n')

            if moment.tactical_alert:
                parts.append(f'        <div class="tactical-alert">{html.escape(moment.tactical_alert)}</div>\n')

            if moment.refutation_line and not is_missed:
                parts.append(f'        <div class="variation" style="margin-bottom:12px">Refutation: {html.escape(moment.refutation_line)}</div>\n')

            if moment.explanation:
                parts.append('        <div class="explanation">\n')
                parts.append('            <h3>Coach Explanation</h3>\n')
                parts.append(f'            <p>{_md_to_html(moment.explanation)}</p>\n')
                parts.append('        </div>\n')

            parts.append('    </div>\n')

    if summary:
        parts.append('    <div class="summary-section">\n')
        parts.append(f'        {_md_to_html(summary)}\n')
        parts.append('    </div>\n')

    parts.append("""</div>
</body>
</html>
""")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))

    logger.info(f"HTML report generated: {output_path}")


def regenerate_index_page(html_output_dir: str):
    """
    Scans html_output_dir for report HTML files and generates an index.html listing them.

    Args:
        html_output_dir: Directory containing the HTML report files.
    """
    if not os.path.exists(html_output_dir):
        os.makedirs(html_output_dir)

    reports = []
    for fname in os.listdir(html_output_dir):
        if not fname.endswith('.html') or fname == 'index.html':
            continue
        fpath = os.path.join(html_output_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read(4096)  # metadata is near the top
            match = re.search(r'<meta\s+name="report-data"\s+content=\'([^\']+)\'', content)
            if match:
                meta = json.loads(html.unescape(match.group(1)))
                meta['filename'] = fname
                reports.append(meta)
        except Exception as e:
            logger.warning(f"Could not read metadata from {fname}: {e}")

    # Sort by date descending
    reports.sort(key=lambda r: r.get('date', ''), reverse=True)

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analysis Reports</title>
    <style>{_HTML_STYLE}</style>
</head>
<body>
<div class="container">
    <h1>Analysis Reports</h1>
    <div class="meta">Game analysis with Stockfish engine and AI coach explanations.</div>
""")

    if not reports:
        parts.append('    <p class="no-reports">No analysis reports yet.</p>\n')
    else:
        parts.append('    <div class="report-grid">\n')
        for r in reports:
            white_esc = html.escape(r.get('white', '?'))
            black_esc = html.escape(r.get('black', '?'))
            date_esc = html.escape(r.get('date', '?'))
            result_esc = html.escape(r.get('result', ''))
            count = r.get('moment_count', 0)
            fname_esc = html.escape(r['filename'])

            parts.append(f"""        <a href="{fname_esc}" class="report-card">
            <h3>{white_esc} vs {black_esc}</h3>
            <div class="card-meta">{date_esc} &middot; {result_esc}</div>
            <div class="card-moments">{count} crucial moment{"s" if count != 1 else ""}</div>
        </a>
""")
        parts.append('    </div>\n')

    parts.append("""</div>
</body>
</html>
""")

    index_path = os.path.join(html_output_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))

    logger.info(f"Index page generated: {index_path} ({len(reports)} reports)")
