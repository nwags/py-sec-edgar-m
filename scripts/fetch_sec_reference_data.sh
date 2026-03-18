#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-refdata/sec_sources}"
mkdir -p "$OUT_DIR"

USER_AGENT="${SEC_USER_AGENT:-NickWagnerResearch sec-ingest-admin@example.com}"

fetch() {
  local url="$1"
  local out="$2"
  echo "Fetching $url -> $out"
  curl -fL     --retry 5     --retry-delay 2     --retry-all-errors     -H "User-Agent: ${USER_AGENT}"     -o "${OUT_DIR}/${out}"     "$url"
}

fetch "https://www.sec.gov/files/company_tickers.json" "company_tickers.json"
fetch "https://www.sec.gov/files/company_tickers_exchange.json" "company_tickers_exchange.json"
fetch "https://www.sec.gov/files/company_tickers_mf.json" "company_tickers_mf.json"
fetch "https://www.sec.gov/include/ticker.txt" "ticker.txt"
fetch "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt" "cik-lookup-data.txt"
fetch "https://www.sec.gov/files/investment/data/other/investment-company-series-class-information/investment-company-series-class-2025.csv" "investment-company-series-class-2025.csv"

echo
echo "Saved SEC reference files into ${OUT_DIR}"
