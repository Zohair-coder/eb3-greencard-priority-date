from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime
import re

MONTH_REGEX = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
    re.IGNORECASE,
)

html = Path("page.html").read_text()
soup = BeautifulSoup(html, "html.parser")
header = soup.find("h1", class_="page-title") or soup.find("h1")
if header:
    text = header.get_text(" ", strip=True)
    Path("header.txt").write_text(text)
    match = MONTH_REGEX.search(text)
    Path("match.txt").write_text(match.group(0) if match else "NO MATCH")
    if match:
        cleaned = match.group(0).replace("\xa0", " ")
        Path("parsed.txt").write_text(str(datetime.strptime(cleaned, "%B %Y")))
else:
    Path("header.txt").write_text("NO HEADER")
