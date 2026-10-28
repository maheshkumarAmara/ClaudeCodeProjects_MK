"""HTML export of a validation run."""


def generate_html_report(order_nums: list, all_dl_sections: dict,
                         env: str, timestamp: str,
                         grand_total: int, grand_passed: int, grand_failed: int) -> str:
    rows_html = ""
    for section, df in all_dl_sections.items():
        rows_html += f'<h3 style="margin-top:2rem;color:#1a3a6e;">{section}</h3>'
        rows_html += '<table><thead><tr>'
        for col in df.columns:
            rows_html += f'<th>{col}</th>'
        rows_html += '</tr></thead><tbody>'
        for _, row in df.iterrows():
            status = str(row.get("Status", ""))
            if "FAIL" in status:
                bg = "#ffe0e0"
            elif "PASS" in status:
                bg = "#e0f5e9"
            elif "N/A" in status or "ℹ️" in status:
                bg = "#e8f4ff"
            else:
                bg = "#ffffff"
            rows_html += f'<tr style="background:{bg};">'
            for val in row:
                rows_html += f'<td>{val}</td>'
            rows_html += '</tr>'
        rows_html += '</tbody></table>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Order Validation Report</title>
<style>
body{{font-family:Inter,Arial,sans-serif;margin:2rem;background:#f5f8fc;color:#1a1a2e}}
h1{{color:#0d1b2a}} h2{{color:#1a3a6e}} h3{{color:#1a3a6e;border-bottom:1px solid #cce}}
table{{border-collapse:collapse;width:100%;margin-bottom:1rem;background:#fff;
       box-shadow:0 1px 4px rgba(0,0,0,.08);border-radius:6px;overflow:hidden}}
th{{background:#1a3a6e;color:#fff;padding:.5rem .75rem;text-align:left;font-size:.82rem}}
td{{padding:.4rem .75rem;font-size:.82rem;border-bottom:1px solid #eee}}
.meta{{background:#fff;border-radius:8px;padding:1rem 1.5rem;margin-bottom:1.5rem;
       box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.badge{{display:inline-block;padding:.2rem .6rem;border-radius:12px;font-weight:600;font-size:.8rem}}
.pass{{background:#e0f5e9;color:#1a7a3c}} .fail{{background:#ffe0e0;color:#a00}} .info{{background:#e8f4ff;color:#1a3a6e}}
</style></head><body>
<h1>✅ Order Validation Report</h1>
<div class="meta">
  <b>Date:</b> {timestamp} &nbsp;|&nbsp; <b>Environment:</b> {env} &nbsp;|&nbsp;
  <b>Orders:</b> {', '.join(order_nums)}<br>
  <span class="badge pass">✅ Passed: {grand_passed}</span>&nbsp;
  <span class="badge fail">❌ Failed: {grand_failed}</span>&nbsp;
  <span class="badge info">Total: {grand_total}</span>
</div>
{rows_html}
</body></html>"""
