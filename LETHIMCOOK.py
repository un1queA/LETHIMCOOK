import streamlit as st
import requests
import pandas as pd
import math
import time
import re
from geopy.distance import geodesic, distance
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from difflib import SequenceMatcher

st.set_page_config(layout="wide")
st.title("🍜 Multi-Source Food Finder (All Cuisines)")

# -------------------------
# API KEY INPUTS
# -------------------------
st.sidebar.header("🔑 API Keys (required)")
google_api_key = st.sidebar.text_input("Google Places API Key", type="password", help="Get it from Google Cloud Console")
foursquare_api_key = st.sidebar.text_input("Foursquare Places API Key", type="password", help="Get it from Foursquare Developer Portal")

if not google_api_key or not foursquare_api_key:
    st.sidebar.warning("Please enter both API keys to enable searching.")
    st.stop()

# -------------------------
# CACHE for OSRM distances & reverse geocoding
# -------------------------
if "osrm_cache" not in st.session_state:
    st.session_state.osrm_cache = {}
if "reverse_geocode_cache" not in st.session_state:
    st.session_state.reverse_geocode_cache = {}

# -------------------------
# UTILITIES
# -------------------------
def geocode_address(address):
    geolocator = Nominatim(user_agent="food_finder_app")
    try:
        location = geolocator.geocode(address)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        st.error(f"Geocoding error: {e}")
    return None

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    lon1_rad = math.radians(lon1)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def strict_radius_filter(results, user_coords, radius_km):
    filtered = []
    for r in results:
        lat = r.get("lat")
        lon = r.get("lon")
        if lat is None or lon is None:
            continue
        try:
            dist = geodesic(user_coords, (lat, lon)).km
        except:
            continue
        if dist <= radius_km:
            r["distance_km"] = round(dist, 2)
            filtered.append(r)
    return filtered

# -------------------------
# REVERSE GEOCODING (fill missing addresses)
# -------------------------
def reverse_geocode(lat, lon):
    """Get address from coordinates using Nominatim (with cache)."""
    key = f"{lat:.6f},{lon:.6f}"
    if key in st.session_state.reverse_geocode_cache:
        return st.session_state.reverse_geocode_cache[key]

    geolocator = Nominatim(user_agent="food_finder_app")
    try:
        location = geolocator.reverse((lat, lon), exactly_one=True, language='en')
        if location and location.address:
            address = location.address
            st.session_state.reverse_geocode_cache[key] = address
            return address
    except Exception as e:
        st.warning(f"Reverse geocoding failed for {lat},{lon}: {e}")
    st.session_state.reverse_geocode_cache[key] = "Address not available"
    return "Address not available"

# -------------------------
# CHECK IF VENUE IS OPEN (2026) – with debug
# -------------------------
def is_venue_open(venue):
    """Return False if the venue is permanently closed."""
    source = venue.get("source")
    closed_reason = None

    # Google
    if source == "Google":
        status = venue.get("business_status")
        if status == "CLOSED_PERMANENTLY":
            closed_reason = "Google: CLOSED_PERMANENTLY"
    # Foursquare
    elif source == "Foursquare":
        if venue.get("closed") is True or venue.get("date_closed") is not None:
            closed_reason = f"Foursquare: closed={venue.get('closed')}, date_closed={venue.get('date_closed')}"
    # OSM
    elif source == "OSM":
        tags = venue.get("tags", {})
        if "disused:amenity" in tags:
            closed_reason = "OSM: disused:amenity"
        if "was:amenity" in tags:
            closed_reason = "OSM: was:amenity"

    if closed_reason:
        return False
    return True

# -------------------------
# NORMALIZE NAME for comparison
# -------------------------
def normalize_name(name):
    if not isinstance(name, str):
        return ""
    name = name.lower()
    name = re.sub(r'[^\w\s]', '', name)
    common_suffixes = [
        'restaurant', 'cafe', 'coffee', 'bakery', 'bar', 'pub', 'diner',
        'eatery', 'bistro', 'tavern', 'fast food', 'takeaway', 'deli',
        'buffet', 'food court', 'hawker', 'stall', 'food truck', 'izakaya',
        'steakhouse', 'pizzeria', 'noodle', 'sushi', 'dessert', 'ice cream',
        'juice', 'beverage', 'chicken', 'burger', 'pasta', 'rice', 'seafood',
        'vegetarian', 'vegan', 'halal', 'indian', 'chinese', 'malay',
        'japanese', 'korean', 'thai', 'vietnamese', 'mexican', 'italian',
        'western', 'pte', 'ltd', 'limited', '&', 'and', 'the', 'at', 'by'
    ]
    words = name.split()
    while words and words[-1] in common_suffixes:
        words.pop()
    normalized = ' '.join(words).strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized

# -------------------------
# IMPROVED NAME MATCH (contains + fuzzy)
# -------------------------
def names_match(name1, name2, threshold=0.7):
    """Return True if names are similar enough (containment or fuzzy ratio)."""
    n1 = normalize_name(name1)
    n2 = normalize_name(name2)
    if not n1 or not n2:
        return False
    if n1 in n2 or n2 in n1:
        return True
    ratio = SequenceMatcher(None, n1, n2).ratio()
    return ratio >= threshold

# -------------------------
# ADVANCED DEDUPLICATION (clustering by distance + name)
# -------------------------
def cluster_and_merge(venues, max_distance_m=150, name_threshold=0.7):
    """Cluster venues within distance and similar names, merge them."""
    if not venues:
        return []

    venues_sorted = sorted(venues, key=lambda x: x.get("distance_km", float('inf')))
    clusters = []
    for v in venues_sorted:
        matched = False
        for cluster in clusters:
            rep = cluster[0]
            d = geodesic((v["lat"], v["lon"]), (rep["lat"], rep["lon"])).meters
            if d <= max_distance_m and names_match(v["name"], rep["name"], name_threshold):
                cluster.append(v)
                matched = True
                break
        if not matched:
            clusters.append([v])

    merged = []
    for cluster in clusters:
        best = None
        best_score = -1
        sources = set()
        for v in cluster:
            sources.add(v["source"])
            addr = v.get("address", "")
            score = 0
            if addr and addr != "Address not available":
                score += len(addr) + 100
            if v["source"] in ("Foursquare", "Google"):
                score += 200
            elif v["source"] == "OSM":
                score += 100
            if score > best_score:
                best_score = score
                best = v.copy()
        if best:
            if best["address"] in (None, "", "Address not available"):
                best["address"] = reverse_geocode(best["lat"], best["lon"])
            best["source"] = "+".join(sorted(sources))
            best["distance_km"] = min(v["distance_km"] for v in cluster)
            merged.append(best)
    return merged

# -------------------------
# FOOD ESTABLISHMENT FILTER (with blacklist)
# -------------------------
FOOD_INDICATORS = [
    'restaurant', 'food', 'cafe', 'coffee', 'bakery',
    'bar', 'pub', 'diner', 'eatery', 'bistro', 'tavern',
    'fast food', 'takeaway', 'takeout', 'deli', 'buffet',
    'food court', 'market', 'hawker', 'stall', 'food truck',
    'izakaya', 'steakhouse', 'pizzeria', 'noodle', 'sushi',
    'dessert', 'ice cream', 'juice', 'beverage',
    'chicken', 'burger', 'pasta', 'rice', 'noodles',
    'seafood', 'vegetarian', 'vegan', 'halal', 'indian',
    'chinese', 'malay', 'japanese', 'korean', 'thai',
    'vietnamese', 'mexican', 'italian', 'western'
]
NON_FOOD_BLACKLIST = ['supermarket', 'grocery', 'mart', 'store', 'clinic', 'hospital', 'bank', 'school']

def is_food_place(venue):
    types = venue.get("types", [])
    if not types:
        return False
    types_lower = [t.lower() for t in types]
    for t in types_lower:
        for bad in NON_FOOD_BLACKLIST:
            if bad in t:
                return False
    for t in types_lower:
        for ind in FOOD_INDICATORS:
            if ind in t:
                return True
    return False

# -------------------------
# OSRM CLIENT (with caching and retries)
# -------------------------
class OSRMClient:
    def __init__(self, base_url="https://router.project-osrm.org", profile="foot"):
        self.base_url = base_url
        self.profile = profile
        self.last_request = 0
        self.min_delay = 0.2
        self.max_retries = 3
        self.timeout = 30

    def _rate_limit(self):
        now = time.time()
        if self.last_request:
            elapsed = now - self.last_request
            if elapsed < self.min_delay:
                time.sleep(self.min_delay - elapsed)
        self.last_request = time.time()

    def _request_with_retry(self, url, params):
        for attempt in range(self.max_retries):
            try:
                self._rate_limit()
                resp = requests.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp
                elif resp.status_code in (502, 503, 504):
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue
                else:
                    return None
            except requests.RequestException:
                if attempt == self.max_retries - 1:
                    return None
                time.sleep(2 ** attempt)
        return None

    def batch_walking_distances_chunked(self, home_lat, home_lon, venues, chunk_size=100):
        if not venues:
            return []

        distances = [None] * len(venues)
        cache_key_base = f"{home_lat:.6f},{home_lon:.6f}"
        for i, v in enumerate(venues):
            key = (cache_key_base, f"{v['lat']:.6f},{v['lon']:.6f}")
            if key in st.session_state.osrm_cache:
                distances[i] = st.session_state.osrm_cache[key]

        uncached_indices = [i for i, d in enumerate(distances) if d is None]
        if not uncached_indices:
            return distances

        uncached_venues = [venues[i] for i in uncached_indices]
        total_uncached = len(uncached_venues)

        chunk_size = min(chunk_size, 100)
        progress_bar = st.progress(0)
        status_text = st.empty()

        for chunk_start in range(0, total_uncached, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total_uncached)
            chunk_venues = uncached_venues[chunk_start:chunk_end]
            status_text.text(f"OSRM: Processing chunk {chunk_start//chunk_size + 1}/{(total_uncached+chunk_size-1)//chunk_size} ({len(chunk_venues)} venues)...")

            coords = [f"{home_lon},{home_lat}"] + [f"{v['lon']},{v['lat']}" for v in chunk_venues]
            coord_str = ";".join(coords)
            url = f"{self.base_url}/table/v1/{self.profile}/{coord_str}"
            params = {
                "sources": "0",
                "destinations": ";".join(str(i) for i in range(1, len(coords))),
                "annotations": "distance"
            }

            resp = self._request_with_retry(url, params)
            if resp and resp.status_code == 200:
                data = resp.json()
                if data.get("code") == "Ok" and "distances" in data:
                    chunk_dists = data["distances"][0]
                    for j, d in enumerate(chunk_dists):
                        if d is not None:
                            orig_idx = uncached_indices[chunk_start + j]
                            distances[orig_idx] = d
                            key = (cache_key_base, f"{venues[orig_idx]['lat']:.6f},{venues[orig_idx]['lon']:.6f}")
                            st.session_state.osrm_cache[key] = d
                else:
                    st.warning(f"OSRM returned error for chunk: {data.get('code')}")
            else:
                st.warning(f"OSRM request failed for chunk (after retries).")

            progress_bar.progress(min((chunk_end) / total_uncached, 1.0))

        status_text.empty()
        progress_bar.empty()
        return distances

# -------------------------
# GRID GENERATION (unchanged)
# -------------------------
def generate_hex_grid(center_lat, center_lon, outer_radius_m, grid_spacing_m):
    d = math.sqrt(3) * grid_spacing_m
    x_step = d
    y_step = d * math.sqrt(3) / 2.0
    max_steps = int(math.ceil(outer_radius_m / d)) + 1

    lat_per_m = 1.0 / 111000.0
    lng_per_m = 1.0 / (111000.0 * math.cos(math.radians(center_lat)))

    points = []
    for col in range(-max_steps, max_steps + 1):
        for row in range(-max_steps, max_steps + 1):
            x = col * x_step
            y = row * y_step + (col % 2) * y_step / 2.0
            if math.sqrt(x**2 + y**2) > outer_radius_m:
                continue
            lat = center_lat + y * lat_per_m
            lon = center_lon + x * lng_per_m
            points.append((lat, lon))
    return points

def adaptive_grid_spacing(radius_km):
    if radius_km <= 1.0:
        return 400
    elif radius_km <= 3.0:
        return 600
    elif radius_km <= 10.0:
        return 800
    elif radius_km <= 20.0:
        return 1200
    else:
        return 2000

# -------------------------
# FOURSQUARE GRID SEARCH (uses user key)
# -------------------------
def fetch_foursquare_grid(lat, lon, radius_km):
    url = "https://places-api.foursquare.com/places/search"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {foursquare_api_key.strip()}",
        "X-Places-Api-Version": "2025-06-17"
    }
    grid_spacing = adaptive_grid_spacing(radius_km)
    grid_points = generate_hex_grid(lat, lon, radius_km*1000, grid_spacing)
    seen_ids = set()
    results = []
    request_count = 0
    st.info(f"Foursquare: Searching {len(grid_points)} grid points...")
    progress = st.progress(0)

    for i, (plat, plon) in enumerate(grid_points):
        params = {
            "ll": f"{plat},{plon}",
            "radius": grid_spacing,
            "limit": 50,
            "sort": "DISTANCE",
            "categories": "13000"
        }

        try:
            time.sleep(0.1)
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            request_count += 1

            if i == 0 and resp.status_code != 200:
                st.error(f"Foursquare API error on first request: HTTP {resp.status_code}")
                st.error(f"Response: {resp.text[:500]}")
                st.stop()

            if resp.status_code != 200:
                st.warning(f"Foursquare HTTP {resp.status_code} at point {i}: {resp.text[:100]}")
                continue

            data = resp.json()
            for place in data.get("results", []):
                place_id = place.get("fsq_place_id") or place.get("fsq_id") or f"{place.get('name')}_{place.get('geocodes',{}).get('main',{}).get('latitude')}"
                if place_id in seen_ids:
                    continue
                seen_ids.add(place_id)

                name = place.get("name", "")
                categories = [c["name"] for c in place.get("categories", [])]
                place_lat = place.get("latitude") or place.get("geocodes", {}).get("main", {}).get("latitude")
                place_lon = place.get("longitude") or place.get("geocodes", {}).get("main", {}).get("longitude")
                loc = place.get("location", {})
                address = loc.get("formatted_address", "Address not available")
                closed = place.get("closed", False)
                date_closed = place.get("date_closed")

                if place_lat and place_lon:
                    results.append({
                        "name": name,
                        "address": address,
                        "lat": place_lat,
                        "lon": place_lon,
                        "types": categories,
                        "source": "Foursquare",
                        "closed": closed,
                        "date_closed": date_closed
                    })
        except Exception as e:
            st.warning(f"Foursquare grid error at point {i}: {e}")

        progress.progress((i+1)/len(grid_points))

    st.success(f"Foursquare: {len(results)} places found ({request_count} requests)")
    return results

# -------------------------
# GOOGLE PLACES GRID SEARCH (uses user key)
# -------------------------
def fetch_google_grid(lat, lon, radius_km):
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    grid_spacing = adaptive_grid_spacing(radius_km)
    grid_points = generate_hex_grid(lat, lon, radius_km*1000, grid_spacing)
    seen_place_ids = set()
    results = []
    request_count = 0
    st.info(f"Google: Searching {len(grid_points)} grid points...")
    progress = st.progress(0)

    for i, (plat, plon) in enumerate(grid_points):
        params = {
            "location": f"{plat},{plon}",
            "radius": grid_spacing,
            "type": "restaurant",
            "key": google_api_key
        }

        try:
            time.sleep(0.1)
            resp = requests.get(url, params=params, timeout=15)
            request_count += 1

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "OK":
                    for place in data.get("results", []):
                        place_id = place.get("place_id")
                        if place_id in seen_place_ids:
                            continue
                        seen_place_ids.add(place_id)

                        name = place.get("name", "")
                        types = place.get("types", [])
                        loc = place.get("geometry", {}).get("location", {})
                        place_lat = loc.get("lat")
                        place_lon = loc.get("lng")
                        address = place.get("vicinity", "Address not available")
                        business_status = place.get("business_status")

                        if place_lat and place_lon:
                            results.append({
                                "name": name,
                                "address": address,
                                "lat": place_lat,
                                "lon": place_lon,
                                "types": types,
                                "source": "Google",
                                "business_status": business_status
                            })
                elif data.get("status") == "OVER_QUERY_LIMIT":
                    st.warning("Google Places API quota exceeded.")
                    break
            elif resp.status_code == 429:
                time.sleep(2)
        except Exception as e:
            st.warning(f"Google grid error: {e}")

        progress.progress((i+1)/len(grid_points))

    st.success(f"Google: {len(results)} places found ({request_count} requests)")
    return results

# -------------------------
# OPENSTREETMAP (Overpass API) – unchanged, no key needed
# -------------------------
def fetch_osm_places(lat, lon, radius_km):
    overpass_url = "https://overpass-api.de/api/interpreter"
    radius_m = int(radius_km * 1000)
    query = f"""
    [out:json];
    (
      node["amenity"~"restaurant|cafe|fast_food|food_court|ice_cream|pub|bar|biergarten"](around:{radius_m},{lat},{lon});
      way["amenity"~"restaurant|cafe|fast_food|food_court|ice_cream|pub|bar|biergarten"](around:{radius_m},{lat},{lon});
      node["shop"~"bakery|confectionery|coffee|tea"](around:{radius_m},{lat},{lon});
      way["shop"~"bakery|confectionery|coffee|tea"](around:{radius_m},{lat},{lon});
    );
    out center;
    """
    try:
        st.info("Fetching from OpenStreetMap (Overpass)...")
        resp = requests.get(overpass_url, params={"data": query}, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for elem in data.get("elements", []):
                if elem["type"] == "node":
                    place_lat = elem["lat"]
                    place_lon = elem["lon"]
                else:
                    if "center" in elem:
                        place_lat = elem["center"]["lat"]
                        place_lon = elem["center"]["lon"]
                    else:
                        continue
                tags = elem.get("tags", {})
                name = tags.get("name", "Unnamed")
                if not name or name == "Unnamed":
                    continue
                address_parts = []
                if "addr:housenumber" in tags:
                    address_parts.append(tags["addr:housenumber"])
                if "addr:street" in tags:
                    address_parts.append(tags["addr:street"])
                if "addr:city" in tags:
                    address_parts.append(tags["addr:city"])
                if "addr:postcode" in tags:
                    address_parts.append(tags["addr:postcode"])
                address = ", ".join(address_parts) if address_parts else "Address not available"
                types = []
                if "amenity" in tags:
                    types.append(tags["amenity"])
                if "shop" in tags:
                    types.append(tags["shop"])
                if "cuisine" in tags:
                    types.append(tags["cuisine"])
                results.append({
                    "name": name,
                    "address": address,
                    "lat": place_lat,
                    "lon": place_lon,
                    "types": types,
                    "source": "OSM",
                    "tags": tags
                })
            st.success(f"OSM: {len(results)} places found")
            return results
        else:
            st.warning(f"Overpass API error: {resp.status_code}")
            return []
    except Exception as e:
        st.error(f"OSM fetch failed: {e}")
        return []

# -------------------------
# MAIN APP
# -------------------------
address_input = st.text_input("📍 Your location (e.g., Singapore)")
radius_input = st.slider("📏 Search radius (km)", 1, 50, 5)

if "results" not in st.session_state:
    st.session_state.results = None

if st.button("🔍 Search All Sources"):
    if not address_input:
        st.warning("Please enter a location.")
    else:
        coords = geocode_address(address_input)
        if not coords:
            st.error("Invalid address or geocoding unavailable.")
        else:
            home_lat, home_lon = coords
            st.success(f"📍 Home: {home_lat:.6f}, {home_lon:.6f}")

            # Fetch from all three sources
            with st.spinner("Searching Foursquare..."):
                fsq_places = fetch_foursquare_grid(home_lat, home_lon, radius_input)
                fsq_food = [p for p in fsq_places if is_food_place(p)]
                st.info(f"Foursquare: {len(fsq_food)} food places (out of {len(fsq_places)})")

            with st.spinner("Searching Google..."):
                google_places = fetch_google_grid(home_lat, home_lon, radius_input)
                google_food = [p for p in google_places if is_food_place(p)]
                st.info(f"Google: {len(google_food)} food places (out of {len(google_places)})")

            with st.spinner("Searching OpenStreetMap..."):
                osm_places = fetch_osm_places(home_lat, home_lon, radius_input)
                osm_food = [p for p in osm_places if is_food_place(p)]
                st.info(f"OSM: {len(osm_food)} food places (out of {len(osm_places)})")

            # Combine all food places
            all_places = fsq_food + google_food + osm_food
            st.info(f"Total food places before filters: {len(all_places)}")

            # Filter out closed venues
            open_places = []
            closed_count = 0
            for p in all_places:
                if is_venue_open(p):
                    open_places.append(p)
                else:
                    closed_count += 1
            if closed_count > 0:
                st.info(f"Removed {closed_count} closed venues")
            else:
                st.info("No closed venues found (or closure info missing)")

            st.info(f"After removing closed venues: {len(open_places)} places")

            # Apply radius filter (straight-line)
            radius_filtered = strict_radius_filter(open_places, coords, radius_input)
            st.info(f"After radius filter: {len(radius_filtered)} places")

            # Advanced deduplication (clustering by distance + name)
            deduped = cluster_and_merge(radius_filtered, max_distance_m=150, name_threshold=0.7)
            st.info(f"After deduplication: {len(deduped)} places")

            # Convert to DataFrame
            final_df = pd.DataFrame(deduped) if deduped else pd.DataFrame()

            # Compute walking distances using OSRM
            if not final_df.empty:
                osrm = OSRMClient()
                venues_list = final_df.to_dict("records")
                st.info(f"Calculating walking distances for {len(venues_list)} venues...")
                walking_dists = osrm.batch_walking_distances_chunked(home_lat, home_lon, venues_list, chunk_size=100)

                for i, dist in enumerate(walking_dists):
                    if dist is not None:
                        venues_list[i]["walking_distance_m"] = dist
                        venues_list[i]["walking_distance_km"] = round(dist / 1000, 2)
                    else:
                        venues_list[i]["walking_distance_m"] = None
                        venues_list[i]["walking_distance_km"] = venues_list[i]["distance_km"]

                # Enforce radius again based on walking distance
                within_radius = [v for v in venues_list if v["walking_distance_km"] <= radius_input]
                st.info(f"After walking distance filter: {len(within_radius)} places within {radius_input} km")

                if within_radius:
                    final_df = pd.DataFrame(within_radius)
                else:
                    final_df = pd.DataFrame()

            st.session_state.results = (coords, final_df, fsq_food, google_food, osm_food)

# -------------------------
# DISPLAY RESULTS
# -------------------------
if st.session_state.results:
    coords, df, fsq_res, google_res, osm_res = st.session_state.results
    if df.empty:
        st.warning("No food establishments found within the walking distance radius.")
    else:
        st.success(f"✅ {len(df)} unique food establishments within {radius_input} km (walking distance)")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total after filters", len(df))
        with col2:
            st.metric("Foursquare", len(df[df["source"].str.contains("Foursquare")]))
        with col3:
            st.metric("Google", len(df[df["source"].str.contains("Google")]))
        with col4:
            st.metric("OSM", len(df[df["source"].str.contains("OSM")]))

        display_cols = ["name", "address", "source"]
        if "walking_distance_km" in df.columns:
            display_cols.insert(2, "walking_distance_km")
        st.dataframe(df[display_cols].sort_values("walking_distance_km"),
                     use_container_width=True)

        with st.expander("🔍 Debug Info"):
            st.write(f"Foursquare food places: {len(fsq_res)}")
            st.write(f"Google food places: {len(google_res)}")
            st.write(f"OSM food places: {len(osm_res)}")
            st.write(f"After radius & dedupe: {len(df)}")

        m = folium.Map(location=coords, zoom_start=14)
        folium.Marker(coords, tooltip="Your Location", icon=folium.Icon(color="red")).add_to(m)
        color_map = {"Foursquare": "blue", "Google": "green", "OSM": "purple"}
        for _, row in df.iterrows():
            src = row["source"].split("+")[0]
            folium.Marker(
                [row["lat"], row["lon"]],
                tooltip=f"{row['name']} ({row['source']})",
                icon=folium.Icon(color=color_map.get(src, "gray"))
            ).add_to(m)
        st_folium(m, width=1000, height=600)
