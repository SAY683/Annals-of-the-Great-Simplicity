"""History export formatting services."""
import csv
import io
import json

from services.history_report import build_human_report_md, md_to_html


def summary_json(summary) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2)


def summary_csv(summary) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['field', 'value'])
    writer.writerow(['task_id', summary['task_id']])
    writer.writerow(['updated_at', summary['updated_at']])
    writer.writerow(['image_count', len(summary['images'])])
    writer.writerow(['images', ';'.join(summary['images'])])
    config = summary.get('config') or {}
    for key, value in config.items():
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        writer.writerow([f'config.{key}', value])
    return buf.getvalue().encode('utf-8-sig')


def report_md(task_id: str) -> str:
    return build_human_report_md(task_id)


def report_html(task_id: str) -> str:
    md_content = build_human_report_md(task_id)
    html_body = md_to_html(md_content)
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>EDM-Takens 人话版报告 — {task_id}</title>
  <style>
    :root {{
      --bg: #0b0f17;
      --panel: #111827;
      --panel-solid: #0f1520;
      --border: #1f2a36;
      --text: #d1d5db;
      --muted: #94a3b8;
      --dept-color: #00ff9d;
      --dept-color-rgb: 0, 255, 157;
      --dept-dim: #00cc7d;
      --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: "JetBrains Mono", Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.6;
    }}
    .report-wrap {{
      max-width: 960px;
      margin: 0 auto;
      border: 1px solid rgba(var(--dept-color-rgb), 0.25);
      border-radius: 8px;
      background: rgba(0, 0, 0, 0.32);
      padding: 24px;
      box-shadow: inset 0 0 30px rgba(0, 0, 0, 0.3);
    }}
    h1, h2, h3, h4 {{
      color: var(--dept-color);
      font-weight: 700;
      margin-top: 1.4em;
      margin-bottom: 0.6em;
    }}
    h1 {{ font-size: 1.4rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4em; margin-top: 0; }}
    h2 {{ font-size: 1.15rem; border-left: 3px solid var(--dept-color); padding-left: 10px; }}
    h3 {{ font-size: 1rem; color: var(--dept-dim); }}
    h4 {{ font-size: 0.95rem; color: var(--muted); }}
    p {{ margin: 0.6em 0; }}
    a {{ color: var(--dept-color); text-decoration: underline; text-underline-offset: 2px; }}
    ul, ol {{ margin: 0.6em 0; padding-left: 1.4em; }}
    li {{ margin-bottom: 0.35em; }}
    blockquote {{
      margin: 1em 0;
      padding: 10px 14px;
      border-left: 3px solid var(--dept-color);
      background: rgba(var(--dept-color-rgb), 0.06);
      color: var(--muted);
    }}
    code {{
      background: rgba(255, 255, 255, 0.08);
      padding: 2px 5px;
      border-radius: 4px;
      font-family: var(--font-mono);
      color: var(--dept-dim);
      font-size: 0.9em;
    }}
    pre {{
      background: var(--panel-solid);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
      font-family: var(--font-mono);
      font-size: 0.85em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1em 0;
      font-size: 0.9em;
      table-layout: fixed;
    }}
    th, td {{
      border: 1px solid var(--border);
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }}
    th {{
      background: rgba(var(--dept-color-rgb), 0.08);
      color: var(--dept-color);
      font-weight: 600;
    }}
    tr:nth-child(even) td {{ background: rgba(255, 255, 255, 0.02); }}
    strong {{ color: var(--dept-dim); }}
    .meta {{ color: var(--muted); font-size: 0.85em; margin-bottom: 1em; }}
    .footer {{ margin-top: 2em; padding-top: 1em; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.85em; text-align: center; }}
    @media (max-width: 640px) {{
      body {{ padding: 12px; }}
      .report-wrap {{ padding: 16px; }}
      table {{ font-size: 0.8em; }}
      th, td {{ padding: 4px 5px; }}
    }}
  </style>
</head>
<body>
  <div class="report-wrap">
    {html_body}
    <div class="footer">报告由 EDM-Takens Web 自动生成 | task {task_id}</div>
  </div>
</body>
</html>"""
    return html_content
