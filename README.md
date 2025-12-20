# fill-er-up
Fuel price comparison site

## Overview

A Python-based fuel price checker that fetches current fuel prices from 14 major UK retailers including Tesco, Sainsbury's, Asda, Morrisons, BP, Shell, and more.

## Features

- ✅ Concurrent API requests for fast data retrieval
- ✅ Supports 14 UK fuel retailers
- ✅ JSON export of results
- ✅ Error handling and timeout management
- ✅ Summary reporting with station counts

## Supported Retailers

- Ascona Group
- Asda
- bp
- Esso Tesco Alliance
- JET Retail UK
- Karan Retail Ltd
- Morrisons
- Moto
- Motor Fuel Group
- Rontec
- Sainsbury's
- SGN
- Shell (HTML format - requires special handling)
- Tesco

## Installation

1. Clone the repository:
```bash
git clone https://github.com/KRoperUK/fill-er-up.git
cd fill-er-up
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Run the fuel price checker:
```bash
python fuel_price_checker.py
```

The script will:
1. Fetch prices from all retailers concurrently
2. Display a summary showing successful fetches and errors
3. Save results to `fuel_prices.json`

### Example Output

```
================================================================================
Fuel Price Check Summary - 2025-12-20 14:30:45
================================================================================

✓ Successful: 12/14
✗ Errors: 1/14
⚠ Special Format: 1/14

--------------------------------------------------------------------------------
SUCCESSFUL FETCHES:
--------------------------------------------------------------------------------

Tesco:
  Stations: 542
  URL: https://www.tesco.com/fuel_prices/fuel_prices_data.json
...
```

## Output Format

Results are saved to `fuel_prices.json` with the following structure:
```json
{
  "timestamp": "2025-12-20T14:30:45.123456",
  "results": [
    {
      "retailer": "Tesco",
      "status": "success",
      "data": { ... },
      "url": "https://..."
    }
  ]
}
```

## Configuration

Edit the `FuelPriceChecker` class in [fuel_price_checker.py](fuel_price_checker.py) to:
- Adjust timeout (default: 10 seconds)
- Modify concurrent workers (default: 5)
- Add/remove retailers

## License

MIT License
