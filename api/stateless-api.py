import gzip
import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request

app = Flask(__name__)


DATA_PATH: str = os.environ.get(
    "FULL_TO_BRIM_PATH",
    ".data/fuel_prices.json",
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute Haversine distance between two points in kilometers."""
    R = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def load_locations() -> List[Dict[str, Any]]:
    """Load station/location entries from the configured JSON file.

    Supports:
        - Aggregated format:
            {"timestamp": ..., "results": [
                    {"retailer": ..., "status": ..., "data": {"stations": [...]}}
            ]}
        - Simple list of stations
        - Dict with a list under: "stations", "locations", "data", "results"
    """
    try:
        with open(DATA_PATH, "rb") as f:
            raw_bytes = f.read()

        app.logger.info(
            f"Loaded {len(raw_bytes)} bytes from {DATA_PATH}, "
            f"first 4 bytes: {raw_bytes[:4].hex()}"
        )

        # Check for gzip magic number (0x1f8b)
        if len(raw_bytes) >= 2 and raw_bytes[0] == 0x1F and raw_bytes[1] == 0x8B:
            try:
                decompressed = gzip.decompress(raw_bytes)
                data = json.loads(decompressed.decode("utf-8"))
                app.logger.info(f"Successfully decompressed gzip from {DATA_PATH}")
                return _parse_locations(data)
            except Exception as e:
                app.logger.error(f"Gzip decompression failed: {type(e).__name__} - {e}")
                raise

        # Not gzip, try plain text with multiple encodings
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"]
        data = None
        last_error = None

        for encoding in encodings:
            try:
                text = raw_bytes.decode(encoding)
                data = json.loads(text)
                app.logger.info(f"Loaded plain JSON from {DATA_PATH} with {encoding}")
                return _parse_locations(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                last_error = e
                app.logger.debug(
                    f"Failed to decode with {encoding}: {type(e).__name__}"
                )
                continue

        app.logger.error(
            f"Could not decode {DATA_PATH} with any encoding. "
            f"Last error: {last_error}"
        )
        return []

    except FileNotFoundError as e:
        app.logger.error(f"Data file not found: {DATA_PATH} - {e}")
        return []
    except Exception as e:
        app.logger.error(f"Error loading {DATA_PATH}: {type(e).__name__} - {e}")
        return []


def _parse_locations(data: Any) -> List[Dict[str, Any]]:
    """Parse JSON data into list of location dicts."""

    # Aggregator case: top-level dict with "results" list of retailer payloads
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        stations: List[Dict[str, Any]] = []
        for entry in data["results"]:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") != "success":
                continue
            retailer_name = entry.get("retailer")
            payload = entry.get("data")
            if not isinstance(payload, dict):
                continue
            sub_list = None
            for key in ("stations", "stores", "locations"):
                v = payload.get(key)
                if isinstance(v, list):
                    sub_list = v
                    break
            if isinstance(sub_list, list):
                for s in sub_list:
                    if isinstance(s, dict):
                        # Attach retailer context if not present
                        if retailer_name and "retailer" not in s:
                            s["retailer"] = retailer_name
                        stations.append(s)
        return stations

    # Simple list of stations at top-level
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    # Dict with known list containers
    if isinstance(data, dict):
        for key in ("stations", "stores", "locations", "data", "results"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        # Fallback single record
        return [data]

    return []


def _get_from_many(d: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def extract_lat_lon(obj: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Attempt to extract lat/lon from common field names or nested objects."""
    # Direct fields
    lat = _get_from_many(obj, ["lat", "latitude", "Lat", "Latitude"])
    lon = _get_from_many(obj, ["lon", "lng", "longitude", "Long", "Longitude"])

    # Nested location fields
    if lat is None or lon is None:
        for loc_key in ("location", "coords", "geo", "position", "geoPoint"):
            nested = obj.get(loc_key)
            if isinstance(nested, dict):
                lat = (
                    lat
                    if lat is not None
                    else _get_from_many(nested, ["lat", "latitude", "Lat", "Latitude"])
                )
                lon = (
                    lon
                    if lon is not None
                    else _get_from_many(
                        nested, ["lon", "lng", "longitude", "Long", "Longitude"]
                    )
                )

    # Coordinates under other keys
    if lat is None or lon is None:
        coords = obj.get("coordinates") or obj.get("coord")
        if isinstance(coords, dict):
            lat = (
                lat if lat is not None else _get_from_many(coords, ["lat", "latitude"])
            )
            lon = (
                lon
                if lon is not None
                else _get_from_many(coords, ["lon", "lng", "longitude"])
            )
        elif isinstance(coords, (list, tuple)) and len(coords) == 2:
            # Try both orders: [lat, lon] or [lon, lat]
            try:
                a, b = float(coords[0]), float(coords[1])
                # If both within valid ranges, prefer [lat, lon]
                if -90 <= a <= 90 and -180 <= b <= 180:
                    lat = lat if lat is not None else a
                    lon = lon if lon is not None else b
                elif -90 <= b <= 90 and -180 <= a <= 180:
                    lat = lat if lat is not None else b
                    lon = lon if lon is not None else a
            except (TypeError, ValueError):
                pass

    # String form "lat,lon"
    if (lat is None or lon is None) and isinstance(obj.get("latlng"), str):
        try:
            parts = [p.strip() for p in obj["latlng"].split(",")]
            if len(parts) == 2:
                lat = lat if lat is not None else float(parts[0])
                lon = lon if lon is not None else float(parts[1])
        except (ValueError, TypeError):
            pass

    try:
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def normalize_key(s: str) -> str:
    return s.strip().lower().replace(" ", "_")


def extract_price(obj: Dict[str, Any], fuel: Optional[str]) -> Optional[float]:
    """Extract a price for the requested fuel, or the cheapest available.

    Looks through common fields: "price", "ppl", "price_per_litre", or nested
    dicts like "prices" / "fuels". Falls back to minimum numeric value found.
    """
    # Normalized fuel label used across different container shapes
    fuel_norm: Optional[str] = normalize_key(fuel) if fuel else None
    # Direct price fields
    for key in ("price", "ppl", "price_per_litre", "fuel_price"):
        val = obj.get(key)
        try:
            if val is not None:
                return float(val)
        except (TypeError, ValueError):
            pass

    # Nested dicts of prices
    for container_key in ("prices", "fuels", "fuel_prices", "price_list"):
        container = obj.get(container_key)
        if isinstance(container, dict):
            if fuel_norm:
                # Try exact and normalized matches against container keys
                for k, v in container.items():
                    try:
                        if normalize_key(k) == fuel_norm:
                            return float(v)
                    except (TypeError, ValueError):
                        continue
            # Otherwise pick the minimum numeric price
            numeric_vals: List[float] = []
            for v in container.values():
                if v is None:
                    continue
                try:
                    numeric_vals.append(float(v))
                except (TypeError, ValueError):
                    continue
            if numeric_vals:
                return min(numeric_vals)

        # Containers provided as list of dicts
        # Example: [{"label": "E10", "price": 141.9}, ...]
        if isinstance(container, list):
            best: Optional[float] = None

            def _match_label(d: Dict[str, Any]) -> bool:
                if not fuel_norm:
                    return False
                for key in ("label", "name", "type", "fuel", "grade", "key"):
                    val = d.get(key)
                    if isinstance(val, str) and normalize_key(val) == fuel_norm:
                        return True
                return False

            # Try to match requested fuel first
            if fuel_norm:
                for item in container:
                    if not isinstance(item, dict):
                        continue
                    if _match_label(item):
                        try:
                            val = next(
                                (
                                    item.get(k)
                                    for k in ("price", "ppl", "value")
                                    if item.get(k) is not None
                                ),
                                None,
                            )
                            if val is not None:
                                return float(val)
                        except (TypeError, ValueError):
                            continue

            # Otherwise take minimum available numeric value
            for item in container:
                if not isinstance(item, dict):
                    continue
                for key in ("price", "ppl", "value"):
                    try:
                        val = item.get(key)
                        if val is not None:
                            v = float(val)
                            best = v if best is None or v < best else best
                            break
                    except (TypeError, ValueError):
                        continue
            if best is not None:
                return best

    # Fuel synonyms mapping (e.g., "unleaded" -> "e10", "ul") in other fields
    if fuel_norm:
        synonyms = {
            "unleaded": {"e10", "ul", "unleaded", "petrol"},
            "super_unleaded": {"e5", "super", "super_unleaded"},
            "diesel": {"b7", "d", "diesel"},
            "premium_diesel": {"premium_diesel", "super_diesel"},
        }
        # Scan dict for matching synonyms
        for key, val in obj.items():
            if not isinstance(val, (int, float)):
                continue
            k_norm = normalize_key(key)
            for target, names in synonyms.items():
                if fuel_norm == target and k_norm in names:
                    return float(val)

    # Scan any nested lists or dicts for numeric price-like values
    for key, val in obj.items():
        if isinstance(val, (int, float)) and key.lower() in {"ppl", "price"}:
            return float(val)

    return None


def extract_basic_info(obj: Dict[str, Any]) -> Dict[str, Any]:
    name = _get_from_many(obj, ["name", "station", "site_name", "retailer"]) or ""
    brand = _get_from_many(obj, ["brand", "retailer", "company"]) or ""
    address = _get_from_many(
        obj,
        [
            "address",
            "addr",
            "street_address",
            "location_name",
            "postcode",
            "postal_code",
        ],
    )
    return {"name": name, "brand": brand, "address": address}


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/debug/file-info")
def debug_file_info():
    """Dump file info to logs for debugging."""
    try:
        with open(DATA_PATH, "rb") as f:
            raw_bytes = f.read()

        app.logger.info(
            f"File: {DATA_PATH}, Size: {len(raw_bytes)} bytes, "
            f"First 100 bytes (hex): {raw_bytes[:100].hex()}, "
            f"First 100 bytes (repr): {repr(raw_bytes[:100])}"
        )

        # Try to parse as gzip
        is_gzip = len(raw_bytes) >= 2 and raw_bytes[0] == 0x1F and raw_bytes[1] == 0x8B
        app.logger.info(f"Is gzip: {is_gzip}")

        if is_gzip:
            try:
                decompressed = gzip.decompress(raw_bytes)
                app.logger.info(f"Gzip decompressed size: {len(decompressed)} bytes")
                # Try to parse as JSON
                try:
                    _ = json.loads(decompressed.decode("utf-8"))
                    app.logger.info("Successfully parsed as JSON after gzip")
                except Exception as e:
                    app.logger.error(f"JSON parse failed: {e}")
            except Exception as e:
                app.logger.error(f"Gzip decompression failed: {e}")

        return jsonify(
            {
                "file": DATA_PATH,
                "size": len(raw_bytes),
                "is_gzip": is_gzip,
                "first_4_bytes_hex": raw_bytes[:4].hex(),
                "status": "Check logs for full dump",
            }
        )
    except Exception as e:
        app.logger.error(f"Debug error: {e}")
        return jsonify({"error": str(e)}), 500


@app.get("/closest-cheapest")
def closest_cheapest():
    """Return the closest cheapest N locations to a given lat/lon.

    Query params:
      - lat: required float
      - lon: required float
      - limit: optional int (default 5)
      - fuel: optional string fuel type label
    """
    lat_param = request.args.get("lat")
    lon_param = request.args.get("lon")
    limit_param = request.args.get("limit", "5")
    fuel_param = request.args.get("fuel")

    try:
        user_lat = float(lat_param) if lat_param is not None else None
        user_lon = float(lon_param) if lon_param is not None else None
        limit = int(limit_param)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid query parameters"}), 400

    if user_lat is None or user_lon is None:
        return jsonify({"error": "Missing required lat/lon"}), 400

    locations = load_locations()
    if not locations:
        app.logger.warning(f"No locations loaded from {DATA_PATH}")
        # Check if file exists and log details
        if os.path.exists(DATA_PATH):
            app.logger.warning(f"File exists but returned no locations: {DATA_PATH}")
        else:
            app.logger.error(f"File does not exist: {DATA_PATH}")
        return jsonify({"error": f"No data found at {DATA_PATH}"}), 500

    enriched: List[Dict[str, Any]] = []
    for obj in locations:
        if not isinstance(obj, dict):
            continue
        coords = extract_lat_lon(obj)
        if not coords:
            continue
        price = extract_price(obj, fuel_param)
        if price is None:
            continue
        dist_km = haversine_km(user_lat, user_lon, coords[0], coords[1])
        info = extract_basic_info(obj)
        enriched.append(
            {
                "name": info.get("name") or None,
                "brand": info.get("brand") or None,
                "address": info.get("address") or None,
                "price": round(float(price), 3),
                "distance_km": round(dist_km, 3),
                "lat": coords[0],
                "lon": coords[1],
                "raw": obj,  # keep original for transparency
            }
        )

    # Sort by price asc then distance asc
    enriched.sort(key=lambda x: (x["price"], x["distance_km"]))
    result = enriched[: max(1, limit)]

    return jsonify(
        {
            "count": len(result),
            "limit": limit,
            "fuel": fuel_param,
            "data_path": DATA_PATH,
            "results": result,
        }
    )


def create_app():
    """Factory for Cloud Run / Gunicorn."""
    return app


if __name__ == "__main__":
    # Useful for local testing
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
