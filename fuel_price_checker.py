#!/usr/bin/env python3
"""
Fuel Price Checker for UK Retailers
Fetches and displays current fuel prices from various UK fuel retailers.
"""

import concurrent.futures
import json
from datetime import datetime
from typing import Dict, List, Optional

import requests


class FuelPriceChecker:
    """Checks fuel prices from multiple UK retailers."""

    with open("retailers.json", "r") as f:
        RETAILERS = json.load(f)

    def __init__(self, timeout: int = 10):
        """
        Initialize the fuel price checker.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) " "AppleWebKit/537.36")}
        )

    def fetch_prices(self, retailer: str, url: str) -> Dict:
        """
        Fetch fuel prices from a single retailer.

        Args:
            retailer: Name of the retailer
            url: URL to fetch prices from

        Returns:
            Dictionary containing retailer info and prices or error
        """
        try:
            # Shell URL ends in .html but returns JSON
            headers = {}
            if retailer == "Shell":
                headers = {"Accept": "application/json"}

            response = self.session.get(url, timeout=self.timeout, headers=headers)
            response.raise_for_status()

            data = response.json()
            return {
                "retailer": retailer,
                "status": "success",
                "data": data,
                "url": url,
            }

        except requests.exceptions.Timeout:
            return {
                "retailer": retailer,
                "status": "error",
                "error": "Request timeout",
                "url": url,
            }
        except requests.exceptions.RequestException as e:
            return {
                "retailer": retailer,
                "status": "error",
                "error": str(e),
                "url": url,
            }
        except json.JSONDecodeError:
            return {
                "retailer": retailer,
                "status": "error",
                "error": "Invalid JSON response",
                "url": url,
            }

    def fetch_all_prices(self, max_workers: int = 5) -> List[Dict]:
        """
        Fetch prices from all retailers concurrently.

        Args:
            max_workers: Maximum number of concurrent requests

        Returns:
            List of dictionaries containing results from each retailer
        """
        results = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_retailer = {
                executor.submit(self.fetch_prices, retailer, url): retailer
                for retailer, url in self.RETAILERS.items()
            }

            for future in concurrent.futures.as_completed(future_to_retailer):
                results.append(future.result())

        return results

    def extract_station_info(self, result: Dict) -> Optional[Dict]:
        """
        Extract basic station information from a result.

        Args:
            result: Result dictionary from fetch_prices

        Returns:
            Dictionary with extracted info or None
        """
        if result["status"] != "success":
            return None

        data = result["data"]
        retailer = result["retailer"]

        # Handle different JSON structures
        stations = []

        # Most retailers use "stations" key
        if isinstance(data, dict) and "stations" in data:
            stations = data["stations"]
        elif isinstance(data, list):
            stations = data
        elif isinstance(data, dict):
            # Some might have different structures
            stations = [data]

        return {
            "retailer": retailer,
            "station_count": (len(stations) if isinstance(stations, list) else 0),
            "sample_data": (
                stations[0] if stations and isinstance(stations, list) else data
            ),
        }

    def print_summary(self, results: List[Dict]):
        """
        Print a summary of the fetched prices.

        Args:
            results: List of result dictionaries
        """
        print(f"\n{'='*80}")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"Fuel Price Check Summary - {timestamp}")
        print(f"{'='*80}\n")

        successful = [r for r in results if r["status"] == "success"]
        errors = [r for r in results if r["status"] == "error"]
        html_format = [r for r in results if r["status"] == "html_format"]

        print(f"✓ Successful: {len(successful)}/{len(results)}")
        print(f"✗ Errors: {len(errors)}/{len(results)}")
        print(f"⚠ Special Format: {len(html_format)}/{len(results)}")
        print()

        if successful:
            print(f"\n{'-'*80}")
            print("SUCCESSFUL FETCHES:")
            print(f"{'-'*80}")
            for result in sorted(successful, key=lambda x: x["retailer"]):
                info = self.extract_station_info(result)
                if info:
                    print(f"\n{result['retailer']}:")
                    print(f"  Stations: {info['station_count']}")
                    print(f"  URL: {result['url']}")

        if html_format:
            print(f"\n{'-'*80}")
            print("SPECIAL FORMAT (Needs Manual Handling):")
            print(f"{'-'*80}")
            for result in html_format:
                print(f"\n{result['retailer']}:")
                print(f"  {result['message']}")
                print(f"  URL: {result['url']}")

        if errors:
            print(f"\n{'-'*80}")
            print("ERRORS:")
            print(f"{'-'*80}")
            for result in sorted(errors, key=lambda x: x["retailer"]):
                print(f"\n{result['retailer']}:")
                print(f"  Error: {result['error']}")
                print(f"  URL: {result['url']}")

        print(f"\n{'='*80}\n")

    def save_results(
        self, results: List[Dict], filename: str = "./.data/fuel_prices.json"
    ):
        """
        Save results to a JSON file.

        Args:
            results: List of result dictionaries
            filename: Output filename
        """
        output = {
            "timestamp": datetime.now().isoformat(),
            "results": results,
        }

        with open(filename, "w") as f:
            json.dump(output, f, indent=2)

        print(f"Results saved to {filename}")


def main():
    """Main entry point for the fuel price checker."""
    print("Starting Fuel Price Checker...")

    checker = FuelPriceChecker()
    results = checker.fetch_all_prices()

    checker.print_summary(results)
    checker.save_results(results)


if __name__ == "__main__":
    main()
