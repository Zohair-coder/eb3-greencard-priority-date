# EB-3 Backlog Chart

Website: https://eb3.zohair.dev

This project scrapes every available USCIS "When to File" bulletin archive page to extract the Employment-Based Third Preference (EB-3) **Final Action Date** for "All Chargeability Areas Except Those Listed" and charts the resulting backlog in months.

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

The script will walk the archive from the newest bulletin backward, gathering every month that is still published. For each bulletin it extracts the relevant EB-3 final action cut-off date, calculates the backlog in months, and stores the results in the `artifacts/` directory:

-   `artifacts/eb3_backlog_months.csv` — tabular data containing the bulletin month, raw final action date string, computed backlog, and source URL.
-   `artifacts/eb3_backlog_months.png` — a line chart of backlog months vs. bulletin month.

## Notes

-   If the final action date is listed as `C` (current), the backlog is recorded as `0` months.
-   If the final action date is `U` (unauthorized/unavailable), the backlog value is left blank in the CSV and plotted as `NaN`, so it is omitted from the chart line.
-   The scraper discovers the latest USCIS "When to File" page automatically before walking backward through the archive, so you don't need to update a hard-coded start page when a new bulletin is published.
-   It fetches several pages in parallel (default: 6 workers) while still stopping as soon as the archive returns a run of missing pages. You can reduce the concurrency by editing `MAX_WORKERS` in `src/scrape_backlog.py` if you prefer a slower crawl.
-   A scheduled GitHub Actions workflow (`.github/workflows/monthly-scrape.yml`) runs on the first day of each month to refresh the artifacts automatically.
