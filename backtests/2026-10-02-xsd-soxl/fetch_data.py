"""Download a new frozen snapshot. Existing files are kept unless --overwrite."""
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", default="2026-10-01", help="Last complete US session, YYYY-MM-DD")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / "data"
    root.mkdir(exist_ok=True)
    through = date.fromisoformat(args.through)
    end = datetime.combine(through + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    p1 = int(datetime(2008, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(end.timestamp())
    def fetch(symbol):
        target = root / f"{symbol}.json"
        if target.exists() and not args.overwrite:
            return {"ticker": symbol, "status": "existing snapshot retained"}
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}"
               f"&period2={p2}&interval=1d&events=div%2Csplits&includeAdjustedClose=true")
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=45) as response:
            payload = json.load(response)
        if payload["chart"].get("error") or not payload["chart"].get("result"):
            raise ValueError(f"Failed {symbol}: {payload['chart'].get('error')}")
        target.write_text(json.dumps(payload), encoding="utf-8")
        return {"ticker": symbol, "url": url, "download_utc": datetime.now(timezone.utc).isoformat()}
    with ThreadPoolExecutor(max_workers=3) as pool:
        manifest = list(pool.map(fetch, ("QQQ", "XSD", "SOXL")))
    if any("url" in x for x in manifest):
        (root / "downloads.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
