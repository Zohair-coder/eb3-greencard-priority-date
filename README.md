# EB-3 Backlog Chart

This project scrapes the most recent 48 USCIS "When to File" bulletins to extract the Employment-Based Third Preference (EB-3) **Final Action Date** for "All Chargeability Areas Except Those Listed" and charts the resulting backlog in months.

## Prerequisites

-   Python 3.11+
-   The Python dependencies listed in `requirements.txt`:
    -   `requests`
    -   `beautifulsoup4`
    -   `matplotlib`
    -   `python-dateutil`

Install them with:

```bash
pip install -r requirements.txt
```

## Usage

Run the scraper from the repository root:

```bash
python -m src.scrape_backlog
```

The script will download the latest 48 bulletins (for example, September 2025 back through October 2021), extract the relevant EB-3 final action cut-off dates, calculate the backlog in months, and store the results in the `artifacts/` directory:

-   `artifacts/eb3_backlog_months.csv` — tabular data containing the bulletin month, raw final action date string, computed backlog, and source URL.
-   `artifacts/eb3_backlog_months.png` — a line chart of backlog months vs. bulletin month.

## Notes

-   If the final action date is listed as `C` (current), the backlog is recorded as `0` months.
-   If the final action date is `U` (unauthorized/unavailable), the backlog value is left blank in the CSV and plotted as `NaN`, so it is omitted from the chart line.
-   The scraper respects the USCIS site by pausing between requests; collecting 48 months takes roughly 15–20 seconds.
