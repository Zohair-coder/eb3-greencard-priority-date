import requests
from pathlib import Path

URL = "https://www.uscis.gov/green-card/green-card-processes-and-procedures/visa-availability-priority-dates/when-to-file-your-adjustment-of-status-application-for-family-sponsored-or-employment-based-116"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
resp = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=30)
print(resp.status_code)
Path("page_116.html").write_text(resp.text)
