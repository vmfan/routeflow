import argparse
import sys
import requests
from .explainability import explain
from .formatter import format_route_report


def _parse_error_response(response: requests.Response) -> dict:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"detail": str(data)}
    except Exception:
        text = response.text.strip()
        return {"detail": text or f"HTTP {response.status_code}"}

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RouteFlow command-line client")
    parser.add_argument("--symbol", required=True, help="Trading pair, e.g. ETHUSDT")
    parser.add_argument("--side", required=True, choices=["buy", "sell"], help="Trade side")
    parser.add_argument("--size", required=True, type=float, help="Trade size in base asset")
    parser.add_argument(
        "--enable-split",
        action="store_true",
        help="Enable split optimization across venues",
    )
    parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:8000/api/route",
        help="RouteFlow API endpoint",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    payload = {
        "symbol": args.symbol,
        "side": args.side,
        "size": args.size,
        "enable_split": args.enable_split,
    }

    try:
        response = requests.post(args.api_url, json=payload, timeout=10)
    except requests.RequestException as exc:
        print(f"ERROR: could not reach API: {exc}", file=sys.stderr)
        return 1

    if response.status_code == 503:
        error = _parse_error_response(response)
        print(
            (
                f"STALE DATA: {error.get('symbol', args.symbol)} on "
                f"{error.get('source', 'unknown source')} is too old to trust "
                f"(age={error.get('age_ms', 'n/a')}ms, "
                f"limit={error.get('max_age_ms', 'n/a')}ms)."
            ),
            file=sys.stderr,
        )
        return 1

    try:
        response.raise_for_status()
    except requests.HTTPError:
        error = _parse_error_response(response)
        print(f"ERROR: {error.get('detail', 'request failed')}", file=sys.stderr)
        return 1

    data = response.json()
    split_data = data.get("split")
    explanation = explain(data.get("best_route", {}), split_data)
    print(format_route_report(data, explanation))
    return 0


if __name__ == "__main__":
    sys.exit(main())