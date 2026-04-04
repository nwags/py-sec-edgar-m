# SEC_DATA_SOURCES.md

## Core official SEC sources

### Association / lookup files
- `https://www.sec.gov/files/company_tickers.json`
- `https://www.sec.gov/files/company_tickers_exchange.json`
- `https://www.sec.gov/files/company_tickers_mf.json`
- `https://www.sec.gov/include/ticker.txt`
- `https://www.sec.gov/Archives/edgar/cik-lookup-data.txt`

### EDGAR indexes and archives
- `https://www.sec.gov/Archives/edgar/full-index/`
- `https://www.sec.gov/Archives/edgar/daily-index/`
- `https://www.sec.gov/Archives/edgar/Feed/`
- `https://www.sec.gov/Archives/edgar/Oldloads/`

### Data APIs
- `https://data.sec.gov/submissions/CIK##########.json`
- `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
- `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/<taxonomy>/<concept>.json`
- `https://data.sec.gov/api/xbrl/frames/<taxonomy>/<concept>/<unit>/<period>.json`

## Additional high-value SEC datasets for this project

### Investment company series / class mappings
- `https://www.sec.gov/files/investment/data/other/investment-company-series-class-information/investment-company-series-class-*.csv`

### SEC data-library datasets worth considering later
- Form 13F data sets
- Form D data sets
- Regulation A data sets
- Insider Transactions data sets
- Financial Statement and Notes data sets

## Notes

- The ticker/exchange/mutual-fund files are useful bootstrap sources, but they are not complete enough by themselves for all EDGAR actors.
- The all-CIK text file is historically cumulative and includes individuals and funds.
- Index files remain essential because they let us discover filing candidates across all forms, not just API-covered XBRL-centric submissions.
- For investment-company series/class data, local loaders should select the newest matching `investment-company-series-class-*.csv` file (prefer highest year token in filename, then latest mtime).
- Source/surface assumptions should be represented explicitly in normalized authority artifacts (`sec_source_surfaces.parquet`) instead of only in scattered code constants.
