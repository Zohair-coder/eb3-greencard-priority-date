import requests
from pathlib import Path

URL = "https://www.uscis.gov/green-card/green-card-processes-and-procedures/visa-availability-priority-dates/when-to-file-your-adjustment-of-status-application-for-family-sponsored-or-employment-based-50"
resp = requests.get(URL, timeout=30)
print(resp.status_code)
Path("page_50.html").write_text(resp.text)
