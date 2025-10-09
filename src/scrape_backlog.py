"""Scrape USCIS visa bulletin pages to chart EB-3 backlog."""

from __future__ import annotations

import csv
import logging
import math
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup, Tag
from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

LOGGER = logging.getLogger(__name__)
BASE_URL = (
    "https://www.uscis.gov/green-card/green-card-processes-and-procedures/"
    "visa-availability-priority-dates/"
    "when-to-file-your-adjustment-of-status-application-for-family-sponsored-or-"
    "employment-based-{}"
)
DOS_BULLETIN_URL = (
    "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin/{folder_year}/"
    "visa-bulletin-for-{month}-{slug_year}.html"
)
INDEX_URLS = [
    (
        "https://www.uscis.gov/green-card/green-card-processes-and-procedures/"
        "visa-availability-priority-dates/adjustment-of-status-filing-charts-from-the-visa-bulletin"
    ),
    (
        "https://www.uscis.gov/green-card/green-card-processes-and-procedures/"
        "visa-availability-priority-dates"
    ),
]
DEFAULT_START_PAGE_ID = 116
MAX_PAGES_TO_CHECK = 400  # safeguard so we don't loop forever if structure changes
REQUEST_TIMEOUT = 30
MAX_WORKERS = 6
CONSECUTIVE_NOT_FOUND_LIMIT = 5
TARGET_CAPTION = (
    "Final Action Dates for Employment-Based Adjustment of Status Applications"
)
TARGET_ROW_LABEL = "3rd"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

MONTH_REGEX = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    re.IGNORECASE,
)


@dataclass
class BulletinRecord:
    """Represents data extracted for a single visa bulletin month."""

    bulletin_month: datetime
    raw_date: str
    backlog_months: Optional[float]
    source_url: str

    @property
    def month_label(self) -> str:
        return self.bulletin_month.strftime("%b %Y")

    @property
    def backlog_label(self) -> str:
        if self.backlog_months is None or math.isnan(self.backlog_months):
            return "N/A"
        return f"{self.backlog_months:.2f}"


def fetch_page_html(page_id: int) -> tuple[str, str]:
    url = BASE_URL.format(page_id)
    LOGGER.info("Fetching %s", url)
    response = requests.get(
        url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    if response.status_code == 404:
        raise FileNotFoundError(f"USCIS page {url} returned 404.")
    response.raise_for_status()
    return response.text, url


def build_dos_url(bulletin_month: datetime) -> str:
    month_slug = bulletin_month.strftime("%B").lower()
    slug_year = bulletin_month.strftime("%Y")
    folder_year = bulletin_month.year
    if bulletin_month.month >= 10:
        folder_year += 1
    return DOS_BULLETIN_URL.format(
        folder_year=folder_year, slug_year=slug_year, month=month_slug
    )


def discover_latest_start_page_id() -> int:
    LOGGER.info("Discovering latest USCIS employment-based bulletin page ID")

    for index_url in INDEX_URLS:
        try:
            response = requests.get(
                index_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network resilience
            LOGGER.debug("Failed to fetch %s: %s", index_url, exc)
            continue

        matches = {
            int(match)
            for match in re.findall(
                r"employment-based-(\d+)", response.text, re.IGNORECASE
            )
        }
        if matches:
            latest_id = max(matches)
            LOGGER.info("Discovered latest page id %s from %s", latest_id, index_url)
            return latest_id
        LOGGER.debug("No employment-based links discovered on %s", index_url)

    raise ValueError(
        "Could not find any employment-based bulletin links on the index pages."
    )


def fetch_dos_final_action(bulletin_month: datetime) -> tuple[str, str]:
    url = build_dos_url(bulletin_month)
    LOGGER.info(
        "Falling back to Department of State bulletin %s for %s",
        url,
        bulletin_month.strftime("%b %Y"),
    )

    response = requests.get(
        url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    table = find_dos_employment_table(soup)

    column_index = get_chargeability_column_index(table)
    target_row = find_target_row(table)
    raw_value = parse_final_action_date(target_row, column_index)

    return raw_value, url


def parse_bulletin_month(soup: BeautifulSoup) -> datetime:
    header = soup.find("h1", class_=re.compile("page-title")) or soup.find("h1")
    if header:
        match = MONTH_REGEX.search(header.get_text(" ", strip=True))
        if match:
            month_text = match.group(0).replace("\xa0", " ")
            return date_parser.parse(month_text, fuzzy=True)

    month_heading = soup.find(string=MONTH_REGEX)
    if month_heading:
        match = MONTH_REGEX.search(month_heading)
        if match:
            month_text = match.group(0).replace("\xa0", " ")
            return date_parser.parse(month_text, fuzzy=True)

    raise ValueError("Unable to determine bulletin month from page content.")


def find_dos_employment_table(soup: BeautifulSoup) -> Tag:
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if header_row is None:
            continue
        header_text = header_row.get_text(" ", strip=True).lower()
        if "employment" in header_text and "chargeability" in header_text:
            return table
    raise ValueError(
        "Could not locate the employment-based table on DOS bulletin page."
    )


def find_target_row(table: Tag) -> Tag:
    for row in table.find_all("tr"):
        header_cell = row.find("th") or row.find("td")
        if not header_cell:
            continue
        header_text = header_cell.get_text(" ", strip=True)
        normalized = re.sub(r"\s+", " ", header_text).strip().lower()
        normalized_alnum = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
        if (
            normalized.startswith(TARGET_ROW_LABEL.lower())
            or normalized_alnum.startswith(TARGET_ROW_LABEL.lower())
            or normalized.startswith("third")
            or normalized_alnum.startswith("third")
            or "eb 3" in normalized_alnum
            or ("employment" in normalized and "third" in normalized)
        ):
            return row
    raise ValueError(f"Could not find row labeled '{TARGET_ROW_LABEL}' in the table.")


def get_chargeability_column_index(table: Tag) -> int:
    header_section = table.find("thead")
    header_row = None
    if header_section:
        header_row = header_section.find("tr")
    if header_row is None:
        header_row = table.find("tr")
    if header_row is None:
        raise ValueError("Unable to locate header row in employment-based table.")

    header_cells = header_row.find_all(["th", "td"])
    if len(header_cells) <= 1:
        raise ValueError(
            "Employment-based table header does not contain expected columns."
        )

    for data_index, cell in enumerate(header_cells[1:]):
        text = cell.get_text(" ", strip=True).lower()
        if "all chargeability" in text:
            return data_index

    raise ValueError(
        "Could not find 'All Chargeability Areas Except Those Listed' column."
    )


def parse_final_action_date(row: Tag, column_index: int) -> str:
    cells = row.find_all(["td", "th"])
    if len(cells) <= column_index + 1:
        raise ValueError("Target column index exceeds available cells in the row.")
    return cells[column_index + 1].get_text(strip=True)


def compute_backlog_months(
    bulletin_month: datetime, final_action_text: str
) -> Optional[float]:
    value = final_action_text.strip().upper()
    if not value or value in {"U", "UNAVAILABLE"}:
        return math.nan
    if value in {"C", "CURRENT"}:
        return 0.0

    try:
        final_date = datetime.strptime(value, "%d%b%y")
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(
            f"Could not parse final action date '{final_action_text}'."
        ) from exc

    bulletin_date = bulletin_month.replace(day=1)
    if final_date > bulletin_date:
        return 0.0

    delta = relativedelta(bulletin_date, final_date)
    backlog = delta.years * 12 + delta.months + delta.days / 30.0
    return round(max(backlog, 0.0), 2)


def extract_record(page_id: int) -> BulletinRecord:
    html, url = fetch_page_html(page_id)
    soup = BeautifulSoup(html, "html.parser")

    bulletin_month = parse_bulletin_month(soup)
    table = None
    for caption in soup.find_all("caption"):
        if TARGET_CAPTION.lower() in caption.get_text(strip=True).lower():
            table = caption.find_parent("table")
            break
    data_source_url = url
    if table is not None:
        column_index = get_chargeability_column_index(table)
        target_row = find_target_row(table)
        raw_value = parse_final_action_date(target_row, column_index)
    else:
        raw_value, data_source_url = fetch_dos_final_action(bulletin_month)

    backlog = compute_backlog_months(bulletin_month, raw_value)

    return BulletinRecord(
        bulletin_month=bulletin_month,
        raw_date=raw_value,
        backlog_months=backlog,
        source_url=data_source_url,
    )


def collect_records() -> list[BulletinRecord]:
    records_by_month: dict[datetime, BulletinRecord] = {}
    try:
        page_id = discover_latest_start_page_id()
    except Exception as exc:  # pragma: no cover - network resilience
        LOGGER.warning(
            "Falling back to default start page id %s: %s",
            DEFAULT_START_PAGE_ID,
            exc,
        )
        page_id = DEFAULT_START_PAGE_ID
    pages_checked = 0
    consecutive_missing = 0
    active_futures: dict = {}
    stopping = False

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        while (page_id > 0 or active_futures) and pages_checked < MAX_PAGES_TO_CHECK:
            while (
                not stopping
                and page_id > 0
                and pages_checked < MAX_PAGES_TO_CHECK
                and len(active_futures) < MAX_WORKERS
            ):
                future = executor.submit(extract_record, page_id)
                active_futures[future] = page_id
                page_id -= 1
                pages_checked += 1

            if not active_futures:
                break

            done, _ = wait(active_futures.keys(), return_when=FIRST_COMPLETED)
            for future in done:
                pid = active_futures.pop(future)
                try:
                    record = future.result()
                except FileNotFoundError:
                    consecutive_missing += 1
                    LOGGER.info(
                        "USCIS page %s missing (%s consecutive).",
                        pid,
                        consecutive_missing,
                    )
                    if consecutive_missing >= CONSECUTIVE_NOT_FOUND_LIMIT:
                        LOGGER.info(
                            "Stopping after %s consecutive missing pages.",
                            consecutive_missing,
                        )
                        stopping = True
                        page_id = 0
                except ValueError as exc:
                    LOGGER.warning("Skipping page %s: %s", pid, exc)
                    consecutive_missing = 0
                except Exception as exc:  # pragma: no cover - diagnostic
                    LOGGER.error("Failed to process page %s: %s", pid, exc)
                    consecutive_missing = 0
                else:
                    consecutive_missing = 0
                    if record.bulletin_month not in records_by_month:
                        records_by_month[record.bulletin_month] = record
                        LOGGER.info(
                            "Collected %s records so far (page %s → %s)",
                            len(records_by_month),
                            pid,
                            record.month_label,
                        )

    if not records_by_month:
        LOGGER.warning("No records collected after checking %s pages.", pages_checked)

    return sorted(records_by_month.values(), key=lambda item: item.bulletin_month)


def write_csv(records: list[BulletinRecord], destination: Path) -> None:
    with destination.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["month", "final_action", "backlog_months", "source_url"])
        for record in records:
            backlog_value = (
                ""
                if record.backlog_months is None or math.isnan(record.backlog_months)
                else f"{record.backlog_months:.2f}"
            )
            writer.writerow(
                [
                    record.month_label,
                    record.raw_date,
                    backlog_value,
                    record.source_url,
                ]
            )


def generate_plot(records: list[BulletinRecord], destination: Path) -> None:
    if not records:
        raise ValueError("No data available to plot.")

    x_dates = [record.bulletin_month.replace(day=1) for record in records]
    x_values = mdates.date2num(x_dates)
    y_values = [
        math.nan if record.backlog_months is None else record.backlog_months
        for record in records
    ]

    plt.figure(figsize=(14, 6))
    ax = plt.gca()
    ax.plot(
        x_values,
        y_values,
        linestyle="-",
        marker="o",
        linewidth=2,
        color="#2a6f97",
    )
    ax.xaxis_date()
    locator = mdates.AutoDateLocator(minticks=6, maxticks=14)
    formatter = mdates.ConciseDateFormatter(locator)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

    plt.title("EB-3 All Chargeability Backlog (Final Action Dates)")
    plt.xlabel("Visa Bulletin Month")
    plt.ylabel("Backlog (months)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(destination, dpi=200)
    plt.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    records = collect_records()

    if not records:
        raise SystemExit("No records were collected. Aborting.")

    records.sort(key=lambda item: item.bulletin_month)

    output_dir = Path("artifacts")
    output_dir.mkdir(exist_ok=True)

    csv_path = output_dir / "eb3_backlog_months.csv"
    png_path = output_dir / "eb3_backlog_months.png"

    write_csv(records, csv_path)
    generate_plot(records, png_path)

    LOGGER.info("Saved CSV data to %s", csv_path.resolve())
    LOGGER.info("Saved backlog chart to %s", png_path.resolve())

    latest = records[-1]
    LOGGER.info(
        "Latest bulletin (%s): final action %s, backlog %s months",
        latest.month_label,
        latest.raw_date,
        latest.backlog_label,
    )


if __name__ == "__main__":
    main()
