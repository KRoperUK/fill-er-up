/**
 * Welcome to Cloudflare Workers! This is your first worker.
 *
 * - Run "npm run dev" in your terminal to start a development server
 * - Open a browser tab at http://localhost:8787/ to see your worker in action
 * - Run "npm run deploy" to publish your worker
 *
 * Learn more at https://developers.cloudflare.com/workers/
 */

const getLatestDataFromR2 = async (env) => {
  const bucket = env["fuel-prices"];
  const objectKey = "fuel_prices.json";

  const object = await bucket.get(objectKey);
  if (!object) {
    throw new Error("Object not found in R2 bucket");
  }

  const data = await object.text();
  return JSON.parse(data);
}

function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371; // Radius of the Earth in kilometers
  const dLat = (lat2 - lat1) * (Math.PI / 180);
  const dLon = (lon2 - lon1) * (Math.PI / 180);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * (Math.PI / 180)) *
      Math.cos(lat2 * (Math.PI / 180)) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  const distance = R * c; // Distance in kilometers
  return distance;
}

function normalise(retailer, station) {
  switch (retailer) {
    case "Costco":
      return {
        name: station.name,
        address: `${station.address.line1}, ${station.address.town}, ${station.address.postalCode}`,
        latitude: station.geoPoint.latitude,
        longitude: station.geoPoint.longitude,
        prices: {
          unleaded: station.fuelPrices.REGULAR.price,
          diesel: station.fuelPrices.DIESEL.price,
          premium_unleaded: station.fuelPrices.PREMIUM.price,
        },
      };
    default:
      return {
        name: station.name ?? station.displayName,
        address: station.address?.line1 ?? station.address,
        latitude: station.latitude ?? station.location?.latitude ?? station.geo?.latitude,
        longitude: station.longitude ?? station.location?.longitude ?? station.geo?.longitude,
        prices: station.prices ?? station.fuelPrices,
      };
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const { pathname, searchParams } = url;

    const accept = request.headers.get("accept") || "";

    // If the client explicitly accepts HTML, reject it
    if (accept.includes("text/html") && !accept.includes("application/json") && !accept.includes("*/*")) {
      return new Response(
        JSON.stringify({
          error: "HTML responses are not supported. This is a JSON API.",
        }),
        {
          status: 406, // Not Acceptable
          headers: {
            "content-type": "application/json",
          },
        }
      );
    }

    if (request.method === "GET") {
      if (pathname === "/latest-fuel-prices") {
        try {
          const data = await getLatestDataFromR2(env);
          return new Response(JSON.stringify(data), {
            status: 200,
            headers: {
              "content-type": "application/json",
              "Access-Control-Allow-Origin": "*",
            },
          });
        } catch (error) {
          return new Response(
            JSON.stringify({
              error: "Failed to retrieve data from database: " + error.message,
            }),
            {
              status: 500, // Internal Server Error
              headers: {
                "content-type": "application/json",
              },
            }
          );
        }
      } else if (pathname === "/") {
        return new Response(
          JSON.stringify({
            message: "Welcome to the Fill 'Er Up API! Use /latest-fuel-prices to get the latest data.",
          }),
          {
            status: 200,
            headers: {
              "content-type": "application/json",
            },
          }
        );
      } else if (pathname === "/favicon.ico") {
        return new Response(null, {
          status: 204, // No Content
        });
      } else if (pathname === "/robots.txt") {
        return new Response("User-agent: *\nDisallow: /", {
          status: 200,
          headers: {
            "content-type": "text/plain",
          },
        });

      } else if (pathname === "/health") {
        return new Response(
          JSON.stringify({
            status: "ok",
            timestamp: new Date().toISOString(),
          }),
          {
            status: 200,
            headers: {
              "content-type": "application/json",
            },
          }
        );
      } else if (pathname === "/cheapest-nearby-lat-long") {
        if (searchParams.has("lat") && searchParams.has("long")) {
          const lat = searchParams.get("lat");
          const long = searchParams.get("long");

          const data = await getLatestDataFromR2(env);

          const radius = searchParams.get("radius") || 10; // Default radius in km
          const fuelType = searchParams.get("fuel") || "unleaded"; // Default fuel type

          let stationsNearby = [];

          for (const retailer of data.results) {
            if (retailer.status === "success" && retailer.data) {
              const stations = retailer.data.stations ?? retailer.data.stores;
              if (stations) {
                for (const station of stations) {
                  const s = normalise(retailer.retailer, station);

                  if (s.latitude && s.longitude) {
                    const distance = haversine(lat, long, s.latitude, s.longitude);
                    if (distance <= radius) {
                      const price = s.prices ? s.prices[fuelType] : undefined;

                      if (price) {
                        stationsNearby.push({
                          retailer: retailer.retailer,
                          name: s.name,
                          address: s.address,
                          distance: distance.toFixed(2),
                          price: price,
                          last_updated: station.last_updated ?? retailer.data.last_updated,
                        });
                      }
                    }
                  }
                }
              }
            }
          }

          stationsNearby.sort((a, b) => a.price - b.price);

          return new Response(
            JSON.stringify({
              message: `Found ${stationsNearby.length} stations within ${radius}km.`,
              stations: stationsNearby,
            }),
            {
              status: 200,
              headers: {
                "content-type": "application/json",
                "Access-Control-Allow-Origin": "*",
              },
            }
          );
        } else {
          return new Response(
            JSON.stringify({
              error: "Missing required query parameters 'lat' and 'long'.",
            }),
            {
              status: 400, // Bad Request
              headers: {
                "content-type": "application/json",
              },
            }
          );
        }
      } else {
        return new Response(
          JSON.stringify({
            error: "Endpoint not found. Use /latest-fuel-prices to get the latest data.",
          }),
          {
            status: 404, // Not Found
            headers: {
              "content-type": "application/json",
            },
          }
        );
      }
    } else if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type, Accept",
        },
      });
    } else {
      return new Response(
        JSON.stringify({
          error: "Method not allowed. Only GET requests are supported.",
        }),
        {
          status: 405, // Method Not Allowed
          headers: {
            "content-type": "application/json",
            "Allow": "GET, OPTIONS",
          },
        }
      );
    }
  }
};
