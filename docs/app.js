// Configuration
const REPO_OWNER = 'KRoperUK';
const REPO_NAME = 'fill-er-up';

// Use CORS proxy for GitHub releases
// Alternative: Use raw.githubusercontent.com from main branch
const DATA_URL = `https://corsproxy.io/?https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/download/latest/fuel_prices.json`;

// Fuel type mappings
const FUEL_TYPES = {
    'E10': 'Unleaded (E10)',
    'E5': 'Super Unleaded (E5)',
    'B7': 'Diesel (B7)',
    'SDV': 'Premium Diesel',
    'ULSP': 'Super Unleaded',
    'LPG': 'LPG (Autogas)'
};

// Global variables
let map;
let markers = [];
let markerCluster;
let allData = null;
let currentFilters = {
    retailer: '',
    fuelType: ''
};
let userLocation = null;
let maxDistance = 3; // miles
let searchRadiusCircle = null;
let userMarker = null;

// Initialize the application
async function init() {
    try {
        showLoading(true);

        // Load saved preferences from localStorage
        const savedMaxDistance = localStorage.getItem('maxDistance');
        if (savedMaxDistance) {
            maxDistance = parseInt(savedMaxDistance);
        }

        // Fetch the data
        const response = await fetch(DATA_URL);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        allData = data;

        // Initialize the map
        initMap();

        // Restore saved last location (if any)
        try {
            const saved = localStorage.getItem('lastLocation');
            if (saved) {
                const obj = JSON.parse(saved);
                if (obj && obj.lat && obj.lng) {
                    userLocation = { lat: parseFloat(obj.lat), lng: parseFloat(obj.lng) };
                    // center map on saved location
                    map.setView([userLocation.lat, userLocation.lng], obj.zoom || 12);

                    // add persistent marker
                    userMarker = L.marker([userLocation.lat, userLocation.lng], {
                        icon: L.icon({
                            iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
                            shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
                            iconSize: [25, 41],
                            iconAnchor: [12, 41],
                            popupAnchor: [1, -34],
                            shadowSize: [41, 41]
                        })
                    }).addTo(map);

                    if (obj.name) {
                        userMarker.bindPopup(`<strong>${obj.name}</strong>`);
                        const searchInput = document.getElementById('search-input');
                        if (searchInput) searchInput.value = obj.name;
                    }

                    updateSearchRadius();
                }
            }
        } catch (err) {
            console.warn('Unable to restore lastLocation from localStorage', err);
        }

        // Wait for map to be ready before processing data
        setTimeout(() => {
            // Force map to recalculate size after container is visible
            map.invalidateSize();

            processData(data);

            // Hide loading, show content
            showLoading(false);
            document.getElementById('summary').classList.remove('is-hidden');
            document.getElementById('content').classList.remove('is-hidden');

            // Invalidate size again after content is shown
            setTimeout(() => map.invalidateSize(), 100);
        }, 200);

    } catch (error) {
        console.error('Error fetching data:', error);
        showError(`Failed to fetch fuel prices: ${error.message}`);
        showLoading(false);
    }
}

// Initialize the Leaflet map
function initMap() {
    // Center on UK
    map = L.map('map', {
        preferCanvas: false,
        renderer: L.canvas()
    }).setView([54.5, -3.5], 6);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 14,
        minZoom: 5
    }).addTo(map);

    map.maxZoom = 14;

    // Add locate control
    const locateControl = L.control.locate({
        position: 'topleft',
        strings: {
            title: "Show my location"
        },
        locateOptions: {
            enableHighAccuracy: true
        }
    }).addTo(map);

    // Listen for location found event
    map.on('locationfound', (e) => {
        userLocation = e.latlng;

        // Persist last location
        try {
            localStorage.setItem('lastLocation', JSON.stringify({ lat: userLocation.lat, lng: userLocation.lng }));
        } catch (err) {
            console.warn('Unable to save lastLocation to localStorage', err);
        }

        // Add or update persistent user marker
        if (userMarker) {
            userMarker.setLatLng(userLocation);
        } else {
            userMarker = L.marker(userLocation, {
                icon: L.icon({
                    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
                    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowSize: [41, 41]
                })
            }).addTo(map);
        }

        updateSearchRadius();
        updateCheapestStations();
    });

    // Initialize marker cluster group after a small delay
    setTimeout(() => {
        markerCluster = L.markerClusterGroup({
            chunkedLoading: true,
            spiderfyOnMaxZoom: true,
            showCoverageOnHover: false,
            zoomToBoundsOnClick: true,
            maxClusterRadius: 80
        });
        map.addLayer(markerCluster);
    }, 100);
}

// Get human-readable fuel type name
function getFuelTypeName(code) {
    return FUEL_TYPES[code] || code;
}

// Get station display name from available fields
function getStationName(station) {
    // Try various possible name fields
    if (station.site_name) return station.site_name;
    if (station.name) return station.name;
    if (station.station_name) return station.station_name;

    // Fallback to brand + location from address
    if (station.brand && station.address) {
        // Extract location from address (usually last part)
        const addressParts = station.address.split(',');
        const location = addressParts[addressParts.length - 1].trim();
        return `${station.brand} - ${location}`;
    }

    if (station.brand) return station.brand;
    if (station.address) return station.address;

    return 'Unknown Station';
}

// Process the fetched data
function processData(data) {
    const results = data.results;

    // Update summary
    updateSummary(data, results);

    // Update retailer status
    updateRetailerStatus(results);

    // Populate retailer filter
    populateRetailerFilter(results);

    // Populate fuel type filter
    populateFuelTypeFilter(results);

    // Setup search functionality
    setupSearch();

    // Add stations to map
    addStationsToMap(results);

    // If a user location is known (restored or set), update cheapest stations
    if (userLocation) {
        // ensure search radius and persistent marker are present
        updateSearchRadius();
        if (!userMarker) {
            userMarker = L.marker([userLocation.lat, userLocation.lng], {
                icon: L.icon({
                    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
                    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowSize: [41, 41]
                })
            }).addTo(map);
        }
        updateCheapestStations();
    }
}

// Update summary statistics
function updateSummary(data, results) {
    const successful = results.filter(r => r.status === 'success');
    let totalStations = 0;

    successful.forEach(result => {
        if (result.data && result.data.stations) {
            totalStations += result.data.stations.length;
        }
    });

    document.getElementById('retailer-count').textContent = results.length;
    document.getElementById('station-count').textContent = totalStations.toLocaleString();

    const timestamp = new Date(data.timestamp);
    document.getElementById('last-updated').textContent = timestamp.toLocaleString();
}

// Update retailer status list
function updateRetailerStatus(results) {
    const statusDiv = document.getElementById('retailer-status');
    const successful = results.filter(r => r.status === 'success');
    const errors = results.filter(r => r.status === 'error');

    let html = '<div class="tags">';

    successful.forEach(result => {
        const stationCount = result.data?.stations?.length || 0;
        html += `
            <span class="tag is-success" title="${result.retailer}: ${stationCount} stations">
                <i class="fas fa-check"></i>&nbsp;${result.retailer}
            </span>
        `;
    });

    errors.forEach(result => {
        html += `
            <span class="tag is-danger" title="${result.retailer}: ${result.error}">
                <i class="fas fa-times"></i>&nbsp;${result.retailer}
            </span>
        `;
    });

    html += '</div>';
    statusDiv.innerHTML = html;
}

// Populate retailer filter dropdown
function populateRetailerFilter(results) {
    const select = document.getElementById('retailer-select');
    const successful = results.filter(r => r.status === 'success');

    successful.forEach(result => {
        const option = document.createElement('option');
        option.value = result.retailer;
        option.textContent = result.retailer;
        select.appendChild(option);
    });

    // Restore saved retailer filter
    const savedRetailer = localStorage.getItem('retailer');
    if (savedRetailer) {
        const retailers = successful.map(r => r.retailer);
        if (retailers.includes(savedRetailer)) {
            select.value = savedRetailer;
            currentFilters.retailer = savedRetailer;
            applyFilters();
        }
    }

    // Add event listener
    select.addEventListener('change', (e) => {
        currentFilters.retailer = e.target.value;
        localStorage.setItem('retailer', e.target.value);
        applyFilters();
    });
}

// Populate fuel type filter dropdown
function populateFuelTypeFilter(results) {
    const select = document.getElementById('fuel-type-select');
    const fuelTypesSet = new Set();

    const successful = results.filter(r => r.status === 'success');

    successful.forEach(result => {
        if (!result.data || !result.data.stations) return;

        result.data.stations.forEach(station => {
            if (station.prices) {
                Object.keys(station.prices).forEach(fuelType => {
                    fuelTypesSet.add(fuelType);
                });
            }
        });
    });

    // Sort fuel types
    const sortedFuelTypes = Array.from(fuelTypesSet).sort();

    sortedFuelTypes.forEach(fuelType => {
        const option = document.createElement('option');
        option.value = fuelType;
        option.textContent = getFuelTypeName(fuelType);
        select.appendChild(option);
    });

    // Restore saved fuel type filter
    const savedFuelType = localStorage.getItem('fuelType');
    if (savedFuelType && sortedFuelTypes.includes(savedFuelType)) {
        select.value = savedFuelType;
        currentFilters.fuelType = savedFuelType;
        applyFilters();
    }

    // Add event listener
    select.addEventListener('change', (e) => {
        currentFilters.fuelType = e.target.value;
        localStorage.setItem('fuelType', e.target.value);
        applyFilters();
        // Update cheapest stations list if location is available
        if (userLocation) {
            updateCheapestStations();
        }
    });
}

// Setup search functionality
function setupSearch() {
    const searchInput = document.getElementById('search-input');
    const maxDistanceInput = document.getElementById('max-distance');

    // Restore saved max distance
    const savedMaxDistance = localStorage.getItem('maxDistance');
    if (savedMaxDistance) {
        maxDistanceInput.value = savedMaxDistance;
        maxDistance = parseInt(savedMaxDistance);
    }

    // Update max distance when user changes it
    maxDistanceInput.addEventListener('change', () => {
        const newDistance = parseInt(maxDistanceInput.value);
        if (newDistance >= 1 && newDistance <= 50) {
            maxDistance = newDistance;
            localStorage.setItem('maxDistance', newDistance);
            updateSearchRadius();
            if (userLocation) {
                updateCheapestStations();
            }
        }
    });

    searchInput.addEventListener('keypress', async (e) => {
        if (e.key === 'Enter') {
            const query = searchInput.value.trim();
            if (!query) return;

            try {
                // Use Nominatim (OpenStreetMap) geocoding API
                const response = await fetch(
                    `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&countrycodes=gb&limit=1`
                );
                const results = await response.json();

                if (results.length > 0) {
                    const lat = parseFloat(results[0].lat);
                    const lon = parseFloat(results[0].lon);

                    // Set user location for cheapest stations calculation
                    userLocation = { lat: lat, lng: lon };

                    // Persist last location with display name and current zoom
                    try {
                        localStorage.setItem('lastLocation', JSON.stringify({
                            lat: lat,
                            lng: lon,
                            name: results[0].display_name,
                            zoom: map.getZoom() || 12
                        }));
                    } catch (err) {
                        console.warn('Unable to save lastLocation to localStorage', err);
                    }

                    // Zoom to location
                    map.setView([lat, lon], 12);

                    // Add or update persistent user marker and show popup
                    if (userMarker) {
                        userMarker.setLatLng([lat, lon]);
                        userMarker.bindPopup(`<strong>${results[0].display_name}</strong>`).openPopup();
                    } else {
                        userMarker = L.marker([lat, lon], {
                            icon: L.icon({
                                iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
                                shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
                                iconSize: [25, 41],
                                iconAnchor: [12, 41],
                                popupAnchor: [1, -34],
                                shadowSize: [41, 41]
                            })
                        }).addTo(map);
                        userMarker.bindPopup(`<strong>${results[0].display_name}</strong>`).openPopup();
                    }

                    // Update search radius and cheapest stations
                    updateSearchRadius();
                    updateCheapestStations();
                } else {
                    alert('Location not found. Please try a different search term.');
                }
            } catch (error) {
                console.error('Geocoding error:', error);
                alert('Error searching for location. Please try again.');
            }
        }
    });
}

// Add stations to the map
function addStationsToMap(results) {
    const successful = results.filter(r => r.status === 'success');

    successful.forEach(result => {
        if (!result.data || !result.data.stations) return;

        result.data.stations.forEach(station => {
            addStationMarker(station, result.retailer);
        });
    });
}

// Add a single station marker
function addStationMarker(station, retailer) {
    // Skip if no location data
    if (!station.location?.latitude || !station.location?.longitude) {
        return;
    }

    const lat = parseFloat(station.location.latitude);
    const lon = parseFloat(station.location.longitude);

    if (isNaN(lat) || isNaN(lon)) return;

    const marker = L.marker([lat, lon]);

    // Store station data for dynamic popup updates
    marker.stationData = station;
    marker.retailer = retailer;
    marker.fuelTypes = station.prices ? Object.keys(station.prices) : [];

    // Generate and bind popup
    updateMarkerPopup(marker);

    markerCluster.addLayer(marker);
    markers.push(marker);
}

// Update marker popup based on current fuel type filter
function updateMarkerPopup(marker) {
    const station = marker.stationData;
    const retailer = marker.retailer;

    let popupContent = `
        <div class="content">
            <h4 class="title is-6">${getStationName(station)}</h4>
            <p><strong>${retailer}</strong></p>
    `;

    if (station.address) {
        popupContent += `<p class="is-size-7">${station.address}</p>`;
    }

    if (station.prices) {
        popupContent += '<div class="tags">';

        // Filter prices based on selected fuel type
        const pricesToShow = currentFilters.fuelType
            ? Object.entries(station.prices).filter(([fuelType]) => fuelType === currentFilters.fuelType)
            : Object.entries(station.prices);

        pricesToShow.forEach(([fuelType, price]) => {
            popupContent += `
                <span class="tag is-info">
                    ${getFuelTypeName(fuelType)}: £${(price / 100).toFixed(2)}
                </span>
            `;
        });
        popupContent += '</div>';
    }

    popupContent += '</div>';

    marker.bindPopup(popupContent);
}

// Update search radius circle on map
function updateSearchRadius() {
    // Remove existing circle
    if (searchRadiusCircle) {
        map.removeLayer(searchRadiusCircle);
        searchRadiusCircle = null;
    }

    // Add new circle if location is set
    if (userLocation) {
        searchRadiusCircle = L.circle(userLocation, {
            radius: maxDistance * 1609.34, // Convert miles to meters
            color: '#667eea',
            fillColor: '#667eea',
            fillOpacity: 0.1,
            weight: 2,
            opacity: 0.5
        }).addTo(map);

        searchRadiusCircle.bindPopup(`<strong>Search radius:</strong> ${maxDistance} mile${maxDistance !== 1 ? 's' : ''}`);
    }
}

// Calculate distance between two points in miles
function calculateDistance(lat1, lon1, lat2, lon2) {
    const R = 3959; // Earth's radius in miles
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a =
        Math.sin(dLat/2) * Math.sin(dLat/2) +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
        Math.sin(dLon/2) * Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c;
}

// Update cheapest stations list based on user location
function updateCheapestStations() {
    if (!userLocation || !allData) return;

    const stationsList = document.getElementById('stations-list');
    const results = allData.results.filter(r => r.status === 'success');

    // Collect all stations with prices and distances
    const stationsWithPrices = [];

    results.forEach(result => {
        if (!result.data || !result.data.stations) return;

        result.data.stations.forEach(station => {
            if (!station.location?.latitude || !station.location?.longitude) return;
            if (!station.prices) return;

            const lat = parseFloat(station.location.latitude);
            const lon = parseFloat(station.location.longitude);

            if (isNaN(lat) || isNaN(lon)) return;

            const distance = calculateDistance(
                userLocation.lat, userLocation.lng,
                lat, lon
            );

            stationsWithPrices.push({
                name: getStationName(station),
                address: station.address || '',
                retailer: result.retailer,
                prices: station.prices,
                distance: distance,
                lat: lat,
                lon: lon
            });
        });
    });

    // Group by fuel type and find cheapest
    const fuelTypes = new Set();
    stationsWithPrices.forEach(station => {
        Object.keys(station.prices).forEach(fuelType => fuelTypes.add(fuelType));
    });

    // Filter fuel types based on current filter
    const fuelTypesToShow = currentFilters.fuelType
        ? [currentFilters.fuelType]
        : Array.from(fuelTypes).sort();

    let html = '<div class="content">';
    html += `<p class="has-text-success"><i class="fas fa-location-dot"></i> <strong>Cheapest stations within ${maxDistance} miles</strong></p>`;

    // Show warning if fuel type filter is active
    if (currentFilters.fuelType) {
        html += `<div class="notification is-warning is-light">
            <p><i class="fas fa-filter"></i> Showing only <strong>${getFuelTypeName(currentFilters.fuelType)}</strong> prices.
            Clear the fuel type filter to see all fuel types.</p>
        </div>`;
    }

    fuelTypesToShow.forEach(fuelType => {
        // Get stations with this fuel type, filter by distance, sorted by price then distance
        const stationsWithFuel = stationsWithPrices
            .filter(s => s.prices[fuelType] && s.distance <= maxDistance)
            .map(s => ({
                ...s,
                price: s.prices[fuelType]
            }))
            .sort((a, b) => {
                if (a.price !== b.price) return a.price - b.price;
                return a.distance - b.distance;
            })
            .slice(0, 5);

        if (stationsWithFuel.length === 0) return;

        html += `<h5 class="title is-6 mt-4"><span class="tag is-info">${getFuelTypeName(fuelType)}</span></h5>`;
        html += '<table class="table is-fullwidth is-striped is-hoverable is-narrow">';
        html += '<thead><tr><th>Station</th><th>Price</th><th>Distance</th></tr></thead>';
        html += '<tbody>';

        stationsWithFuel.forEach(station => {
            const priceFormatted = `£${(station.price / 100).toFixed(2)}`;
            const distanceFormatted = station.distance < 0.1
                ? `${(station.distance * 1760).toFixed(0)} yards`
                : `${station.distance.toFixed(1)} mi`;

            html += '<tr style="cursor: pointer;" onclick="map.setView([' + station.lat + ', ' + station.lon + '], 15);">';
            html += `<td><strong>${station.name}</strong><br><small class="has-text-grey">${station.retailer}</small></td>`;
            html += `<td><span class="tag is-success">${priceFormatted}</span></td>`;
            html += `<td><small>${distanceFormatted}</small></td>`;
            html += '</tr>';
        });

        html += '</tbody></table>';
    });

    html += '</div>';
    stationsList.innerHTML = html;
}

// Apply all filters
function applyFilters() {
    // Clear existing cluster
    markerCluster.clearLayers();

    // Add filtered markers back and update popups
    markers.forEach(marker => {
        const retailerMatch = !currentFilters.retailer || marker.retailer === currentFilters.retailer;
        const fuelTypeMatch = !currentFilters.fuelType || marker.fuelTypes.includes(currentFilters.fuelType);

        if (retailerMatch && fuelTypeMatch) {
            // Update popup to reflect current fuel type filter
            updateMarkerPopup(marker);
            markerCluster.addLayer(marker);
        }
    });
}

// Show/hide loading indicator
function showLoading(show) {
    document.getElementById('loading').classList.toggle('is-hidden', !show);
}

// Show error message
function showError(message) {
    document.getElementById('error-message').textContent = message;
    document.getElementById('error').classList.remove('is-hidden');
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', init);
