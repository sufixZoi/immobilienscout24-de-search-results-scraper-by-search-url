thonimport csv
import html
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)

def _ensure_list(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []

def _collect_fieldnames(rows: Iterable[Dict[str, Any]]) -> List[str]:
    fieldnames: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    return fieldnames

def export_json(data: Any, path: Path) -> None:
    rows = _ensure_list(data)
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

def export_csv(data: Any, path: Path) -> None:
    rows = _ensure_list(data)
    fieldnames = _collect_fieldnames(rows)
    if not fieldnames:
        logger.warning("No data to export to CSV.")
        fieldnames = ["title", "price", "address", "listing_url", "apify_monitoring_status"]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

def export_html(data: Any, path: Path) -> None:
    rows = _ensure_list(data)
    fieldnames = _collect_fieldnames(rows)
    if not fieldnames:
        fieldnames = ["title", "price", "address", "listing_url", "apify_monitoring_status"]

    head_cells = "".join(f"<th>{html.escape(str(name))}</th>" for name in fieldnames)

    body_rows = []
    for row in rows:
        cells = []
        for name in fieldnames:
            value = row.get(name, "")
            cells.append(f"<td>{html.escape(str(value))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>immobilienscout24.de Search Results</title>
  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 20px;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #ddd;
      padding: 8px;
      font-size: 14px;
    }}
    th {{
      background-color: #f4f4f4;
      text-align: left;
    }}
    tr:nth-child(even) {{
      background-color: #fafafa;
    }}
  </style>
</head>
<body>
  <h1>immobilienscout24.de Search Results</h1>
  <table>
    <thead>
      <tr>{head_cells}</tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</body>
</html>
""".strip()

    with path.open("w", encoding="utf-8") as f:
        f.write(table_html)

def export_results(data: Any, fmt: str, path: Path) -> None:
    fmt = fmt.lower()
    logger.debug("Exporting results to %s as %s", path, fmt)
    if fmt == "json":
        export_json(data, path)
    elif fmt == "csv":
        export_csv(data, path)
    elif fmt == "html":
        export_html(data, path)
    else:
        raise ValueError(f"Unsupported export format: {fmt}")