# SEC Reference Links

Official SEC URLs discussed for repo refdata refresh:

- https://www.sec.gov/files/company_tickers.json
- https://www.sec.gov/files/company_tickers_exchange.json
- https://www.sec.gov/files/company_tickers_mf.json
- https://www.sec.gov/include/ticker.txt
- https://www.sec.gov/Archives/edgar/cik-lookup-data.txt
- https://www.sec.gov/files/investment/data/other/investment-company-series-class-information/investment-company-series-class-*.csv

Implementation note:
- Use the newest local `investment-company-series-class-*.csv` file during refdata refresh (highest year token, then mtime fallback).

Core index / archive roots:

- https://www.sec.gov/Archives/edgar/full-index/
- https://www.sec.gov/Archives/edgar/daily-index/
- https://www.sec.gov/Archives/edgar/Feed/
- https://www.sec.gov/Archives/edgar/Oldloads/

Core APIs:

- https://data.sec.gov/submissions/CIK##########.json
- https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
- https://data.sec.gov/api/xbrl/companyconcept/CIK##########/<taxonomy>/<concept>.json
- https://data.sec.gov/api/xbrl/frames/<taxonomy>/<concept>/<unit>/<period>.json
