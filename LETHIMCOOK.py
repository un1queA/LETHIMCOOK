import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from typing import List, Dict, Tuple, Set
import time
from folium import plugins
import re

st.set_page_config(page_title="LETHIMCOOK", page_icon="🍽️", layout="wide")

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================
# This section initializes variables that persist across reruns of the app
# Think of session_state as the app's "memory" that survives button clicks
for key in ['searched', 'restaurants', 'user_lat', 'user_lon', 'display_name', 'selected_restaurant', 'api_calls', 'last_search_stats']:
    if key not in st.session_state:
        # Set default values for each variable
        st.session_state[key] = False if key == 'searched' else [] if key == 'restaurants' else None if key not in ['api_calls', 'last_search_stats'] else {'foursquare': 0, 'google': 0, 'osm': 0} if key == 'api_calls' else {}

# ============================================================================
# CSS STYLING
# ============================================================================
# Custom CSS to make the app look nicer
st.markdown("""
<style>
.main-header{font-size:2.5rem;color:#FF6B6B;text-align:center;margin-bottom:2rem;}
.stButton>button{background-color:#FF6B6B;color:white;font-weight:bold;border-radius:10px;padding:0.5rem 2rem;}
.api-badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;margin:2px;display:inline-block;}
.google{background:#4285F4;color:white;} .foursquare{background:#F94877;color:white;} .osm{background:#7EBC6F;color:white;}
</style>
""", unsafe_allow_html=True)

# ============================================================================
# GEOCODING FUNCTION
# ============================================================================
def geocode(address: str) -> Tuple:
    """
    Converts an address (like "Orchard Road") into GPS coordinates (latitude, longitude)
    Uses OpenStreetMap's Nominatim service (free geocoding API)
    
    Args:
        address: The location to search for (e.g., "Sengkang", "Marina Bay Sands")
    
    Returns:
        Tuple of (latitude, longitude, full_address_name) or (None, None, None) if not found
    """
    url = "https://nominatim.openstreetmap.org/search"
    try:
        # Make API request to Nominatim
        r = requests.get(url, params={'q': address, 'format': 'json', 'limit': 1, 'countrycodes': 'sg'},
                        headers={'User-Agent': 'RestaurantFinderApp/1.0'}, timeout=10)
        r.raise_for_status()
        data = r.json()
        
        # Extract coordinates from response
        return (float(data[0]['lat']), float(data[0]['lon']), data[0]['display_name']) if data else (None, None, None)
    except Exception as e:
        st.error(f"Geocoding error: {e}")
        return None, None, None

# ============================================================================
# DISTANCE CALCULATION
# ============================================================================
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two GPS coordinates using Haversine formula
    This accounts for the Earth's curvature (not just straight-line distance)
    
    Args:
        lat1, lon1: Your location coordinates
        lat2, lon2: Restaurant location coordinates
    
    Returns:
        Distance in kilometers, rounded to 2 decimal places
    """
    from math import radians, cos, sin, asin, sqrt
    
    # Convert degrees to radians (math functions need radians)
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    
    # Calculate differences
    dlon, dlat = lon2 - lon1, lat2 - lat1
    
    # Haversine formula
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Earth's radius in km
    return round(6371 * c, 2)

# ============================================================================
# NAME CLEANING FOR DEDUPLICATION
# ============================================================================
def clean_name_for_comparison(name: str) -> str:
    """
    Cleans restaurant names to help detect duplicates
    Example: "The Pizza Hut Restaurant & Grill" → "hut pizza"
    
    This helps match:
    - "McDonald's" and "McDonalds" 
    - "KFC (Sengkang)" and "KFC"
    - "Subway Restaurant" and "Subway"
    
    Args:
        name: Original restaurant name
    
    Returns:
        Cleaned, sorted version for comparison
    """
    if not name:
        return ""
    
    # Convert to lowercase
    name = name.lower()
    
    # Remove common filler words that don't help identify unique restaurants
    remove_words = ['restaurant', 'cafe', 'bistro', 'eatery', 'kitchen', 'food', 'house', 
                   'bar & grill', 'bar', 'grill', 'diner', 'eats', 'the', 'a', 'an', 
                   'singapore', 'sg', 'pte', 'ltd', 'co.', '&', 'and']
    
    # Remove punctuation (e.g., "McDonald's" → "mcdonalds")
    name = re.sub(r'[^\w\s]', ' ', name)
    
    # Split into words and filter out common words
    words = name.split()
    filtered_words = [word for word in words if word not in remove_words]
    
    # Sort alphabetically so "Pizza Hut" and "Hut Pizza" match
    filtered_words.sort()
    
    return ' '.join(filtered_words).strip()

# ============================================================================
# FOOD CATEGORY VALIDATION
# ============================================================================
def is_food_related_category(cuisine: str) -> bool:
    """
    Checks if a category is actually food-related
    Helps filter out non-restaurants like "7-Eleven" or "OCBC Bank"
    
    Args:
        cuisine: The category/cuisine type from API
    
    Returns:
        True if it's food-related, False if it's not a restaurant
    """
    if not cuisine or cuisine == 'N/A':
        return True  # If unknown, keep it (might be a restaurant)
    
    cuisine_lower = cuisine.lower()
    
    # List of keywords that indicate NOT a restaurant
    non_food_keywords = [
        'mobile', 'phone', 'store', 'shop', 'retail', 'electronic', 'computer',
        'clothing', 'fashion', 'apparel', 'shoe', 'accessory', 'jewelry',
        'bank', 'atm', 'financial', 'insurance', 'real estate', 'agency',
        'hospital', 'clinic', 'medical', 'dentist', 'pharmacy', 'health',
        'school', 'university', 'college', 'education', 'training',
        'gas station', 'petrol', 'service station', 'car wash', 'auto',
        'parking', 'garage', 'lot', 'transportation', 'bus station', 'mrt',
        'hotel', 'motel', 'hostel', 'lodging', 'accommodation',
        'museum', 'gallery', 'art', 'theater', 'cinema', 'movie',
        'gym', 'fitness', 'sports', 'stadium', 'arena', 'pool',
        'post office', 'mail', 'government', 'embassy', 'consulate',
        'place of worship', 'church', 'mosque', 'temple', 'synagogue',
        'beauty', 'salon', 'spa', 'barber', 'hair', 'nail'
    ]
    
    # Check if any non-food keyword appears in the cuisine
    for keyword in non_food_keywords:
        if keyword in cuisine_lower:
            return False  # This is NOT a restaurant
    
    return True  # Looks like food!

# ============================================================================
# RELEVANCE SCORING SYSTEM (NEW!)
# ============================================================================
def calculate_relevance_score(restaurant: Dict, search_term: str = None) -> Dict:
    """
    **NEW FEATURE**: Calculates how reliable and relevant each restaurant result is
    
    This scoring system helps you know which results to trust:
    - Higher score = more reliable
    - Scores below 40% are filtered out automatically
    
    **STRICT FILTERING**: If you search for a specific cuisine (e.g., "sushi"),
    restaurants that don't match are heavily penalized or filtered out entirely.
    
    Scoring factors:
    1. Data Quality (40 points max):
       - Has rating? +15 points
       - Has price info? +5 points
       - Has address? +10 points
       - Has specific cuisine? +10 points
    
    2. Search Relevance (35 points max) - **STRICTER NOW**:
       - Search term in name? +35 points
       - Search term in cuisine? +30 points
       - Partial match? +10 points
       - No match? -50 points (HEAVY PENALTY)
    
    3. API Source Reliability (15 points max):
       - Google: +15 points (strictest filtering)
       - Foursquare: +10 points
       - OSM: +5 points (user-contributed data)
    
    4. Distance Bonus (10 points max):
       - Under 0.5 km: +10 points
       - Under 1 km: +5 points
    
    5. Suspicious Name Check:
       - Contains "7-Eleven", "minimart", etc? -40 points
    
    Args:
        restaurant: Restaurant data dictionary
        search_term: What you searched for (e.g., "sushi")
    
    Returns:
        Updated restaurant dict with 'relevance_score', 'confidence', and 'warnings'
    """
    score = 50  # Everyone starts at 50%
    confidence = "Unknown"
    warnings = []
    
    # ---- DATA QUALITY SCORING ----
    if restaurant.get('rating') != 'N/A' and restaurant.get('rating'):
        score += 15  # Has customer ratings
    if restaurant.get('price') != 'N/A' and restaurant.get('price'):
        score += 5   # Has price range info
    if restaurant.get('address') != 'N/A' and restaurant.get('address'):
        score += 10  # Has full address
    if restaurant.get('cuisine') not in ['N/A', 'Not specified', 'Restaurant']:
        score += 10  # Has specific cuisine type
    
    # ---- SEARCH TERM RELEVANCE (MUCH STRICTER NOW!) ----
    if search_term and search_term.strip():
        search_lower = search_term.lower().strip()
        name_lower = restaurant.get('name', '').lower()
        cuisine_lower = restaurant.get('cuisine', '').lower()
        
        # Create search keywords (handle multi-word searches like "sushi buffet")
        search_keywords = search_lower.split()
        
        # Check for exact phrase match first
        exact_in_name = search_lower in name_lower
        exact_in_cuisine = search_lower in cuisine_lower
        
        # Check for individual keyword matches
        keywords_in_name = sum(1 for keyword in search_keywords if keyword in name_lower)
        keywords_in_cuisine = sum(1 for keyword in search_keywords if keyword in cuisine_lower)
        
        # ---- SCORING LOGIC ----
        if exact_in_name:
            # Perfect: search term in restaurant name (e.g., "Sushi Tei" when searching "sushi")
            score += 35
        elif exact_in_cuisine:
            # Great: search term in cuisine type (e.g., cuisine="Japanese Sushi Restaurant")
            score += 30
        elif keywords_in_name >= len(search_keywords):
            # Good: all keywords in name (e.g., "sushi buffet" → "Buffet Town Sushi Bar")
            score += 25
        elif keywords_in_cuisine >= len(search_keywords):
            # Good: all keywords in cuisine
            score += 20
        elif keywords_in_name > 0 or keywords_in_cuisine > 0:
            # Partial: some keywords match
            score += 10
            warnings.append(f"⚠️ Partial match for '{search_term}'")
        else:
            # BAD: No match at all - this is probably wrong!
            score -= 50  # HEAVY PENALTY (increased from -20)
            warnings.append(f"❌ '{search_term}' NOT found in name or cuisine - likely incorrect result")
        
        # ---- ADDITIONAL CONTRADICTION CHECK ----
        # If searching for specific food, check if restaurant serves something completely different
        cuisine_contradictions = {
            'sushi': ['indian', 'mexican', 'italian', 'western', 'burger', 'pizza', 'steamboat', 'hotpot', 'bbq'],
            'pizza': ['chinese', 'japanese', 'sushi', 'korean', 'thai', 'indian', 'steamboat'],
            'indian': ['japanese', 'sushi', 'chinese', 'korean', 'mexican', 'italian'],
            'chinese': ['italian', 'mexican', 'indian', 'japanese sushi'],
            'burger': ['chinese', 'japanese', 'indian', 'thai', 'korean'],
            'korean': ['italian', 'mexican', 'indian'],
            'thai': ['italian', 'mexican', 'japanese sushi'],
            'mexican': ['chinese', 'japanese', 'korean', 'thai', 'indian'],
            'steamboat': ['pizza', 'burger', 'sushi', 'mexican'],
            'bbq': ['sushi', 'pizza', 'indian curry']
        }
        
        # Check for contradictions
        for search_key, incompatible_types in cuisine_contradictions.items():
            if search_key in search_lower:
                for incompatible in incompatible_types:
                    if incompatible in name_lower or incompatible in cuisine_lower:
                        score -= 40  # Major penalty for contradictory cuisine
                        warnings.append(f"❌ CONTRADICTION: Searching '{search_term}' but restaurant appears to be {incompatible}")
                        break
    
    # ---- API SOURCE RELIABILITY ----
    source = restaurant.get('source', 'unknown')
    if source == 'google':
        score += 15
        confidence = "High"
    elif source == 'foursquare':
        score += 10
        confidence = "Medium-High"
    elif source == 'osm':
        score += 5
        confidence = "Medium"
        # OSM data is user-contributed, less reliable
        if restaurant.get('cuisine') == 'Not specified':
            warnings.append("⚠️ OSM data: cuisine not specified")
            score -= 10  # Penalize unknown cuisine when searching
    
    # ---- DISTANCE FACTOR ----
    distance = restaurant.get('distance', 999)
    if distance < 0.5:
        score += 10  # Very close
    elif distance < 1:
        score += 5   # Reasonably close
    
    # ---- SUSPICIOUS NAME DETECTION ----
    name = restaurant.get('name', '').lower()
    suspicious_words = ['convenience', 'minimart', '7-eleven', 'cheers', 'fairprice', 'cold storage']
    if any(word in name for word in suspicious_words):
        score -= 40  # Probably not a restaurant! (increased from -30)
        warnings.append("❌ Likely NOT a restaurant (convenience store detected)")
    
    # ---- SET CONFIDENCE LEVEL ----
    if score >= 80:
        confidence = "Very High"
    elif score >= 70:
        confidence = "High"
    elif score >= 60:
        confidence = "Medium"
    elif score >= 50:
        confidence = "Low"
    else:
        confidence = "Very Low"
    
    # Add scoring info to restaurant data
    restaurant['relevance_score'] = score
    restaurant['confidence'] = confidence
    restaurant['warnings'] = warnings
    
    return restaurant

# ============================================================================
# FOURSQUARE API SEARCH
# ============================================================================
def search_foursquare(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """
    Searches Foursquare Places API for restaurants
    
    How it works:
    1. Sends request to Foursquare with your location + radius
    2. Uses specific restaurant category IDs (not generic "food")
    3. Filters results by distance to ensure accuracy
    4. Removes non-food venues
    
    Args:
        lat, lon: Your GPS coordinates
        radius_m: Search radius in meters
        search_term: Cuisine to search for (optional)
        api_key: Your Foursquare API key
    
    Returns:
        List of restaurant dictionaries with name, location, cuisine, etc.
    """
    if not api_key or not api_key.strip():
        return []

    try:
        url = "https://places-api.foursquare.com/places/search"

        # Authentication headers (required by Foursquare)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
            "X-Places-Api-Version": "2025-06-17"  # API version header
        }

        # Category filter: ONLY food & drink categories
        # These are Foursquare's specific category IDs for restaurants
        category_list = (
            '13065,13066,13068,13070,13071,13072,13073,13076,13077,13079,'
            '13080,13081,13082,13083,13084,13085,13086,13087,13088,13089,'
            '13090,13091,13092,13093,13094,13095,13096,13097,'
            '13144,13145,13146,13147,13148,13149,13150,'
            '13303,13304,13314,13377,13378,13379,13380'
        )

        # Build search parameters
        params = {
            'll': f"{lat},{lon}",           # Your location
            'radius': min(radius_m, 100000), # Max 100km radius
            'categories': category_list,     # Only restaurants
            'limit': 50,                     # Max 50 results
            'sort': 'POPULARITY'             # Sort by popular places
        }

        # Add search term if provided
        if search_term and search_term.strip():
            params['query'] = search_term

        # Make the API request
        r = requests.get(url, headers=headers, params=params, timeout=15)

        # Check for errors
        if r.status_code != 200:
            st.error(f"Foursquare API Error: {r.status_code}")
            if r.text:
                st.error(f"Response: {r.text[:300]}")
            return []

        r.raise_for_status()
        data = r.json()

        results = []
        
        # Process each place in the response
        for place in data.get('results', []):
            # Get coordinates
            r_lat = place.get('latitude')
            r_lon = place.get('longitude')

            if r_lat and r_lon:
                # Calculate actual distance (API radius isn't always accurate)
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):
                    continue  # Skip if too far

                # Get cuisine from categories (use only primary category)
                categories = place.get('categories', [])
                if categories:
                    primary_category = categories[0]
                    cuisine = primary_category.get('name', 'Restaurant')
                    
                    # Filter out non-food categories
                    if not is_food_related_category(cuisine):
                        continue
                else:
                    cuisine = 'Restaurant'

                # Get address
                location = place.get('location', {})
                address = location.get('formatted_address', 'N/A')

                # Additional filtering for relevance
                skip_venue = False
                
                if search_term and search_term.strip():
                    search_lower = search_term.lower()
                    venue_cuisine_lower = cuisine.lower()
                    venue_name_lower = place.get('name', '').lower()
                    
                    # Check if search term appears in name OR cuisine
                    if (search_lower not in venue_name_lower) and (search_lower not in venue_cuisine_lower):
                        # Last chance: check for common food terms
                        food_terms = ['restaurant', 'food', 'cafe', 'bistro', 'eatery', 'kitchen', 'dining']
                        if not any(term in venue_cuisine_lower for term in food_terms):
                            skip_venue = True
                
                # Filter out obvious non-restaurants
                venue_name = place.get('name', '').lower()
                non_food_indicators = ['mobile', 'phone', 'store', 'shop', 'retail', 'electronic', 
                                      'bank', 'atm', 'clinic', 'hospital', 'school', 'hotel']
                if any(indicator in venue_name for indicator in non_food_indicators):
                    skip_venue = True
                
                if skip_venue:
                    continue

                # Add to results
                results.append({
                    'name': place.get('name', 'Unnamed'),
                    'lat': r_lat,
                    'lon': r_lon,
                    'cuisine': cuisine,
                    'address': address,
                    'rating': place.get('rating', 'N/A'),
                    'price': 'N/A',
                    'image_url': '',
                    'is_open': None,
                    'distance': distance,
                    'source': 'foursquare',
                    'fsq_id': place.get('fsq_place_id', '')
                })

        return results
        
    except requests.exceptions.RequestException as e:
        st.error(f"Foursquare network error: {str(e)[:200]}")
        return []
    except Exception as e:
        st.error(f"Foursquare error: {str(e)[:200]}")
        return []

# ============================================================================
# GOOGLE PLACES API SEARCH
# ============================================================================
def search_google(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """
    Searches Google Places API (New) for restaurants
    
    Google provides the most reliable data with:
    - Photos
    - Opening hours
    - Price levels
    - User ratings
    
    Uses two different endpoints:
    - searchText: when you search for specific cuisine
    - searchNearby: when browsing all restaurants
    
    Args:
        lat, lon: Your GPS coordinates
        radius_m: Search radius in meters
        search_term: Cuisine to search for (optional)
        api_key: Your Google Places API key
    
    Returns:
        List of restaurant dictionaries
    """
    if not api_key or not api_key.strip():
        return []
    
    try:
        # Choose endpoint based on whether there's a search term
        if search_term and search_term.strip():
            # Text search endpoint (better for specific queries)
            url = "https://places.googleapis.com/v1/places:searchText"
            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.priceLevel,places.photos,places.currentOpeningHours,places.types'
            }
            body = {
                "textQuery": f"{search_term} restaurant Singapore",
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": min(radius_m, 50000)
                    }
                },
                "maxResultCount": 50
            }
        else:
            # Nearby search endpoint (better for browsing)
            url = "https://places.googleapis.com/v1/places:searchNearby"
            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.priceLevel,places.photos,places.currentOpeningHours,places.types'
            }
            body = {
                "includedTypes": ["restaurant"],
                "maxResultCount": 50,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": min(radius_m, 50000)
                    }
                }
            }
        
        # Make API request
        r = requests.post(url, headers=headers, json=body, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        results = []
        
        # Process each place
        for place in data.get('places', []):
            loc = place.get('location', {})
            r_lat, r_lon = loc.get('latitude'), loc.get('longitude')
            
            if r_lat and r_lon:
                # Verify distance
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):
                    continue
                
                # Extract cuisine from types
                types = place.get('types', [])
                cuisine = 'Restaurant'
                if types:
                    restaurant_types = [t for t in types if 'restaurant' in t.lower() or 'food' in t.lower()]
                    if restaurant_types:
                        cuisine = restaurant_types[0].replace('_', ' ').title()
                
                # Map price level to symbols
                price_map = {
                    'PRICE_LEVEL_INEXPENSIVE': '$',
                    'PRICE_LEVEL_MODERATE': '$$',
                    'PRICE_LEVEL_EXPENSIVE': '$$$',
                    'PRICE_LEVEL_VERY_EXPENSIVE': '$$$$'
                }
                price = price_map.get(place.get('priceLevel', ''), 'N/A')
                
                # Get photo URL
                photos = place.get('photos', [])
                photo_url = f"https://places.googleapis.com/v1/{photos[0].get('name', '')}/media?key={api_key}&maxHeightPx=400" if photos and photos[0].get('name') else ''
                
                # Filter non-restaurants
                venue_name = place.get('displayName', {}).get('text', 'Unnamed').lower()
                non_food_indicators = ['mobile', 'phone', 'store', 'shop', 'retail', 'electronic', 
                                      'bank', 'atm', 'clinic', 'hospital', 'school', 'hotel']
                if any(indicator in venue_name for indicator in non_food_indicators):
                    continue
                
                results.append({
                    'name': place.get('displayName', {}).get('text', 'Unnamed'),
                    'lat': r_lat,
                    'lon': r_lon,
                    'cuisine': cuisine,
                    'address': place.get('formattedAddress', 'N/A'),
                    'rating': place.get('rating', 'N/A'),
                    'price': price,
                    'image_url': photo_url,
                    'is_open': place.get('currentOpeningHours', {}).get('openNow'),
                    'distance': distance,
                    'source': 'google',
                    'place_id': place.get('id', '')
                })
        
        return results
        
    except Exception as e:
        st.warning(f"Google Places error: {str(e)[:100]}")
        return []

# ============================================================================
# OPENSTREETMAP API SEARCH
# ============================================================================
def search_osm(lat: float, lon: float, radius_m: int, search_term: str) -> List[Dict]:
    """
    Searches OpenStreetMap using Overpass API
    
    OSM is community-contributed data (like Wikipedia for maps)
    - FREE to use (no API key needed)
    - Good coverage
    - Less reliable than Google/Foursquare
    - Often missing ratings, prices, hours
    
    Query structure:
    - Searches for nodes and ways (points and areas)
    - Filters by amenity tags: restaurant, fast_food, cafe
    - Can filter by cuisine if search term provided
    
    Args:
        lat, lon: Your GPS coordinates
        radius_m: Search radius in meters
        search_term: Cuisine to search for (optional)
    
    Returns:
        List of restaurant dictionaries
    """
    url = "https://overpass-api.de/api/interpreter"
    
    # Build cuisine filter if search term provided
    if search_term and search_term.strip():
        search_filter = f'["cuisine"~"{search_term}",i]'
    else:
        search_filter = ""
    
    # Overpass QL query (OpenStreetMap's query language)
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="restaurant"]{search_filter}(around:{radius_m},{lat},{lon});
      way["amenity"="restaurant"]{search_filter}(around:{radius_m},{lat},{lon});
      node["amenity"="fast_food"]{search_filter}(around:{radius_m},{lat},{lon});
      way["amenity"="fast_food"]{search_filter}(around:{radius_m},{lat},{lon});
      node["amenity"="cafe"]{search_filter}(around:{radius_m},{lat},{lon});
      way["amenity"="cafe"]{search_filter}(around:{radius_m},{lat},{lon});
    );
    out center;
    """
    
    try:
        # Make API request
        r = requests.post(url, data={'data': query}, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        results = []
        
        # Process each element (node or way)
        for el in data.get('elements', []):
            # Get coordinates (different for nodes vs ways)
            if el['type'] == 'node':
                r_lat, r_lon = el['lat'], el['lon']
            else:  # way (building/area)
                r_lat = el.get('center', {}).get('lat')
                r_lon = el.get('center', {}).get('lon')
            
            if r_lat and r_lon:
                tags = el.get('tags', {})
                name = tags.get('name', 'Unnamed Restaurant')
                cuisine = tags.get('cuisine', 'Not specified')
                description = tags.get('description', '')
                
                # Filter non-restaurants
                venue_name_lower = name.lower()
                non_food_indicators = ['mobile', 'phone', 'store', 'shop', 'retail', 'electronic', 
                                      'bank', 'atm', 'clinic', 'hospital', 'school', 'hotel']
                if any(indicator in venue_name_lower for indicator in non_food_indicators):
                    continue
                
                # Text filtering if search term provided
                if search_term and search_term.strip():
                    search_lower = search_term.lower()
                    if (search_lower not in name.lower() and 
                        search_lower not in cuisine.lower() and 
                        search_lower not in description.lower()):
                        continue
                
                # Verify distance
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):
                    continue
                
                results.append({
                    'name': name,
                    'lat': r_lat,
                    'lon': r_lon,
                    'cuisine': cuisine,
                    'address': f"{tags.get('addr:street', '')} {tags.get('addr:housenumber', '')}".strip() or 'N/A',
                    'rating': 'N/A',
                    'price': 'N/A',
                    'image_url': '',
                    'is_open': None,
                    'distance': distance,
                    'source': 'osm',
                    'osm_id': el.get('id', ''),
                    'phone': tags.get('phone', tags.get('contact:phone', 'N/A')),
                    'website': tags.get('website', tags.get('contact:website', 'N/A')),
                    'opening_hours': tags.get('opening_hours', 'N/A')
                })
        
        return results
        
    except Exception as e:
        st.warning(f"OpenStreetMap error: {str(e)[:100]}")
        return []

# ============================================================================
# DEDUPLICATION FUNCTION
# ============================================================================
def deduplicate(restaurants: List[Dict]) -> List[Dict]:
    """
    Removes duplicate restaurants using multiple matching strategies
    
    Problem: Same restaurant appears multiple times from different APIs
    - "McDonald's" from Google
    - "McDonalds" from Foursquare
    - "McDonald's Restaurant" from OSM
    
    Solution: Use 3 matching strategies:
    1. Exact name + exact coordinates (within ~11 meters)
    2. Cleaned name + approximate coordinates (within ~111 meters)
    3. API-specific IDs (fsq_id, place_id, osm_id)
    
    Args:
        restaurants: List of all restaurants (with duplicates)
    
    Returns:
        List of unique restaurants only
    """
    seen: Set[str] = set()  # Track what we've seen
    unique = []
    
    for r in restaurants:
        # Get cleaned name for fuzzy matching
        cleaned_name = clean_name_for_comparison(r['name'])
        
        # Create multiple matching keys
        # Strategy 1: Exact name + precise coordinates (4 decimals ~ 11m accuracy)
        key_exact = f"{r['name'].lower().strip()}_{round(r['lat'], 4)}_{round(r['lon'], 4)}"
        
        # Strategy 2: Cleaned name + approximate coordinates (3 decimals ~ 111m)
        key_approx = f"{cleaned_name}_{round(r['lat'], 3)}_{round(r['lon'], 3)}"
        
        # Strategy 3: API-specific IDs
        id_key = ""
        if r.get('fsq_id'):
            id_key = f"fsq_{r['fsq_id']}"
        elif r.get('place_id'):
            id_key = f"google_{r['place_id']}"
        elif r.get('osm_id'):
            id_key = f"osm_{r['osm_id']}"
        
        # Check if this is a duplicate
        is_duplicate = False
        
        if key_exact in seen:
            is_duplicate = True
        elif cleaned_name and key_approx in seen:
            # Additional fuzzy check
            for seen_key in seen:
                if key_approx in seen_key or (cleaned_name and cleaned_name in seen_key):
                    is_duplicate = True
                    break
        elif id_key and id_key in seen:
            is_duplicate = True
        
        if not is_duplicate:
            # Mark as seen using all strategies
            seen.add(key_exact)
            if cleaned_name:
                seen.add(key_approx)
            if id_key:
                seen.add(id_key)
            
            unique.append(r)
    
    return unique

# ============================================================================
# HYBRID SEARCH - COMBINES ALL 3 APIS (IMPROVED!)
# ============================================================================
def hybrid_search(lat: float, lon: float, radius_m: int, search_term: str, fs_key: str, g_key: str) -> Tuple[List[Dict], Dict]:
    """
    **MAIN SEARCH FUNCTION** - Combines all 3 APIs for best results
    
    How it works:
    1. Searches Foursquare (if API key provided)
    2. Searches Google Places (if API key provided)
    3. Searches OpenStreetMap (always, it's free)
    4. Combines all results
    5. Removes duplicates
    6. **NEW**: Calculates relevance scores for each result
    7. **NEW**: Filters out low-quality results (score < 40%)
    8. Sorts by relevance score, then distance
    
    Args:
        lat, lon: Your GPS coordinates
        radius_m: Search radius in meters
        search_term: What cuisine you want (optional)
        fs_key: Foursquare API key (optional)
        g_key: Google API key (optional)
    
    Returns:
        Tuple of (restaurants_list, statistics_dict)
    """
    all_results = []
    stats = {
        'foursquare': 0,
        'google': 0,
        'osm': 0,
        'total': 0,
        'duplicates': 0,
        'filtered': 0  # NEW: track how many low-quality results filtered out
    }
    
    # ---- SEARCH ALL AVAILABLE APIS ----
    
    # 1. Foursquare
    if fs_key and fs_key.strip():
        with st.spinner("🔍 Searching Foursquare..."):
            fs_results = search_foursquare(lat, lon, radius_m, search_term, fs_key)
            all_results.extend(fs_results)
            stats['foursquare'] = len(fs_results)
            st.session_state.api_calls['foursquare'] += 1
    
    # 2. Google Places
    if g_key and g_key.strip():
        with st.spinner("🔍 Searching Google Places..."):
            time.sleep(0.3)  # Rate limiting
            g_results = search_google(lat, lon, radius_m, search_term, g_key)
            all_results.extend(g_results)
            stats['google'] = len(g_results)
            st.session_state.api_calls['google'] += 1
    
    # 3. OpenStreetMap (free, always use it)
    with st.spinner("🔍 Searching OpenStreetMap..."):
        time.sleep(0.3)
        osm_results = search_osm(lat, lon, radius_m, search_term)
        all_results.extend(osm_results)
        stats['osm'] = len(osm_results)
        st.session_state.api_calls['osm'] += 1
    
    stats['total'] = len(all_results)
    
    # ---- REMOVE DUPLICATES ----
    unique_results = deduplicate(all_results)
    stats['duplicates'] = stats['total'] - len(unique_results)
    
    # ---- CALCULATE RELEVANCE SCORES (NEW!) ----
    with st.spinner("📊 Analyzing results..."):
        unique_results = [calculate_relevance_score(r, search_term) for r in unique_results]
    
    # ---- FILTER OUT LOW-QUALITY RESULTS (STRICTER NOW!) ----
    # Remove results with score < 50% when searching specific cuisine
    # Remove results with score < 40% when browsing all restaurants
    min_score = 50 if (search_term and search_term.strip()) else 40
    
    before_filter = len(unique_results)
    unique_results = [r for r in unique_results if r['relevance_score'] >= min_score]
    stats['filtered'] = before_filter - len(unique_results)
    
    # Additional logging for filtered results (optional - can help debug)
    if stats['filtered'] > 0:
        filtered_names = [r['name'] for r in [calculate_relevance_score(r, search_term) for r in deduplicate(all_results)] if r['relevance_score'] < min_score][:5]
        if filtered_names:
            # This helps you see what was filtered out - remove if too verbose
            pass  # st.info(f"Filtered out: {', '.join(filtered_names[:3])}...")
    
    # ---- SORT BY RELEVANCE, THEN DISTANCE ----
    # Higher score = better match, closer = better
    unique_results.sort(key=lambda x: (-x['relevance_score'], x['distance']))
    
    return unique_results, stats

# ============================================================================
# MAP CREATION
# ============================================================================
def create_map(user_lat: float, user_lon: float, restaurants: List[Dict], selected: Dict = None) -> folium.Map:
    """
    Creates interactive Folium map with markers
    
    Features:
    - Blue home icon for your location
    - Red fork/knife icons for restaurants
    - Orange star icon for selected restaurant
    - Route line from you to selected restaurant
    - Clickable popups with info
    - Fullscreen button
    
    Args:
        user_lat, user_lon: Your location
        restaurants: List of restaurants to show
        selected: Currently selected restaurant (if any)
    
    Returns:
        Folium map object
    """
    # Center map on selected restaurant or your location
    center = [selected['lat'], selected['lon']] if selected else [user_lat, user_lon]
    
    # Create base map
    m = folium.Map(
        location=center,
        zoom_start=16 if selected else 14,  # Zoom in if restaurant selected
        tiles='OpenStreetMap'
    )
    
    # Add fullscreen button
    plugins.Fullscreen(position='topright', title='Fullscreen', title_cancel='Exit').add_to(m)
    
    # ---- YOUR LOCATION MARKER ----
    folium.Marker(
        [user_lat, user_lon],
        popup="<b>📍 Your Location</b>",
        tooltip="🔵 You are here",
        icon=folium.Icon(color='blue', icon='home', prefix='fa')
    ).add_to(m)
    
    # ---- RESTAURANT MARKERS ----
    for r in restaurants:
        # Check if this is the selected restaurant
        is_sel = selected and r['name'] == selected['name'] and abs(r['lat'] - selected['lat']) < 0.0001
        
        # Color code by API source
        source_color = {'foursquare': '#F94877', 'google': '#4285F4', 'osm': '#7EBC6F'}
        
        # Create star rating display
        stars = "⭐" * int(float(r.get('rating', 0))) if r.get('rating') != 'N/A' else ''
        
        # Build popup HTML
        popup = f'''
        <div style="width:230px;text-align:center;">
            <h4>{r["name"]}</h4>
            <p style="color:{source_color.get(r.get('source'), '#666')};font-weight:bold;font-size:10px;">
                {r.get('source', '').upper()}
            </p>
            {f'<p>{stars} {r.get("rating")}</p>' if r.get('rating') != 'N/A' else ''}
            <p><b>Distance:</b> {r.get('distance')} km</p>
            <p style="font-size:10px;color:#666;">Click to select & move to #1</p>
        </div>
        '''
        
        # Choose icon based on selection
        icon = folium.Icon(color='orange', icon='star', prefix='fa') if is_sel else folium.Icon(color='red', icon='cutlery', prefix='fa')
        tooltip = f"⭐ SELECTED: {r['name']}" if is_sel else f"🍽️ {r['name']} - {r['distance']} km"
        
        # Add marker to map
        folium.Marker(
            [r['lat'], r['lon']],
            popup=folium.Popup(popup, max_width=250),
            tooltip=tooltip,
            icon=icon
        ).add_to(m)
    
    # ---- ROUTE LINE ----
    # Draw line from you to selected restaurant
    if selected:
        folium.PolyLine(
            [[user_lat, user_lon], [selected['lat'], selected['lon']]],
            color='blue',
            weight=4,
            opacity=0.7,
            popup=f"<b>Route:</b> {selected.get('distance')} km"
        ).add_to(m)
    
    return m

# ============================================================================
# MAIN USER INTERFACE
# ============================================================================

# App title
st.markdown('<h1 class="main-header">🍽️ LETHIMCOOK<br><small>What would you like to eat today?</small></h1>', unsafe_allow_html=True)

# ---- SIDEBAR: API KEYS & SEARCH ----
with st.sidebar:
    st.header("🔑 API Keys")
    
    st.info("💡 **Use multiple APIs for best results!**")
    
    # API key input fields
    fs_key = st.text_input("Foursquare API Key", type="password",
                          help="Use your working Foursquare API key")
    g_key = st.text_input("Google Places API Key", type="password",
                         help="Paid after trial - Good for restaurants")
    
    # Test Foursquare API key button
    if fs_key:
        if st.button("🧪 Test Foursquare API Key", use_container_width=True):
            with st.spinner("Testing Foursquare API..."):
                test_url = "https://places-api.foursquare.com/places/search"
                test_headers = {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {fs_key.strip()}",
                    "X-Places-Api-Version": "2025-06-17"
                }
                test_params = {
                    'll': '1.3521,103.8198',  # Singapore coords
                    'radius': 1000,
                    'limit': 1
                }
                
                try:
                    test_response = requests.get(test_url, headers=test_headers, params=test_params, timeout=10)
                    
                    if test_response.status_code == 200:
                        st.success("✅ API KEY WORKS! Foursquare is responding correctly!")
                    elif test_response.status_code == 401:
                        st.error("❌ 401 ERROR: Invalid API Key!")
                        st.warning("Check: key format, correct key from dashboard, Bearer prefix")
                    else:
                        st.error(f"❌ ERROR {test_response.status_code}")
                        st.write(test_response.text[:500])
                        
                except Exception as e:
                    st.error(f"Connection error: {str(e)}")
    
    st.divider()
    st.header("🔍 Search")
    
    # Search input fields
    address = st.text_input("📍 Location", placeholder="e.g., Sengkang, Orchard Road")
    search_term = st.text_input("🍜 Cuisine/Food", placeholder="e.g., sushi, pizza")
    radius = st.slider("📏 Radius (km)", 1, 10, 3, 1)
    
    st.caption(f"⚠️ Will show ALL restaurants within {radius} km")
    
    # Search button
    search_btn = st.button("Cook! 👨‍🍳", use_container_width=True)
    
    # Clear button (only show after search)
    if st.session_state.searched and st.button("🗑️ Clear", use_container_width=True):
        st.session_state.searched = False
        st.session_state.restaurants = []
        st.session_state.selected_restaurant = None
        st.rerun()

# ============================================================================
# SEARCH BUTTON HANDLER (FIXED - NO DOUBLE CLICK!)
# ============================================================================
if search_btn:
    if not address:
        st.warning("⚠️ Enter a location!")
    else:
        # Geocode the address
        with st.spinner("🔍 Finding location..."):
            time.sleep(1)
            lat, lon, display_name = geocode(address)
        
        if not lat:
            st.error("❌ Location not found in Singapore")
        else:
            st.success(f"✅ {display_name}")
            
            # Perform hybrid search
            restaurants, stats = hybrid_search(lat, lon, radius * 1000, search_term, fs_key, g_key)
            
            # Save results to session state (this automatically overwrites old results)
            st.session_state.searched = True
            st.session_state.restaurants = restaurants
            st.session_state.user_lat = lat
            st.session_state.user_lon = lon
            st.session_state.display_name = display_name
            st.session_state.selected_restaurant = None
            st.session_state.last_search_stats = stats
            
            # Show feedback
            if restaurants:
                st.success(f"🎉 Found {len(restaurants)} restaurants within {radius} km!")
            else:
                st.warning(f"No restaurants found within {radius} km. Try increasing radius or broader search.")
            
            st.rerun()

# ============================================================================
# DISPLAY RESULTS
# ============================================================================
if st.session_state.searched:
    # ---- SEARCH STATISTICS (IMPROVED) ----
    if st.session_state.last_search_stats:
        stats = st.session_state.last_search_stats
        with st.expander(f"📊 Search Statistics ({len(st.session_state.restaurants)} total results)"):
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Foursquare", stats['foursquare'])
            with col2:
                st.metric("Google", stats['google'])
            with col3:
                st.metric("OpenStreetMap", stats['osm'])
            with col4:
                st.metric("Duplicates", stats['duplicates'])
            with col5:
                st.metric("Filtered Out", stats.get('filtered', 0))
            
            st.caption(f"✅ All results within {radius} km • Sorted by relevance score")
            
            # **NEW: Reliability explanation**
            st.info("""
            **🎯 Reliability & Filtering:**
            - **Strict Filtering**: When searching specific cuisine (e.g., "sushi"), only results scoring 50%+ are shown
            - **Contradiction Detection**: Restaurants serving incompatible cuisines are filtered out
            - **Confidence Level**: Based on data quality, API source, and search match
            - **Warnings**: Red ❌ warnings indicate likely incorrect results
            
            **If results seem wrong:** Try being more specific (e.g., "japanese sushi" instead of just "sushi")
            """, icon="ℹ️")
    
    if st.session_state.restaurants:
        col1, col2 = st.columns([2, 1])
        
        # ---- LEFT COLUMN: MAP ----
        with col1:
            st.subheader("📍 Interactive Map")
            
            if st.session_state.selected_restaurant:
                st.success(f"⭐ Selected: {st.session_state.selected_restaurant['name']} ({st.session_state.selected_restaurant.get('distance')} km)")
            else:
                st.info("💡 Click any red icon to select")
            
            # Create and display map
            m = create_map(
                st.session_state.user_lat,
                st.session_state.user_lon,
                st.session_state.restaurants,
                st.session_state.selected_restaurant
            )
            map_data = st_folium(m, width=None, height=600, key="map")
            
            # Handle map marker clicks
            if map_data and map_data.get("last_object_clicked"):
                clicked_lat = map_data["last_object_clicked"]["lat"]
                clicked_lon = map_data["last_object_clicked"]["lng"]
                
                # Ignore clicks on user location marker
                if abs(clicked_lat - st.session_state.user_lat) > 0.0001 or abs(clicked_lon - st.session_state.user_lon) > 0.0001:
                    # Find which restaurant was clicked
                    for r in st.session_state.restaurants:
                        if abs(r['lat'] - clicked_lat) < 0.0001 and abs(r['lon'] - clicked_lon) < 0.0001:
                            # Select this restaurant if not already selected
                            if not st.session_state.selected_restaurant or st.session_state.selected_restaurant['name'] != r['name']:
                                st.session_state.selected_restaurant = r
                                st.success(f"✅ Selected: {r['name']}")
                                time.sleep(0.3)
                                st.rerun()
                            break
        
        # ---- RIGHT COLUMN: RESTAURANT LIST (IMPROVED) ----
        with col2:
            st.subheader("📋 Restaurant List")
            
            # Sort list: selected restaurant goes to #1
            sorted_list = []
            selected = None
            
            for r in st.session_state.restaurants:
                is_sel = bool(
                    st.session_state.selected_restaurant and 
                    r['name'] == st.session_state.selected_restaurant['name'] and
                    abs(r['lat'] - st.session_state.selected_restaurant.get('lat', 0)) < 0.0001
                )
                if is_sel:
                    selected = r
                else:
                    sorted_list.append(r)
            
            if selected:
                sorted_list.insert(0, selected)
                st.info("⭐ #1 = Selected (from map/list)")
            
            st.caption(f"Showing all {len(sorted_list)} restaurants within radius")
            
            # Display each restaurant
            for idx, r in enumerate(sorted_list, 1):
                is_sel = bool(
                    st.session_state.selected_restaurant and 
                    r['name'] == st.session_state.selected_restaurant['name'] and
                    abs(r['lat'] - st.session_state.selected_restaurant.get('lat', 0)) < 0.0001
                )
                
                # **NEW: Confidence emoji indicator**
                confidence_emoji = {
                    'Very High': '🟢',
                    'High': '🟢', 
                    'Medium': '🟡',
                    'Low': '🟠',
                    'Very Low': '🔴',
                    'Unknown': '⚪'
                }
                
                conf_emoji = confidence_emoji.get(r.get('confidence', 'Unknown'), '⚪')
                score = r.get('relevance_score', 0)
                
                # Build label with confidence indicator
                label = f"⭐ #1 (SELECTED) - {r['name']} {conf_emoji}" if is_sel and idx == 1 else f"{idx}. {r['name']} {conf_emoji} ({score:.0f}%)"
                
                with st.expander(label, expanded=is_sel):
                    # **NEW: Show confidence and relevance score**
                    col_conf, col_score = st.columns(2)
                    with col_conf:
                        st.caption(f"**Confidence:** {r.get('confidence', 'Unknown')}")
                    with col_score:
                        st.caption(f"**Relevance:** {r.get('relevance_score', 0):.0f}%")
                    
                    # **NEW: Show warnings if any**
                    if r.get('warnings'):
                        for warning in r['warnings']:
                            st.warning(warning, icon="⚠️")
                    
                    # API source badge
                    st.markdown(f'<span class="api-badge {r["source"]}">{r["source"].upper()}</span>', unsafe_allow_html=True)
                    
                    # Action buttons
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("📍 Select", key=f"s{idx}"):
                            st.session_state.selected_restaurant = r
                            st.rerun()
                    with col_b:
                        # Google Maps directions link
                        url = f"https://www.google.com/maps/dir/?api=1&origin={st.session_state.user_lat},{st.session_state.user_lon}&destination={r['lat']},{r['lon']}&travelmode=driving"
                        st.link_button("🧭 Directions", url)
                    
                    if is_sel:
                        st.success("✅ Currently selected!")
                    
                    st.divider()
                    
                    # Restaurant details
                    st.write(f"**🍽️ Cuisine:** {r['cuisine']}")
                    st.write(f"**📍 Distance:** {r['distance']} km")
                    st.write(f"**📫 Address:** {r['address']}")
                    
                    if r.get('rating') != 'N/A':
                        stars = "⭐" * int(float(r['rating']))
                        st.write(f"**Rating:** {stars} {r['rating']}/5")
                    
                    if r.get('price') != 'N/A':
                        st.write(f"**Price:** {r['price']}")
                    
                    # Opening status
                    if r.get('is_open') == True:
                        st.success("● OPEN NOW")
                    elif r.get('is_open') == False:
                        st.error("● CLOSED")
                    
                    # Photo
                    if r.get('image_url'):
                        st.image(r['image_url'], use_column_width=True)
                    
                    # Additional info (mainly from OSM)
                    if r.get('phone') and r['phone'] != 'N/A':
                        st.write(f"**📞 Phone:** {r['phone']}")
                    if r.get('website') and r['website'] != 'N/A':
                        st.write(f"**🌐 Website:** [Link]({r['website']})")
                    if r.get('opening_hours') and r['opening_hours'] != 'N/A':
                        st.write(f"**🕐 Hours:** {r['opening_hours']}")

else:
    # Welcome screen (before first search)
    st.markdown("---")
    st.markdown('''
    <div style="text-align:center;color:#666;">
        <p>Hybrid Multi-API System with Smart Filters & Reliability Scoring</p>
        <p>Foursquare Places API + Google Places + OpenStreetMap</p>
        <p style="margin-top:1rem;"><strong>NEW:</strong> Relevance scoring & quality filtering!</p>
    </div>
    ''', unsafe_allow_html=True)
