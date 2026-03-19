import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import time
from urllib import parse
from urllib.parse import urljoin

import logging
logger = logging.getLogger(__name__)

import lxml.html
import pandas as pd

import pyarrow as pa
import pyarrow.parquet as pq

from bs4 import BeautifulSoup

from py_sec_edgar.settings import CONFIG
from py_sec_edgar.download import ProxyRequest
from py_sec_edgar.downloader import DownloadTask, run_bounded_downloads
from py_sec_edgar.filters import (
    apply_filing_filters,
    build_cik_filter_set,
    load_normalized_filter_tables,
)
from py_sec_edgar.utilities import edgar_and_local_differ, walk_dir_fullpath, generate_folder_names_years_quarters, read_xml_feedparser, flattenDict


_IDX_REQUIRED_COLUMNS = {"CIK", "Form Type", "Date Filed", "Filename"}


@dataclass(frozen=True)
class _FeedRuntimeContext:
    normalized_refdata_root: Path
    merged_idx_path: Path
    ticker_list_path: Path
    archives_base_url: str
    forms_list: list[str]


def _non_empty_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_feed_runtime_context(config_obj) -> _FeedRuntimeContext:
    ref_dir_raw = _non_empty_str(getattr(config_obj, "REF_DIR", None))
    if ref_dir_raw is None:
        raise ValueError("Feed runtime config is missing REF_DIR")
    ref_root = Path(ref_dir_raw)

    # Deterministic rule: normalized root is always derived from REF_DIR for feed loading.
    normalized_refdata_root = ref_root / "normalized"

    merged_idx_raw = _non_empty_str(getattr(config_obj, "MERGED_IDX_FILEPATH", None))
    merged_idx_path = Path(merged_idx_raw) if merged_idx_raw else (ref_root / "merged_idx_files.pq")

    ticker_list_raw = _non_empty_str(getattr(config_obj, "TICKER_LIST_FILEPATH", None))
    ticker_list_path = Path(ticker_list_raw) if ticker_list_raw else (ref_root / "tickers.csv")

    archives_base_url = _non_empty_str(getattr(config_obj, "edgar_Archives_url", None)) or "https://www.sec.gov/Archives/"

    forms_list_raw = getattr(config_obj, "forms_list", None)
    forms_list = list(forms_list_raw) if forms_list_raw else []

    return _FeedRuntimeContext(
        normalized_refdata_root=normalized_refdata_root,
        merged_idx_path=merged_idx_path,
        ticker_list_path=ticker_list_path,
        archives_base_url=archives_base_url,
        forms_list=forms_list,
    )


def _ensure_required_columns(df: pd.DataFrame, required: set[str], context: str) -> None:
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"{context} is missing required columns: {', '.join(missing)}")


def _load_merged_idx_filings(merged_path: Path) -> pd.DataFrame:
    if not merged_path.exists():
        raise FileNotFoundError(f"Merged index file not found: {merged_path}")
    df = pq.read_table(str(merged_path)).to_pandas()
    _ensure_required_columns(df, _IDX_REQUIRED_COLUMNS, "Merged index dataset")
    return df.sort_values("Date Filed", ascending=False)


def _read_legacy_ticker_list(ticker_path: Path) -> list[str]:
    if not ticker_path.exists():
        raise FileNotFoundError(f"Ticker list file not found: {ticker_path}")
    df = pd.read_csv(ticker_path, header=None)
    if df.empty:
        return []
    return [str(v).strip() for v in df.iloc[:, 0].tolist() if str(v).strip()]


def load_filings_feed(
    ticker_list_filter=True,
    form_list_filter=True,
    *,
    issuer_tickers=None,
    issuer_ciks=None,
    entity_ciks=None,
    forms=None,
    form_families=None,
    date_from=None,
    date_to=None,
):
    ctx = _resolve_feed_runtime_context(CONFIG)
    issuers, entities = load_normalized_filter_tables(ctx.normalized_refdata_root)

    logging.info('\n\n\n\tLoaded IDX files\n\n\n')

    df_merged_idx_filings = _load_merged_idx_filings(ctx.merged_idx_path)

    bridge_tickers = list(issuer_tickers or [])
    if ticker_list_filter and issuer_tickers is None:
        # Legacy compatibility bridge: ticker list file is still accepted, but
        # resolution is performed against normalized parquet reference data.
        bridge_tickers = _read_legacy_ticker_list(ctx.ticker_list_path)

    selected_forms = forms
    if form_list_filter:
        selected_forms = list(selected_forms or ctx.forms_list)

    cik_filter_set = build_cik_filter_set(
        issuers=issuers,
        entities=entities,
        issuer_tickers=bridge_tickers,
        issuer_ciks=issuer_ciks,
        entity_ciks=entity_ciks,
    )
    df_merged_idx_filings = apply_filing_filters(
        df_merged_idx_filings,
        cik_filter_set=cik_filter_set,
        forms=selected_forms,
        form_families=form_families,
        date_from=date_from,
        date_to=date_to,
    )

    df_filings = df_merged_idx_filings.assign(
        url=df_merged_idx_filings["Filename"].map(lambda x: urljoin(ctx.archives_base_url, str(x)))
    )

    return df_filings

#######################
# DAILY FILINGS FEEDS
# https://www.sec.gov/Archives/edgar/daily-index/
# https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&CIK=&type=&company=&dateb=&owner=include&start=0&count=400&output=atom
# https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK=&type=8-K&type=8-K&owner=exclude&count=400&action=getcurrent

def generate_daily_index_urls_and_filepaths(day):
    edgar_url = r'https://www.sec.gov/Archives/edgar/'
    daily_files_templates = ["master", "form", "company", "crawler", "sitemap"]
    date_formated = datetime.strftime(day, "%Y%m%d")
    daily_files = []
    for template in daily_files_templates:
        download_url = urljoin(edgar_url, "daily-index/{}/QTR{}/{}.{}.idx".format(
            day.year, day.quarter, template, date_formated))
        local_filepath = os.path.join(CONFIG.DAILY_INDEX_DIR, "{}".format(
            day.year), "QTR{}".format(day.quarter), "{}.{}.idx".format(template, date_formated))
        daily_files.append((download_url, local_filepath))
    daily_files[-1] = (daily_files[-1][0].replace("idx", "xml"),
                       daily_files[-1][1].replace("idx", "xml"))
    return daily_files

def update_daily_files():
    sec_dates = pd.date_range(
        datetime.today() - timedelta(days=365 * 22), datetime.today())
    sec_dates_weekdays = sec_dates[sec_dates.weekday < 5]
    sec_dates_weekdays = sec_dates_weekdays.sort_values(ascending=False)
    consecutive_days_same = 0

    for i, day in enumerate(sec_dates_weekdays):
        daily_files = generate_daily_index_urls_and_filepaths(day)
        # url, local = daily_files[0]
        for daily_url, daily_local_filepath in daily_files:

            if consecutive_days_same < 5 and os.path.exists(daily_local_filepath):
                differs = edgar_and_local_differ(
                    daily_url, daily_local_filepath)
                if differs:
                    g = ProxyRequest()
                    g.GET_FILE(daily_url, daily_local_filepath)
                    consecutive_days_same = 0
                else:
                    consecutive_days_same += 1
            elif consecutive_days_same > 5 and os.path.exists(daily_local_filepath):
                pass
            else:
                g = ProxyRequest()
                g.GET_FILE(daily_url, daily_local_filepath)


def merge_idx_files():

    files = walk_dir_fullpath(CONFIG.FULL_INDEX_DIR, contains='.csv')
    if not files:
        raise FileNotFoundError(f"No .csv index files found under {CONFIG.FULL_INDEX_DIR}")

    files.sort(reverse=True)

    dfs = []

    for filepath in files:
        df_ = pd.read_csv(filepath)
        _ensure_required_columns(df_, _IDX_REQUIRED_COLUMNS, f"Index CSV {filepath}")
        dfs.append(df_)

    df_idx = pd.concat(dfs)

    pa_filings = pa.Table.from_pandas(df_idx)

    # out_path = os.path.join(CONFIG.REF_DIR, 'merged_idx_files.csv')
    # df_idx.to_csv(out_path)

    pq_filepath = CONFIG.MERGED_IDX_FILEPATH

    if os.path.exists(pq_filepath):
        os.remove(pq_filepath)

    pq.write_table(pa_filings, pq_filepath, compression='snappy')

    # arrow_table = pa.Table.from_pandas(df_idx)
    # pq.write_table(arrow_table, out_path, compression='GZIP')

    # df_idx = fp.ParquetFile(out_path).to_pandas()

def convert_idx_to_csv(filepath):
    # filepath = latest_full_index_master
    df = pd.read_csv(filepath, skiprows=10, names=['CIK', 'Company Name', 'Form Type', 'Date Filed', 'Filename'], sep='|', engine='python', parse_dates=True)

    df = df[~df['CIK'].astype(str).str.contains("---", na=False)]

    df = df.sort_values('Date Filed', ascending=False)

    df = df.assign(published=pd.to_datetime(df['Date Filed']))

    df.reset_index()

    df.to_csv(filepath.replace(".idx", ".csv"), index=False)

#######################
# FULL-INDEX FILINGS FEEDS (TXT)
# https://www.sec.gov/Archives/edgar/full-index/
# "./{YEAR}/QTR{NUMBER}/"

def update_full_index_feed(save_idx_as_csv=True, skip_if_exists=False):
    started_at = time.monotonic()
    activity_events = []

    dates_quarters = generate_folder_names_years_quarters(CONFIG.index_start_date, CONFIG.index_end_date)

    latest_full_index_master = os.path.join(CONFIG.FULL_INDEX_DIR, "master.idx")

    if os.path.exists(latest_full_index_master):
        os.remove(latest_full_index_master)

    g = ProxyRequest()

    if g.GET_FILE(CONFIG.edgar_full_master_url, latest_full_index_master):
        convert_idx_to_csv(latest_full_index_master)
        activity_events.append({"stage": "index_refresh", "status": "success", "item": latest_full_index_master, "detail": "latest_master"})
    else:
        logging.warning("Unable to download latest master index; continuing with quarter index files")
        activity_events.append({"stage": "index_refresh", "status": "failed", "item": latest_full_index_master, "detail": "latest_master"})

    pending_downloads = []
    existing_idx_to_convert = []

    for year, qtr in dates_quarters:

        # CONFIG.index_files = ['master.idx']
        for i, file in enumerate(CONFIG.index_files):

            filepath = os.path.join(CONFIG.FULL_INDEX_DIR, year, qtr, file)
            csv_filepath = filepath.replace('.idx', '.csv')

            if os.path.exists(filepath) and skip_if_exists == False:

                os.remove(filepath)

            if os.path.exists(csv_filepath) and skip_if_exists == False:

                os.remove(csv_filepath)

            if not os.path.exists(filepath):

                if not os.path.exists(os.path.dirname(filepath)):
                    os.makedirs(os.path.dirname(filepath))

                url = urljoin(CONFIG.edgar_Archives_url,'edgar/full-index/{}/{}/{}'.format(year, qtr, file))

                pending_downloads.append(DownloadTask(url=url, filepath=filepath))
            elif save_idx_as_csv and not os.path.exists(csv_filepath):
                existing_idx_to_convert.append(filepath)

    download_results = run_bounded_downloads(
        pending_downloads,
        max_workers=getattr(CONFIG, "download_workers", None),
        downloader_config=CONFIG,
    )

    if save_idx_as_csv == True:
        for filepath in existing_idx_to_convert:
            logging.info('\n\n\tConverting existing idx to csv\n\n')
            convert_idx_to_csv(filepath)
            activity_events.append({"stage": "index_refresh", "status": "success", "item": filepath, "detail": "converted_existing"})
        for result in download_results:
            if result.success:
                logging.info('\n\n\tConverting idx to csv\n\n')
                convert_idx_to_csv(result.filepath)
                activity_events.append({"stage": "index_refresh", "status": "success", "item": result.filepath, "detail": "downloaded_and_converted"})

    logging.info('\n\n\tMerging IDX files\n\n')
    merge_completed = False
    try:
        merge_idx_files()
        merge_completed = True
    except FileNotFoundError as exc:
        logging.warning(str(exc))
        activity_events.append({"stage": "index_refresh", "status": "failed", "item": CONFIG.MERGED_IDX_FILEPATH, "detail": "merge_skipped"})
    logging.info('\n\n\tCompleted Index Download\n\n\t')
    if merge_completed:
        activity_events.append({"stage": "index_refresh", "status": "success", "item": CONFIG.MERGED_IDX_FILEPATH, "detail": "merge_completed"})

    downloaded_count = int(sum(1 for result in download_results if result.success))
    failed_count = int(sum(1 for result in download_results if not result.success))
    converted_count = int(len(existing_idx_to_convert) + downloaded_count)
    return {
        "download_attempted_count": int(len(download_results)),
        "download_succeeded_count": downloaded_count,
        "download_failed_count": failed_count,
        "converted_count": converted_count,
        "merge_completed": bool(merge_completed),
        "total_elapsed_seconds": round(time.monotonic() - started_at, 3),
        "activity_events": activity_events[-200:],
    }


def download_edgar_filings_xbrl_rss_files():
    # download first xbrl file availible

    start_date = datetime.strptime("4/1/2005", "%m/%d/%Y")
    end_date = datetime.now()
    dates = [x for x in pd.date_range(start_date, end_date, freq='MS')]
    dates.reverse()
    for date in dates:
        try:
            downloader = ProxyRequest()

            basename = 'xbrlrss-' + \
                       str(date.year) + '-' + str(date.month).zfill(2) + ".xml"
            filepath = os.path.join(CONFIG.MONTHLY_DIR, basename)
            edgarFilingsFeed = parse.urljoin(
                'https://www.sec.gov/Archives/edgar/monthly/', basename)
            if not os.path.exists(filepath):
                downloader.GET_FILE(edgarFilingsFeed, filepath)
        except Exception as e:
            logging.info(e)


#######################
# MONTHLY FILINGS FEEDS (XBRL)
# http://www.sec.gov/Archives/edgar/monthly/
# "./xbrlrss-{YEAR}-{MONTH}.xml"


def generate_monthly_index_url_and_filepaths(day):
    basename = 'xbrlrss-' + str(day.year) + '-' + str(day.month).zfill(2)
    monthly_local_filepath = os.path.join(
        CONFIG.MONTHLY_DIR, basename + ".xml")
    monthly_url = urljoin(CONFIG.edgar_monthly_index, basename + ".xml")
    return monthly_url, monthly_local_filepath


def download_and_flatten_monthly_xbrl_filings_list():

    downloader = ProxyRequest()
    r = downloader.GET_RESPONSE(CONFIG.edgar_monthly_index)
    if r is None:
        logging.info("Unable to fetch monthly index page")
        return

    html = lxml.html.fromstring(r.text)
    html.make_links_absolute(CONFIG.edgar_monthly_index)
    html = lxml.html.tostring(html)
    soup = BeautifulSoup(html, 'lxml')
    urls = []
    [urls.append(link['href']) for link in soup.find_all('a', href=True)]
    urls = [i for i in urls if "xml" in i]
    urls.sort(reverse=True)

    logging.info("\n\n\n\nDownloading Edgar Monthly XML Files to:\t" + CONFIG.MONTHLY_DIR)

    if not urls:
        logging.info("No monthly XML links found")
        return

    df = pd.DataFrame(urls, columns=['URLS'])

    df.to_excel(os.path.join(CONFIG.DATA_DIR,'sec_gov_archives_edgar_monthly_xbrl_urls.xlsx'))

    for url in urls:
        filename = url.split('/')[-1:][0]

        fullfilepath = os.path.join(CONFIG.MONTHLY_DIR, filename)

        OUTPUT_FILENAME = os.path.join(os.path.dirname(
            fullfilepath), os.path.basename(fullfilepath.replace('.xml', ".xlsx")))

        try:

            if not os.path.isfile(os.path.join(CONFIG.MONTHLY_DIR, filename)) or url == urls[0]:
                logging.info("\n\n\n\nDownloading " + fullfilepath)
                downloader.GET_FILE(url, fullfilepath)
            else:
                logging.info("\n\n\n\nFound XML File " + fullfilepath)

            if not os.path.isfile(OUTPUT_FILENAME):
                logging.info("\n\n\n\nParsing XML File and Exporting to XLSX")

                feeds = read_xml_feedparser(fullfilepath)

                list_ = []

                # item = feeds.entries[0]
                for item in feeds.entries:

                    feed_dict = flattenDict(item)
                    df_ = pd.DataFrame.from_dict(feed_dict, orient='index')
                    df_.columns = ['VALUES']
                    df_.index = [ind.replace(".", "_").replace(
                        ":", "_").upper() for ind in df_.index.tolist()]
                    df_ = df_.T

                    match = df_['EDGAR_XBRLFILE_FILE'].str.replace(
                        "-.+", "").str.upper().tolist()[0]

                    if "." in match or len(match) > 13:
                        df_['TICKER'] = "--"
                    else:
                        df_['TICKER'] = match

                    list_.append(df_)

                df = pd.concat(list_)
                new_columns_names = [column_name.replace(".", "_").replace(":", "_").lower() for column_name in df.columns.tolist()]
                df.columns = new_columns_names
                df['SOURCE_FILENAME'] = os.path.basename(fullfilepath)
                df['SOURCE_IMPORT_TIMESTAMP'] = datetime.now()
                df.index = [icount for icount in range(
                    0, len(df.index.tolist()))]
                df.index.name = '_id'
                logging.info("\n\n\n\nexporting to excel {}".format(OUTPUT_FILENAME))
                df.to_excel(OUTPUT_FILENAME)
                logging.info("\n\n\n\n")
                logging.info("\n\n\n\n")
        except Exception as exc:
            logging.warning("Monthly XML flattening failed for %s: %s", fullfilepath, exc)


def parse_monthly():
    tickercheck_path = getattr(CONFIG, "tickercheck", None)
    cik_ticker_path = getattr(CONFIG, "cik_ticker", None)
    if not tickercheck_path or not cik_ticker_path:
        logging.info("Skipping parse_monthly: missing tickercheck/cik_ticker config paths")
        return

    df_tickercheck = pd.read_excel(tickercheck_path, index_col=0, header=0)
    df_cik_ticker = pd.read_excel(cik_ticker_path, header=0)

    sec_dates_months = getattr(CONFIG, "sec_dates_months", None)
    if sec_dates_months is None:
        sec_dates_months = pd.date_range(
            datetime.now() - timedelta(days=365 * 22),
            datetime.now(),
            freq="MS",
        )[::-1]

    prev_val = datetime.now()
    # i, day = list(enumerate(CONFIG.sec_dates_months))[0]
    for i, day in enumerate(sec_dates_months):

        if day.month != prev_val.month:

            monthly_url, monthly_local_filepath = generate_monthly_index_url_and_filepaths(
                day)

            _ = edgar_and_local_differ(monthly_url, monthly_local_filepath)

            if not os.path.exists(monthly_local_filepath):
                logging.info("Skipping parse_monthly: missing local monthly XML %s", monthly_local_filepath)
                continue

            feed = read_xml_feedparser(monthly_local_filepath)

            logging.info(len(feed.entries))
            for i, feed_item in enumerate(feed.entries):

                if "10-K" in feed_item["edgar_formtype"]:

                    # or ("S-1" in item["edgar_formtype"]) or ("20-F" in item["edgar_formtype"]):

                    item = flattenDict(feed_item)

                    logging.info(item)

                    try:
                        ticker = df_tickercheck[df_tickercheck['EDGAR_CIKNUMBER'].isin(
                            [item['edgar_ciknumber'].lstrip("0")])]
                        symbol = ticker['SYMBOL'].tolist()[0]
                    except:
                        try:
                            logging.info('searching backup')
                            ticker = df_cik_ticker[df_cik_ticker['CIK'].isin(
                                [item['edgar_ciknumber'].lstrip("0")])]['Ticker'].tolist()[0]
                        except:
                            ticker = "TICKER"

                    logging.info(item)
                    basename = os.path.basename(
                        monthly_local_filepath).replace(".xml", "")

                    month_dir = os.path.join(CONFIG.FILING_DIR, str(
                        day.year), '{:02d}'.format(day.month))

                    if not os.path.exists(month_dir):
                        os.makedirs(month_dir)
                    if ticker != "TICKER":

                        filepath = edgar_filing_idx_create_filename(basename, item, ticker)

                        if not os.path.exists(filepath):

                            downloader = ProxyRequest()
                            downloader.GET_RESPONSE(CONFIG.edgar_monthly_index)

                            # consume_complete_submission_filing.delay(basename, item, ticker)
                        else:
                            logging.info('found file {}'.format(filepath))
                    else:
                        # consume_complete_submission_filing.delay(basename, item, ticker)
                        logging.info('yes')


def cik_column_to_list(df):

    df_cik_tickers = df.dropna(subset=['CIK'])

    df_cik_tickers['CIK'] = df_cik_tickers['CIK'].astype(int)

    return df_cik_tickers['CIK'].tolist()
