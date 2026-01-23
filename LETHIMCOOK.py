import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from typing import List, Dict, Tuple, Set
import time
from folium import plugins
import re
from datetime import datetime

st.set_page_config(page_title="LETHIMCOOK", page_icon="🍽️", layout="wide")

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================
for key in ['searched', 'restaurants', 'user_lat', 'user_lon', 'display_name', 
            'selected_restaurant', 'api_calls', 'last_search_stats', 'last_search_term']:
    if key not in st.session_state:
        st.session_state[key] = False if key == 'searched' else [] if key == 'restaurants' else None if key not in ['api_calls', 'last_search_stats', 'last_search_term'] else {'foursquare': 0, 'google': 0, 'osm': 0} if key == 'api_calls' else {}

# ============================================================================
# CSS STYLING
# ============================================================================
st.markdown("""
<style>
.main-header{font-size:2.5rem;color:#FF6B6B;text-align:center;margin-bottom:2rem;}
.stButton>button{background-color:#FF6B6B;color:white;font-weight:bold;border-radius:10px;padding:0.5rem 2rem;}
.api-badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;margin:2px;display:inline-block;}
.google{background:#4285F4;color:white;} .foursquare{background:#F94877;color:white;} .osm{background:#7EBC6F;color:white;}
/* Custom scrollbar for restaurant list */
.restaurant-list {max-height: 600px; overflow-y: auto;}
.restaurant-list::-webkit-scrollbar {width: 8px;}
.restaurant-list::-webkit-scrollbar-track {background: #f1f1f1;}
.restaurant-list::-webkit-scrollbar-thumb {background: #FF6B6B; border-radius: 4px;}
</style>
""", unsafe_allow_html=True)

# ============================================================================
# GEOCODING FUNCTION
# ============================================================================
def geocode(address: str) -> Tuple:
    url = "https://nominatim.openstreetmap.org/search"
    try:
        r = requests.get(url, params={'q': address, 'format': 'json', 'limit': 1, 'countrycodes': 'sg'},
                        headers={'User-Agent': 'RestaurantFinderApp/1.0'}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return (float(data[0]['lat']), float(data[0]['lon']), data[0]['display_name']) if data else (None, None, None)
    except Exception as e:
        st.error(f"Geocoding error: {e}")
        return None, None, None

# ============================================================================
# DISTANCE CALCULATION
# ============================================================================
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import radians, cos, sin, asin, sqrt
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return round(6371 * c, 2)

# ============================================================================
# NAME CLEANING FOR DEDUPLICATION
# ============================================================================
def clean_name_for_comparison(name: str) -> str:
    if not name:
        return ""
    
    name = name.lower()
    remove_words = ['restaurant', 'cafe', 'bistro', 'eatery', 'kitchen', 'food', 'house', 
                   'bar & grill', 'bar', 'grill', 'diner', 'eats', 'the', 'a', 'an', 
                   'singapore', 'sg', 'pte', 'ltd', 'co.', '&', 'and']
    
    name = re.sub(r'[^\w\s]', ' ', name)
    words = name.split()
    filtered_words = [word for word in words if word not in remove_words]
    filtered_words.sort()
    
    return ' '.join(filtered_words).strip()

# ============================================================================
# IMPROVED FOOD VALIDATION WITH SPECIFIC DISH DETECTION
# ============================================================================
def validate_food_relevance(restaurant_name: str, cuisine: str, search_term: str = None) -> bool:
    """
    Enhanced validation to ensure restaurant serves the searched food
    """
    if not search_term or search_term.strip() == '':
        return True
    
    search_term = search_term.lower().strip()
    name_lower = restaurant_name.lower()
    cuisine_lower = cuisine.lower() if cuisine else ''
    
    # Common food terms that should NOT appear for unrelated searches
    food_categories = {
        'sushi': ['japanese', 'sashimi', 'nigiri', 'maki', 'roll', 'wasabi'],
        'pizza': ['italian', 'pasta', 'calzone', 'marinara'],
        'burger': ['american', 'fast food', 'fries'],
        'spaghetti': ['italian', 'pasta', 'noodle'],
        'curry': ['indian', 'thai', 'japanese', 'spicy'],
        'steak': ['western', 'grill', 'bbq', 'meat'],
        'dim sum': ['chinese', 'cantonese', 'yum cha'],
        'pho': ['vietnamese', 'noodle soup'],
        'tacos': ['mexican', 'burrito', 'tex-mex'],
        'ramen': ['japanese', 'noodle soup']
    }
    
    # Check if search term is a specific food item
    if search_term in food_categories:
        # Restaurant name shouldn't contradict the food type
        contradictory_terms = {
            'sushi': ['fish head', 'steamboat', 'hotpot', 'chinese', 'malay', 'indian'],
            'pizza': ['chinese', 'malay', 'indian', 'vegetarian', 'health'],
            'burger': ['chinese', 'malay', 'indian', 'vegetarian'],
            'spaghetti': ['chinese', 'malay', 'indian', 'rice', 'noodle']
        }
        
        if search_term in contradictory_terms:
            for term in contradictory_terms[search_term]:
                if term in name_lower:
                    return False
        
        # Check if cuisine is compatible
        if cuisine_lower and search_term in food_categories:
            if not any(food_type in cuisine_lower for food_type in food_categories[search_term]):
                # If cuisine is specified but doesn't match, be cautious
                return False
    
    # Additional checks for common mismatches
    suspicious_pairs = [
        ('sushi', ['fish head', 'steamboat']),
        ('pizza', ['chinese restaurant', 'nasi lemak']),
        ('burger', ['dim sum', 'sushi']),
        ('spaghetti', ['chinese', 'malay'])
    ]
    
    for food, contradictions in suspicious_pairs:
        if food in search_term:
            for contradiction in contradictions:
                if contradiction in name_lower:
                    return False
    
    return True

# ============================================================================
# ENHANCED RELEVANCE SCORING WITH GOOGLE VERIFICATION
# ============================================================================
def calculate_relevance_score(restaurant: Dict, search_term: str = None) -> Dict:
    score = 50
    confidence = "Unknown"
    warnings = []
    
    # ---- DATA QUALITY ----
    if restaurant.get('rating') != 'N/A' and restaurant.get('rating'):
        score += 15
    if restaurant.get('price') != 'N/A' and restaurant.get('price'):
        score += 5
    if restaurant.get('address') != 'N/A' and restaurant.get('address'):
        score += 10
    if restaurant.get('cuisine') not in ['N/A', 'Not specified', 'Restaurant']:
        score += 10
    
    # ---- FOOD RELEVANCE VALIDATION ----
    if search_term and search_term.strip():
        search_lower = search_term.lower()
        name_lower = restaurant.get('name', '').lower()
        cuisine_lower = restaurant.get('cuisine', '').lower()
        
        # Validate food relevance
        if not validate_food_relevance(restaurant.get('name', ''), 
                                       restaurant.get('cuisine', ''), 
                                       search_term):
            score -= 40
            warnings.append(f"❌ Unlikely to serve {search_term}")
        # Exact match in name
        elif search_lower in name_lower:
            score += 25
        # Exact match in cuisine
        elif search_lower in cuisine_lower:
            score += 20
        # Partial word match
        elif any(word in name_lower or word in cuisine_lower for word in search_lower.split()):
            score += 10
        else:
            score -= 15
            warnings.append(f"⚠️ '{search_term}' not found in name/cuisine")
    
    # ---- API SOURCE RELIABILITY ----
    source = restaurant.get('source', 'unknown')
    if source == 'google':
        score += 20  # Increased weight for Google
        confidence = "High"
    elif source == 'foursquare':
        score += 10
        confidence = "Medium"
    elif source == 'osm':
        score += 5
        confidence = "Low"
    
    # ---- BUSINESS STATUS CHECK (NEW) ----
    if restaurant.get('business_status') == 'CLOSED_PERMANENTLY':
        score -= 50  # Heavy penalty for permanently closed
        warnings.append("🚫 PERMANENTLY CLOSED")
    elif restaurant.get('is_open') == False:
        score -= 10
        warnings.append("⏸️ Currently closed")
    elif restaurant.get('is_open') == True:
        score += 5
    
    # ---- DISTANCE FACTOR ----
    distance = restaurant.get('distance', 999)
    if distance < 0.5:
        score += 10
    elif distance < 1:
        score += 5
    
    # ---- SUSPICIOUS NAME DETECTION ----
    name = restaurant.get('name', '').lower()
    suspicious_words = ['convenience', 'minimart', '7-eleven', 'cheers', 'fairprice', 
                       'atm', 'bank', 'clinic', 'school', 'hotel', 'motel']
    if any(word in name for word in suspicious_words):
        score -= 40
        warnings.append("🚫 Not a restaurant")
    
    # ---- CONFIDENCE LEVEL ----
    if score >= 80:
        confidence = "Very High"
    elif score >= 70:
        confidence = "High"
    elif score >= 60:
        confidence = "Medium"
    elif score >= 40:
        confidence = "Low"
    else:
        confidence = "Very Low"
    
    restaurant['relevance_score'] = score
    restaurant['confidence'] = confidence
    restaurant['warnings'] = warnings
    
    return restaurant

# ============================================================================
# ENHANCED FOURSQUARE SEARCH WITH FOOD FILTERING
# ============================================================================
def search_foursquare(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    if not api_key or not api_key.strip():
        return []

    try:
        url = "https://places-api.foursquare.com/places/search"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
            "X-Places-Api-Version": "2025-06-17"
        }

        category_list = (
            '13065,13066,13068,13070,13071,13072,13073,13076,13077,13079,'
            '13080,13081,13082,13083,13084,13085,13086,13087,13088,13089,'
            '13090,13091,13092,13093,13094,13095,13096,13097,'
            '13144,13145,13146,13147,13148,13149,13150,'
            '13303,13304,13314,13377,13378,13379,13380'
        )

        params = {
            'll': f"{lat},{lon}",
            'radius': min(radius_m, 100000),
            'categories': category_list,
            'limit': 50,
            'sort': 'POPULARITY'
        }

        # Improved search: if specific food item, use text search
        if search_term and search_term.strip():
            # Check if it's a specific food (not cuisine type)
            common_foods = ['sushi', 'pizza', 'burger', 'pasta', 'steak', 'curry', 
                           'ramen', 'pho', 'tacos', 'dim sum', 'spaghetti']
            
            if search_term.lower() in common_foods:
                params['query'] = search_term
            else:
                # For broader cuisine, use both query and categories
                params['query'] = f"{search_term} restaurant"

        r = requests.get(url, headers=headers, params=params, timeout=15)

        if r.status_code != 200:
            return []

        data = r.json()
        results = []
        
        for place in data.get('results', []):
            r_lat = place.get('latitude')
            r_lon = place.get('longitude')

            if r_lat and r_lon:
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):
                    continue

                categories = place.get('categories', [])
                cuisine = categories[0].get('name', 'Restaurant') if categories else 'Restaurant'
                
                # Skip if cuisine clearly doesn't match search term
                if search_term and search_term.strip():
                    search_lower = search_term.lower()
                    cuisine_lower = cuisine.lower()
                    name_lower = place.get('name', '').lower()
                    
                    # Enhanced filtering for specific foods
                    if not validate_food_relevance(place.get('name', ''), cuisine, search_term):
                        continue
                
                location = place.get('location', {})
                address = location.get('formatted_address', 'N/A')
                
                # Check for closed venues
                closed = place.get('closed', False)
                
                results.append({
                    'name': place.get('name', 'Unnamed'),
                    'lat': r_lat,
                    'lon': r_lon,
                    'cuisine': cuisine,
                    'address': address,
                    'rating': place.get('rating', 'N/A'),
                    'price': 'N/A',
                    'image_url': '',
                    'is_open': None if closed else place.get('hours', {}).get('is_open', None),
                    'business_status': 'CLOSED_PERMANENTLY' if closed else None,
                    'distance': distance,
                    'source': 'foursquare',
                    'fsq_id': place.get('fsq_place_id', '')
                })

        return results
        
    except Exception as e:
        return []

# ============================================================================
# ENHANCED GOOGLE PLACES SEARCH WITH DETAIL VERIFICATION
# ============================================================================
def search_google(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """
    Enhanced Google Places search with:
    1. Business status verification
    2. Menu item search capability
    3. Photo verification
    """
    if not api_key or not api_key.strip():
        return []
    
    try:
        # First: Try to search for specific food items in menus
        results = []
        
        # Try text search first for better food item matching
        if search_term and search_term.strip():
            # Use text search for specific food items
            url = "https://places.googleapis.com/v1/places:searchText"
            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.priceLevel,places.photos,places.currentOpeningHours,places.types,places.businessStatus,places.editorialSummary'
            }
            
            # Smart query building
            if len(search_term.split()) <= 2:  # Likely a food item
                query = f"{search_term} restaurant Singapore"
            else:
                query = f"{search_term} Singapore"
            
            body = {
                "textQuery": query,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": min(radius_m, 50000)
                    }
                },
                "maxResultCount": 50
            }
            
            r = requests.post(url, headers=headers, json=body, timeout=15)
            if r.status_code == 200:
                data = r.json()
                results.extend(process_google_places(data.get('places', []), lat, lon, radius_m, api_key, search_term))
        
        # Second: Also do nearby search for broader results
        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': api_key,
            'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.priceLevel,places.photos,places.currentOpeningHours,places.types,places.businessStatus'
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
        
        r = requests.post(url, headers=headers, json=body, timeout=15)
        if r.status_code == 200:
            data = r.json()
            results.extend(process_google_places(data.get('places', []), lat, lon, radius_m, api_key, search_term))
        
        return results
        
    except Exception as e:
        return []

def process_google_places(places: List, lat: float, lon: float, radius_m: int, api_key: str, search_term: str = None) -> List[Dict]:
    """Helper to process Google Places results"""
    results = []
    
    for place in places:
        loc = place.get('location', {})
        r_lat, r_lon = loc.get('latitude'), loc.get('longitude')
        
        if r_lat and r_lon:
            distance = calculate_distance(lat, lon, r_lat, r_lon)
            if distance > (radius_m / 1000):
                continue
            
            # Check business status
            business_status = place.get('businessStatus', 'OPERATIONAL')
            if business_status == 'CLOSED_PERMANENTLY':
                continue  # Skip permanently closed
            
            # Extract cuisine from types
            types = place.get('types', [])
            cuisine = 'Restaurant'
            if types:
                # Filter for restaurant-related types
                restaurant_types = [t.replace('_', ' ').title() for t in types 
                                  if any(keyword in t.lower() for keyword in ['restaurant', 'food', 'cafe', 'bar'])]
                if restaurant_types:
                    cuisine = ', '.join(restaurant_types[:2])
            
            # Food relevance check
            name = place.get('displayName', {}).get('text', 'Unnamed')
            if search_term and search_term.strip():
                if not validate_food_relevance(name, cuisine, search_term):
                    continue
            
            # Map price level
            price_map = {
                'PRICE_LEVEL_INEXPENSIVE': '$',
                'PRICE_LEVEL_MODERATE': '$$',
                'PRICE_LEVEL_EXPENSIVE': '$$$',
                'PRICE_LEVEL_VERY_EXPENSIVE': '$$$$'
            }
            price = price_map.get(place.get('priceLevel', ''), 'N/A')
            
            # Get photo
            photos = place.get('photos', [])
            photo_url = ''
            if photos and photos[0].get('name'):
                photo_url = f"https://places.googleapis.com/v1/{photos[0].get('name')}/media?key={api_key}&maxHeightPx=400"
            
            results.append({
                'name': name,
                'lat': r_lat,
                'lon': r_lon,
                'cuisine': cuisine,
                'address': place.get('formattedAddress', 'N/A'),
                'rating': place.get('rating', 'N/A'),
                'price': price,
                'image_url': photo_url,
                'is_open': place.get('currentOpeningHours', {}).get('openNow'),
                'business_status': business_status,
                'distance': distance,
                'source': 'google',
                'place_id': place.get('id', '')
            })
    
    return results

# ============================================================================
# ENHANCED OSM SEARCH WITH FILTERING
# ============================================================================
def search_osm(lat: float, lon: float, radius_m: int, search_term: str) -> List[Dict]:
    url = "https://overpass-api.de/api/interpreter"
    
    # Use smarter filtering for food items
    if search_term and search_term.strip():
        # Check if it's a specific food vs cuisine
        specific_foods = ['sushi', 'pizza', 'burger', 'spaghetti', 'pasta', 'ramen']
        if search_term.lower() in specific_foods:
            # For specific foods, use broader search and filter later
            search_filter = ""
        else:
            search_filter = f'["cuisine"~"{search_term}",i]'
    else:
        search_filter = ""
    
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
        r = requests.post(url, data={'data': query}, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        results = []
        
        for el in data.get('elements', []):
            if el['type'] == 'node':
                r_lat, r_lon = el['lat'], el['lon']
            else:
                r_lat = el.get('center', {}).get('lat')
                r_lon = el.get('center', {}).get('lon')
            
            if r_lat and r_lon:
                tags = el.get('tags', {})
                name = tags.get('name', 'Unnamed Restaurant')
                cuisine = tags.get('cuisine', 'Not specified')
                
                # Enhanced filtering
                if search_term and search_term.strip():
                    if not validate_food_relevance(name, cuisine, search_term):
                        continue
                
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
                    'business_status': 'CLOSED_PERMANENTLY' if tags.get('disused:amenity') == 'restaurant' or tags.get('abandoned:amenity') == 'restaurant' else None,
                    'distance': distance,
                    'source': 'osm',
                    'osm_id': el.get('id', ''),
                    'phone': tags.get('phone', tags.get('contact:phone', 'N/A')),
                    'website': tags.get('website', tags.get('contact:website', 'N/A')),
                    'opening_hours': tags.get('opening_hours', 'N/A')
                })
        
        return results
        
    except Exception as e:
        return []

# ============================================================================
# DEDUPLICATION FUNCTION
# ============================================================================
def deduplicate(restaurants: List[Dict]) -> List[Dict]:
    seen: Set[str] = set()
    unique = []
    
    for r in restaurants:
        cleaned_name = clean_name_for_comparison(r['name'])
        
        key_exact = f"{r['name'].lower().strip()}_{round(r['lat'], 4)}_{round(r['lon'], 4)}"
        key_approx = f"{cleaned_name}_{round(r['lat'], 3)}_{round(r['lon'], 3)}"
        
        id_key = ""
        if r.get('fsq_id'):
            id_key = f"fsq_{r['fsq_id']}"
        elif r.get('place_id'):
            id_key = f"google_{r['place_id']}"
        elif r.get('osm_id'):
            id_key = f"osm_{r['osm_id']}"
        
        is_duplicate = False
        
        if key_exact in seen:
            is_duplicate = True
        elif cleaned_name and key_approx in seen:
            for seen_key in seen:
                if key_approx in seen_key or (cleaned_name and cleaned_name in seen_key):
                    is_duplicate = True
                    break
        elif id_key and id_key in seen:
            is_duplicate = True
        
        if not is_duplicate:
            seen.add(key_exact)
            if cleaned_name:
                seen.add(key_approx)
            if id_key:
                seen.add(id_key)
            
            unique.append(r)
    
    return unique

# ============================================================================
# HYBRID SEARCH WITH AUTO-SEARCH FIX
# ============================================================================
def hybrid_search(lat: float, lon: float, radius_m: int, search_term: str, fs_key: str, g_key: str) -> Tuple[List[Dict], Dict]:
    """Main search function with automatic search fix"""
    
    # Store current search term
    st.session_state.last_search_term = search_term
    
    all_results = []
    stats = {
        'foursquare': 0,
        'google': 0,
        'osm': 0,
        'total': 0,
        'duplicates': 0,
        'filtered': 0
    }
    
    # Run all searches in parallel for speed
    import concurrent.futures
    
    def run_search(source_func, *args):
        return source_func(*args)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        
        if fs_key and fs_key.strip():
            futures.append(executor.submit(run_search, search_foursquare, lat, lon, radius_m, search_term, fs_key))
        else:
            futures.append(None)
        
        if g_key and g_key.strip():
            futures.append(executor.submit(run_search, search_google, lat, lon, radius_m, search_term, g_key))
        else:
            futures.append(None)
        
        futures.append(executor.submit(run_search, search_osm, lat, lon, radius_m, search_term))
        
        # Collect results
        if futures[0]:
            try:
                fs_results = futures[0].result(timeout=15)
                all_results.extend(fs_results)
                stats['foursquare'] = len(fs_results)
                st.session_state.api_calls['foursquare'] += 1
            except:
                pass
        
        if futures[1]:
            try:
                g_results = futures[1].result(timeout=15)
                all_results.extend(g_results)
                stats['google'] = len(g_results)
                st.session_state.api_calls['google'] += 1
            except:
                pass
        
        try:
            osm_results = futures[2].result(timeout=15)
            all_results.extend(osm_results)
            stats['osm'] = len(osm_results)
            st.session_state.api_calls['osm'] += 1
        except:
            pass
    
    stats['total'] = len(all_results)
    
    # Remove duplicates
    unique_results = deduplicate(all_results)
    stats['duplicates'] = stats['total'] - len(unique_results)
    
    # Calculate relevance scores
    unique_results = [calculate_relevance_score(r, search_term) for r in unique_results]
    
    # Filter low-quality results
    before_filter = len(unique_results)
    unique_results = [r for r in unique_results if r['relevance_score'] >= 40]
    stats['filtered'] = before_filter - len(unique_results)
    
    # Sort by relevance, then distance
    unique_results.sort(key=lambda x: (-x['relevance_score'], x['distance']))
    
    return unique_results, stats

# ============================================================================
# CREATE MAP
# ============================================================================
def create_map(user_lat: float, user_lon: float, restaurants: List[Dict], selected: Dict = None) -> folium.Map:
    center = [selected['lat'], selected['lon']] if selected else [user_lat, user_lon]
    
    m = folium.Map(
        location=center,
        zoom_start=16 if selected else 14,
        tiles='OpenStreetMap'
    )
    
    plugins.Fullscreen(position='topright', title='Fullscreen', title_cancel='Exit').add_to(m)
    
    # Your location marker
    folium.Marker(
        [user_lat, user_lon],
        popup="<b>📍 Your Location</b>",
        tooltip="🔵 You are here",
        icon=folium.Icon(color='blue', icon='home', prefix='fa')
    ).add_to(m)
    
    # Restaurant markers
    for r in restaurants:
        is_sel = selected and r['name'] == selected['name'] and abs(r['lat'] - selected['lat']) < 0.0001
        
        source_color = {'foursquare': '#F94877', 'google': '#4285F4', 'osm': '#7EBC6F'}
        
        # Build popup with confidence indicator
        confidence_emoji = {'Very High': '🟢', 'High': '🟢', 'Medium': '🟡', 
                          'Low': '🟠', 'Very Low': '🔴', 'Unknown': '⚪'}
        conf_emoji = confidence_emoji.get(r.get('confidence', 'Unknown'), '⚪')
        
        popup = f'''
        <div style="width:250px;text-align:center;">
            <h4>{r["name"]}</h4>
            <p style="color:{source_color.get(r.get('source'), '#666')};font-weight:bold;font-size:10px;">
                {r.get('source', '').upper()} • {conf_emoji} {r.get('confidence', '')}
            </p>
            <p><b>Cuisine:</b> {r.get('cuisine', 'N/A')}</p>
            <p><b>Distance:</b> {r.get('distance')} km</p>
            {f'<p>⭐ {r.get("rating")}/5</p>' if r.get('rating') != 'N/A' else ''}
            <p style="font-size:10px;color:#666;">Click to select & move to #1</p>
        </div>
        '''
        
        icon = folium.Icon(color='orange', icon='star', prefix='fa') if is_sel else folium.Icon(color='red', icon='cutlery', prefix='fa')
        tooltip = f"⭐ SELECTED: {r['name']}" if is_sel else f"🍽️ {r['name']} - {r['distance']} km"
        
        folium.Marker(
            [r['lat'], r['lon']],
            popup=folium.Popup(popup, max_width=250),
            tooltip=tooltip,
            icon=icon
        ).add_to(m)
    
    # Route line
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
# MAIN UI WITH AUTO-SEARCH FIX
# ============================================================================

# App title
st.markdown('<h1 class="main-header">🍽️ LETHIMCOOK<br><small>What would you like to eat today?</small></h1>', unsafe_allow_html=True)

# ---- SIDEBAR ----
with st.sidebar:
    st.header("🔑 API Keys")
    
    st.info("💡 **Use multiple APIs for best results!**")
    
    fs_key = st.text_input("Foursquare API Key", type="password",
                          help="Use your working Foursquare API key")
    g_key = st.text_input("Google Places API Key", type="password",
                         help="Paid after trial - Good for restaurants")
    
    # Test Foursquare API key button
    if fs_key and st.button("🧪 Test Foursquare API Key", use_container_width=True):
        with st.spinner("Testing Foursquare API..."):
            test_url = "https://places-api.foursquare.com/places/search"
            test_headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {fs_key.strip()}",
                "X-Places-Api-Version": "2025-06-17"
            }
            test_params = {'ll': '1.3521,103.8198', 'radius': 1000, 'limit': 1}
            
            try:
                test_response = requests.get(test_url, headers=test_headers, params=test_params, timeout=10)
                if test_response.status_code == 200:
                    st.success("✅ API KEY WORKS! Foursquare is responding correctly!")
                elif test_response.status_code == 401:
                    st.error("❌ 401 ERROR: Invalid API Key!")
                else:
                    st.error(f"❌ ERROR {test_response.status_code}")
            except Exception as e:
                st.error(f"Connection error: {str(e)}")
    
    st.divider()
    st.header("🔍 Search")
    
    # Search input fields - with improved labels
    address = st.text_input("📍 Location / Address", placeholder="e.g., Orchard Road, Singapore 238801")
    search_term = st.text_input("🍜 Cuisine / Specific Food Item", 
                               placeholder="e.g., sushi, pizza, spaghetti, burger")
    radius = st.slider("📏 Search Radius (km)", 1, 10, 3, 1)
    
    st.caption("💡 Tip: You can search for specific dishes like 'spaghetti' or cuisines like 'Italian'")
    
    # FIXED: Single search button that triggers immediate search
    search_btn = st.button("Cook! 👨‍🍳", use_container_width=True, type="primary")
    
    # Clear button
    if st.session_state.searched and st.button("🗑️ Clear Results", use_container_width=True):
        for key in ['searched', 'restaurants', 'selected_restaurant']:
            st.session_state[key] = False if key == 'searched' else [] if key == 'restaurants' else None
        st.rerun()

# ============================================================================
# AUTO-SEARCH FIX: Handle search immediately when button is pressed
# ============================================================================
if search_btn:
    if not address:
        st.warning("⚠️ Please enter a location!")
        st.stop()
    
    # Clear previous results
    st.session_state.searched = False
    st.session_state.restaurants = []
    st.session_state.selected_restaurant = None
    
    # Show search progress
    with st.spinner("🔍 Finding location..."):
        lat, lon, display_name = geocode(address)
    
    if not lat:
        st.error("❌ Location not found. Please try a different address.")
        st.stop()
    
    st.success(f"📍 Found: {display_name}")
    
    # Perform search
    with st.spinner(f"🍽️ Searching for '{search_term}' within {radius} km..." if search_term else f"🍽️ Searching all restaurants within {radius} km..."):
        restaurants, stats = hybrid_search(lat, lon, radius * 1000, search_term, fs_key, g_key)
    
    # Save results
    st.session_state.searched = True
    st.session_state.restaurants = restaurants
    st.session_state.user_lat = lat
    st.session_state.user_lon = lon
    st.session_state.display_name = display_name
    st.session_state.last_search_stats = stats
    
    # Show results immediately
    if restaurants:
        st.success(f"🎉 Found {len(restaurants)} restaurants!")
        # Force immediate display
        st.rerun()
    else:
        st.warning(f"No restaurants found. Try increasing radius or using a broader search term.")
        st.stop()

# ============================================================================
# DISPLAY RESULTS
# ============================================================================
if st.session_state.searched:
    # Search statistics
    if st.session_state.last_search_stats:
        stats = st.session_state.last_search_stats
        with st.expander(f"📊 Search Statistics ({len(st.session_state.restaurants)} results)"):
            cols = st.columns(5)
            metrics = [
                ("Foursquare", stats['foursquare']),
                ("Google", stats['google']),
                ("OSM", stats['osm']),
                ("Duplicates", stats['duplicates']),
                ("Filtered", stats['filtered'])
            ]
            
            for col, (label, value) in zip(cols, metrics):
                with col:
                    st.metric(label, value)
            
            st.caption(f"📍 Location: {st.session_state.display_name}")
            if st.session_state.last_search_term:
                st.caption(f"🔍 Searching for: '{st.session_state.last_search_term}'")
            st.caption(f"📏 Radius: {radius} km • Sorted by relevance")
    
    if st.session_state.restaurants:
        # Two-column layout
        col1, col2 = st.columns([2, 1])
        
        # ---- LEFT COLUMN: MAP ----
        with col1:
            st.subheader("📍 Interactive Map")
            
            if st.session_state.selected_restaurant:
                st.success(f"⭐ Selected: {st.session_state.selected_restaurant['name']}")
            else:
                st.info("💡 Click any restaurant on the map or list to select it")
            
            # Create and display map
            m = create_map(
                st.session_state.user_lat,
                st.session_state.user_lon,
                st.session_state.restaurants,
                st.session_state.selected_restaurant
            )
            map_data = st_folium(m, width=None, height=600, key="map")
            
            # Handle map clicks
            if map_data and map_data.get("last_object_clicked"):
                clicked_lat = map_data["last_object_clicked"]["lat"]
                clicked_lon = map_data["last_object_clicked"]["lng"]
                
                if abs(clicked_lat - st.session_state.user_lat) > 0.0001 or abs(clicked_lon - st.session_state.user_lon) > 0.0001:
                    for r in st.session_state.restaurants:
                        if abs(r['lat'] - clicked_lat) < 0.0001 and abs(r['lon'] - clicked_lon) < 0.0001:
                            if not st.session_state.selected_restaurant or st.session_state.selected_restaurant['name'] != r['name']:
                                st.session_state.selected_restaurant = r
                                st.rerun()
                            break
        
        # ---- RIGHT COLUMN: RESTAURANT LIST ----
        with col2:
            st.subheader("📋 Restaurant List")
            st.markdown('<div class="restaurant-list">', unsafe_allow_html=True)
            
            # Sort with selected at top
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
            
            # Display restaurants
            for idx, r in enumerate(sorted_list, 1):
                is_sel = idx == 1 and selected
                
                # Confidence indicator
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
                
                # Build expander label
                if is_sel:
                    label = f"⭐ #1 (SELECTED) - {r['name']} {conf_emoji}"
                else:
                    label = f"{idx}. {r['name']} {conf_emoji} ({score:.0f}%)"
                
                with st.expander(label, expanded=is_sel):
                    # Confidence and warnings
                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption(f"**Confidence:** {r.get('confidence', 'Unknown')}")
                    with col2:
                        st.caption(f"**Relevance:** {score:.0f}%")
                    
                    if r.get('warnings'):
                        for warning in r['warnings']:
                            st.warning(warning, icon="⚠️")
                    
                    # API source
                    st.markdown(f'<span class="api-badge {r["source"]}">{r["source"].upper()}</span>', unsafe_allow_html=True)
                    
                    # Action buttons
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if not is_sel and st.button("📍 Select", key=f"select_{idx}", use_container_width=True):
                            st.session_state.selected_restaurant = r
                            st.rerun()
                    with col_b:
                        # Google Maps directions
                        url = f"https://www.google.com/maps/dir/?api=1&origin={st.session_state.user_lat},{st.session_state.user_lon}&destination={r['lat']},{r['lon']}&travelmode=driving"
                        st.link_button("🧭 Directions", url, use_container_width=True)
                    
                    # Details
                    st.write(f"**🍽️ Cuisine:** {r['cuisine']}")
                    st.write(f"**📍 Distance:** {r['distance']} km")
                    st.write(f"**📫 Address:** {r['address']}")
                    
                    if r.get('rating') != 'N/A':
                        stars = "⭐" * int(float(r['rating']))
                        st.write(f"**Rating:** {stars} {r['rating']}/5")
                    
                    if r.get('price') != 'N/A':
                        st.write(f"**Price:** {r['price']}")
                    
                    # Business status
                    if r.get('business_status') == 'CLOSED_PERMANENTLY':
                        st.error("🚫 PERMANENTLY CLOSED")
                    elif r.get('is_open') == True:
                        st.success("● OPEN NOW")
                    elif r.get('is_open') == False:
                        st.error("● CLOSED")
                    
                    # Photo
                    if r.get('image_url'):
                        st.image(r['image_url'], use_column_width=True)
                    
                    # Additional info
                    if r.get('phone') and r['phone'] != 'N/A':
                        st.write(f"**📞 Phone:** {r['phone']}")
                    if r.get('website') and r['website'] != 'N/A':
                        st.write(f"**🌐 Website:** [Link]({r['website']})")
                    if r.get('opening_hours') and r['opening_hours'] != 'N/A':
                        st.write(f"**🕐 Hours:** {r['opening_hours']}")
            
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.warning("No restaurants found. Try a different search or increase the radius.")
else:
    # Welcome screen
    st.markdown("---")
    st.markdown('''
    <div style="text-align:center;color:#666;">
        <h3>🎯 Smart Restaurant Finder</h3>
        <p>Foursquare Places API + Google Places + OpenStreetMap</p>
        <div style="margin:2rem 0; padding:1.5rem; background:#f8f9fa; border-radius:10px;">
            <h4>🆕 Enhanced Features:</h4>
            <p>✓ <strong>Specific Food Search</strong> - Find restaurants by dish (e.g., "spaghetti")</p>
            <p>✓ <strong>Accuracy Verification</strong> - Filters out irrelevant results</p>
            <p>✓ <strong>Business Status Check</strong> - Removes permanently closed places</p>
            <p>✓ <strong>Automatic Search</strong> - One click to get results</p>
        </div>
        <p><strong>How to use:</strong></p>
        <ol style="text-align:left; max-width:600px; margin:1rem auto;">
            <li>Enter API keys (optional but recommended for best results)</li>
            <li>Enter your location or address</li>
            <li>Enter a cuisine or specific food item</li>
            <li>Set search radius</li>
            <li>Click "Cook! 👨‍🍳" to search</li>
        </ol>
    </div>
    ''', unsafe_allow_html=True)
