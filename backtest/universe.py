#!/usr/bin/env python3
"""
Universe expansion for RBI Filter Sensitivity Analysis.
Scrapes index constituents, filters by beta and volume.

Usage:
    python universe.py                    # Build full universe
    python universe.py --skip-beta        # Skip IBKR beta filtering (use cached)
    python universe.py --debug            # Process only 10 symbols for testing
"""

import os
import re
import json
import time
import argparse
from typing import List, Dict, Set, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import IBKR_HOST, IBKR_PORT

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

# Output files
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
SYMBOLS_FILE = os.path.join(DATA_DIR, 'symbols.json')
HIGH_BETA_FILE = os.path.join(DATA_DIR, 'high_beta_symbols.json')

# Universe criteria
MIN_BETA = 1.5
MIN_AVG_VOLUME = 500_000

# Headers to avoid Wikipedia 403
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def scrape_sp500() -> List[str]:
    """Scrape S&P 500 constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    print(f"  Fetching S&P 500 from {url}...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the first table (current constituents)
        table = soup.find('table', {'id': 'constituents'})
        if not table:
            table = soup.find('table', {'class': 'wikitable'})

        symbols = []
        if table:
            rows = table.find_all('tr')[1:]  # Skip header
            for row in rows:
                cols = row.find_all('td')
                if cols:
                    symbol = cols[0].text.strip()
                    # Clean symbol (some have notes like BRK.B)
                    symbol = symbol.replace('.', '-')  # IBKR uses - not .
                    if symbol and symbol.isalpha() or '-' in symbol:
                        symbols.append(symbol)

        print(f"    Found {len(symbols)} S&P 500 symbols")
        return symbols
    except Exception as e:
        print(f"    ERROR scraping S&P 500: {e}")
        return []


def scrape_sp400() -> List[str]:
    """Scrape S&P 400 (MidCap) constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
    print(f"  Fetching S&P 400 from {url}...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        table = soup.find('table', {'class': 'wikitable'})

        symbols = []
        if table:
            rows = table.find_all('tr')[1:]
            for row in rows:
                cols = row.find_all('td')
                if cols:
                    symbol = cols[0].text.strip()
                    symbol = symbol.replace('.', '-')
                    if symbol:
                        symbols.append(symbol)

        print(f"    Found {len(symbols)} S&P 400 symbols")
        return symbols
    except Exception as e:
        print(f"    ERROR scraping S&P 400: {e}")
        return []


def scrape_sp600() -> List[str]:
    """Scrape S&P 600 (SmallCap) constituents from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
    print(f"  Fetching S&P 600 from {url}...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        table = soup.find('table', {'class': 'wikitable'})

        symbols = []
        if table:
            rows = table.find_all('tr')[1:]
            for row in rows:
                cols = row.find_all('td')
                if cols:
                    symbol = cols[0].text.strip()
                    symbol = symbol.replace('.', '-')
                    if symbol:
                        symbols.append(symbol)

        print(f"    Found {len(symbols)} S&P 600 symbols")
        return symbols
    except Exception as e:
        print(f"    ERROR scraping S&P 600: {e}")
        return []


def scrape_russell2000() -> List[str]:
    """
    Get Russell 2000 constituents.
    Wikipedia doesn't have a complete list, so we use a fallback approach:
    - Try Wikipedia first (partial list)
    - Fall back to a static file if available
    """
    print("  Fetching Russell 2000...")

    # Try Wikipedia Russell 2000 Growth as proxy
    url = "https://en.wikipedia.org/wiki/Russell_2000_Index"
    try:
        response = requests.get(url, timeout=30)
        # Russell 2000 doesn't have a constituents table on Wikipedia
        # We'll use a placeholder and note this limitation
        print("    Wikipedia doesn't have full Russell 2000 list")
        print("    Using S&P indices only (1500 symbols)")
        return []
    except Exception as e:
        print(f"    ERROR: {e}")
        return []


def deduplicate_symbols(all_symbols: Dict[str, List[str]]) -> List[str]:
    """Deduplicate symbols across all indices."""
    seen = set()
    unique = []

    # Process in order: S&P 500 first (larger caps)
    for index in ['sp500', 'sp400', 'sp600', 'russell2000']:
        for symbol in all_symbols.get(index, []):
            if symbol not in seen and symbol:
                seen.add(symbol)
                unique.append(symbol)

    return sorted(unique)


def get_beta_volume_ibkr(symbols: List[str], max_workers: int = 4) -> Dict[str, Dict]:
    """
    Get beta and volume data from IBKR for symbols.
    Uses reqMktData for volume and reqFundamentalData for beta.

    Returns: {symbol: {'beta': float, 'avg_volume': int, 'error': str or None}}
    """
    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("ERROR: ib_insync not installed. Run: pip install ib_insync")
        return {}

    ib = IB()
    results = {}

    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=199)  # Use different clientId
        print(f"Connected to IBKR at {IBKR_HOST}:{IBKR_PORT}")

        for i, symbol in enumerate(symbols):
            print(f"  [{i+1}/{len(symbols)}] {symbol}...", end='', flush=True)

            try:
                contract = Stock(symbol, 'SMART', 'USD')
                ib.qualifyContracts(contract)

                # Get fundamental data (includes beta)
                # Note: reqFundamentalData requires market data subscription
                # Alternative: use contract details for basic info
                details = ib.reqContractDetails(contract)

                beta = None
                avg_volume = None

                if details:
                    # Contract details don't include beta directly
                    # We'd need Fundamental Data subscription for that
                    # For now, we'll use a placeholder approach

                    # Get recent volume from historical data (last 20 days)
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime='',
                        durationStr='20 D',
                        barSizeSetting='1 day',
                        whatToShow='TRADES',
                        useRTH=True
                    )

                    if bars:
                        volumes = [b.volume for b in bars]
                        avg_volume = int(sum(volumes) / len(volumes)) if volumes else None

                results[symbol] = {
                    'beta': beta,  # Will need fundamental data subscription
                    'avg_volume': avg_volume,
                    'error': None
                }

                print(f" vol={avg_volume or 'N/A'}")
                time.sleep(0.5)  # Rate limiting

            except Exception as e:
                results[symbol] = {
                    'beta': None,
                    'avg_volume': None,
                    'error': str(e)
                }
                print(f" ERROR: {e}")

    except Exception as e:
        print(f"IBKR connection error: {e}")
    finally:
        if ib.isConnected():
            ib.disconnect()

    return results


def filter_by_volume(symbols: List[str], fundamentals: Dict[str, Dict]) -> List[str]:
    """Filter symbols by minimum average volume."""
    filtered = []

    for symbol in symbols:
        data = fundamentals.get(symbol, {})
        avg_vol = data.get('avg_volume')

        if avg_vol is None:
            # Include symbols where we couldn't get volume (don't exclude)
            filtered.append(symbol)
        elif avg_vol >= MIN_AVG_VOLUME:
            filtered.append(symbol)

    return filtered


def filter_etfs(symbols: List[str]) -> List[str]:
    """
    Filter out ETFs from symbol list.
    Uses common ETF patterns and known ETF lists.
    """
    # Common ETF suffixes and patterns
    etf_patterns = [
        r'^[A-Z]{3,4}X$',  # Ends in X (many ETFs)
        r'^SPY$', r'^QQQ$', r'^IWM$', r'^DIA$',  # Major ETFs
        r'^XL[A-Z]$',  # Sector SPDRs
        r'^V[A-Z]{2}$',  # Vanguard ETFs
        r'^IY[A-Z]$',  # iShares
    ]

    # Known major ETFs to exclude
    known_etfs = {
        'SPY', 'QQQ', 'IWM', 'DIA', 'VTI', 'VOO', 'VXX', 'UVXY',
        'TQQQ', 'SQQQ', 'SPXL', 'SPXS', 'TNA', 'TZA',
        'XLF', 'XLK', 'XLE', 'XLV', 'XLI', 'XLY', 'XLP', 'XLU', 'XLB',
        'GLD', 'SLV', 'USO', 'UNG',
        'HYG', 'LQD', 'TLT', 'IEF', 'SHY',
        'EEM', 'EFA', 'VWO', 'VEA',
        'ARKK', 'ARKG', 'ARKW', 'ARKF', 'ARKQ',
    }

    filtered = []
    for symbol in symbols:
        if symbol in known_etfs:
            continue

        is_etf = False
        for pattern in etf_patterns:
            if re.match(pattern, symbol):
                is_etf = True
                break

        if not is_etf:
            filtered.append(symbol)

    return filtered


def get_beta_yfinance(symbols: List[str], max_workers: int = 10) -> Dict[str, Dict]:
    """
    Get beta and volume data from Yahoo Finance for symbols.

    Returns: {symbol: {'beta': float, 'avg_volume': int, 'error': str or None}}
    """
    if not YFINANCE_AVAILABLE:
        print("ERROR: yfinance not installed. Run: pip install yfinance")
        return {}

    results = {}
    total = len(symbols)

    def fetch_single(symbol: str) -> Tuple[str, Dict]:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            beta = info.get('beta')
            avg_volume = info.get('averageVolume')

            return symbol, {
                'beta': beta,
                'avg_volume': avg_volume,
                'error': None
            }
        except Exception as e:
            return symbol, {
                'beta': None,
                'avg_volume': None,
                'error': str(e)
            }

    print(f"  Fetching beta/volume for {total} symbols from Yahoo Finance...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single, sym): sym for sym in symbols}

        for i, future in enumerate(as_completed(futures)):
            symbol, data = future.result()
            results[symbol] = data

            if (i + 1) % 50 == 0 or (i + 1) == total:
                print(f"    [{i+1}/{total}] processed...")

    # Summary
    with_beta = sum(1 for d in results.values() if d.get('beta') is not None)
    high_beta = sum(1 for d in results.values() if d.get('beta') is not None and d['beta'] >= MIN_BETA)
    print(f"  Found beta for {with_beta}/{total} symbols, {high_beta} with beta >= {MIN_BETA}")

    return results


def filter_by_beta(symbols: List[str], fundamentals: Dict[str, Dict]) -> List[str]:
    """Filter symbols by minimum beta."""
    filtered = []

    for symbol in symbols:
        data = fundamentals.get(symbol, {})
        beta = data.get('beta')

        if beta is not None and beta >= MIN_BETA:
            filtered.append(symbol)

    return filtered


def build_universe(skip_beta: bool = False, skip_volume: bool = False, debug: bool = False) -> Tuple[List[str], Dict]:
    """
    Build the high-beta stock universe.

    Returns:
        (filtered_symbols, metadata)
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 60)
    print("BUILDING STOCK UNIVERSE")
    print("=" * 60)

    # Step 1: Scrape index constituents
    print("\n1. Scraping index constituents...")
    all_symbols = {
        'sp500': scrape_sp500(),
        'sp400': scrape_sp400(),
        'sp600': scrape_sp600(),
        'russell2000': scrape_russell2000(),
    }

    # Step 2: Deduplicate
    print("\n2. Deduplicating symbols...")
    unique_symbols = deduplicate_symbols(all_symbols)
    print(f"   {len(unique_symbols)} unique symbols after deduplication")

    # Save raw symbols
    with open(SYMBOLS_FILE, 'w') as f:
        json.dump({
            'raw_counts': {k: len(v) for k, v in all_symbols.items()},
            'unique_count': len(unique_symbols),
            'symbols': unique_symbols
        }, f, indent=2)
    print(f"   Saved to {SYMBOLS_FILE}")

    # Step 3: Filter ETFs
    print("\n3. Filtering ETFs...")
    non_etf_symbols = filter_etfs(unique_symbols)
    print(f"   {len(non_etf_symbols)} symbols after ETF filter")

    # Debug mode: limit to 10 symbols
    if debug:
        non_etf_symbols = non_etf_symbols[:10]
        print(f"   DEBUG MODE: Limited to {len(non_etf_symbols)} symbols")

    # Step 4: Get fundamentals from Yahoo Finance (beta, volume)
    if not skip_beta:
        print("\n4. Fetching beta/volume from Yahoo Finance...")
        fundamentals = get_beta_yfinance(non_etf_symbols)

        # Step 5: Filter by beta
        print("\n5. Filtering by beta...")
        beta_filtered = filter_by_beta(non_etf_symbols, fundamentals)
        print(f"   {len(beta_filtered)} symbols with beta >= {MIN_BETA}")

        # Step 6: Filter by volume (optional)
        if not skip_volume:
            print("\n6. Filtering by volume...")
            filtered_symbols = filter_by_volume(beta_filtered, fundamentals)
            print(f"   {len(filtered_symbols)} symbols with volume >= {MIN_AVG_VOLUME:,}")
        else:
            print("\n6. Skipping volume filter (--skip-volume)")
            filtered_symbols = beta_filtered
    else:
        print("\n4-6. Skipping beta/volume filtering (--skip-beta)")
        filtered_symbols = non_etf_symbols
        beta_filtered = non_etf_symbols
        fundamentals = {}

    # Build metadata
    beta_filtered_count = len(beta_filtered)
    metadata = {
        'criteria': {
            'min_beta': MIN_BETA,
            'min_avg_volume': MIN_AVG_VOLUME,
        },
        'counts': {
            'sp500': len(all_symbols['sp500']),
            'sp400': len(all_symbols['sp400']),
            'sp600': len(all_symbols['sp600']),
            'russell2000': len(all_symbols['russell2000']),
            'unique': len(unique_symbols),
            'after_etf_filter': len(non_etf_symbols),
            'after_beta_filter': beta_filtered_count,
            'final': len(filtered_symbols),
        },
        'symbols': filtered_symbols,
        'data_source': 'Yahoo Finance (yfinance)',
        'note': f'Filtered by beta >= {MIN_BETA} and avg volume >= {MIN_AVG_VOLUME:,}'
    }

    # Save filtered symbols
    with open(HIGH_BETA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)
    print(f"\n7. Saved {len(filtered_symbols)} symbols to {HIGH_BETA_FILE}")

    # Summary
    print("\n" + "=" * 60)
    print("UNIVERSE SUMMARY")
    print("=" * 60)
    print(f"  S&P 500:       {len(all_symbols['sp500']):>5} symbols")
    print(f"  S&P 400:       {len(all_symbols['sp400']):>5} symbols")
    print(f"  S&P 600:       {len(all_symbols['sp600']):>5} symbols")
    print(f"  Russell 2000:  {len(all_symbols['russell2000']):>5} symbols (not available)")
    print(f"  -----------------------")
    print(f"  Unique:        {len(unique_symbols):>5} symbols")
    print(f"  After ETF:     {len(non_etf_symbols):>5} symbols")
    print(f"  After Beta:    {beta_filtered_count:>5} symbols (beta >= {MIN_BETA})")
    print(f"  After Volume:  {len(filtered_symbols):>5} symbols (vol >= {MIN_AVG_VOLUME:,})")
    print("=" * 60)

    return filtered_symbols, metadata


def load_universe() -> List[str]:
    """Load previously built universe from file."""
    if os.path.exists(HIGH_BETA_FILE):
        with open(HIGH_BETA_FILE, 'r') as f:
            data = json.load(f)
            return data.get('symbols', [])
    return []


def main():
    parser = argparse.ArgumentParser(description='Build RBI stock universe')
    parser.add_argument('--skip-beta', action='store_true',
                       help='Skip beta filtering')
    parser.add_argument('--skip-volume', action='store_true',
                       help='Skip volume filtering (use all symbols with beta >= 1.5)')
    parser.add_argument('--debug', action='store_true',
                       help='Debug mode: process only 10 symbols')
    args = parser.parse_args()

    symbols, metadata = build_universe(
        skip_beta=args.skip_beta,
        skip_volume=args.skip_volume,
        debug=args.debug
    )

    print(f"\nReady for Phase 2: Parallel data fetching")
    print(f"Run: python parallel_fetch.py --symbols-file {HIGH_BETA_FILE}")


if __name__ == '__main__':
    main()
