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
            'selected_restaurant', 'api_calls', 'last_search_stats', 'search_params']:
    if key not in st.session_state:
        st.session_state[key] = False if key == 'searched' else [] if key == 'restaurants' else None if key not in ['api_calls', 'last_search_stats', 'search_params'] else {'foursquare': 0, 'google': 0, 'osm': 0} if key == 'api_calls' else {} if key == 'last_search_stats' else {'address': '', 'search_term': '', 'radius': 3}

# ============================================================================
# CSS STYLING
# ============================================================================
st.markdown("""
<style>
.main-header{font-size:2.5rem;color:#FF6B6B;text-align:center;margin-bottom:2rem;}
.stButton>button{background-color:#FF6B6B;color:white;font-weight:bold;border-radius:10px;padding:0.5rem 2rem;}
.api-badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;margin:2px;display:inline-block;}
.google{background:#4285F4;color:white;} .foursquare{background:#F94877;color:white;} .osm{background:#7EBC6F;color:white;}
.selected-restaurant {background-color: #fff3cd !important; border-left: 4px solid #ffc107 !important;}
.highlighted {animation: pulse 1s infinite;}
@keyframes pulse {0% {background-color: #fff3cd;} 50% {background-color: #ffeaa7;} 100% {background-color: #fff3cd;}}
</style>
""", unsafe_allow_html=True)

# ============================================================================
# GEOCODING FUNCTION
# ============================================================================
def geocode(address: str) -> Tuple:
    """Convert address to GPS coordinates"""
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
    """Calculate distance between two coordinates using Haversine formula"""
    from math import radians, cos, sin, asin, sqrt
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return round(6371 * c, 2)

# ============================================================================
# MENU/FOOD ITEM VALIDATION (NEW FUNCTION)
# ============================================================================
def check_food_item_in_menu(restaurant_data: Dict, food_item: str) -> bool:
    """
    Check if a specific food item is likely served by a restaurant
    
    Strategies:
    1. Check if food item is in restaurant name
    2. Check if food item is in cuisine type
    3. For Google Places, check if search term was used
    4. For Foursquare, check if query was used
    
    Args:
        restaurant_data: Restaurant information
        food_item: Specific food item to check (e.g., "sushi", "spaghetti")
    
    Returns:
        True if restaurant likely serves the food item
    """
    if not food_item or not food_item.strip():
        return True  # No specific food search, show all
    
    food_lower = food_item.lower().strip()
    name_lower = restaurant_data.get('name', '').lower()
    cuisine_lower = restaurant_data.get('cuisine', '').lower()
    
    # Strategy 1: Direct match in name
    if food_lower in name_lower:
        return True
    
    # Strategy 2: Match in cuisine type
    if food_lower in cuisine_lower:
        return True
    
    # Strategy 3: Check for common associations
    food_associations = {
        'sushi': ['japanese', 'sashimi', 'nigiri', 'maki', 'roll'],
        'pizza': ['italian', 'pizzeria', 'oven'],
        'burger': ['burger', 'grill', 'american', 'fast food'],
        'spaghetti': ['italian', 'pasta', 'noodle'],
        'curry': ['indian', 'thai', 'japanese', 'spicy'],
        'nasi lemak': ['malay', 'malaysian', 'rice'],
        'chicken rice': ['chinese', 'hainanese', 'rice'],
        'dim sum': ['chinese', 'cantonese', 'dumpling'],
        'ramen': ['japanese', 'noodle', 'soup'],
        'tacos': ['mexican', 'tex-mex', 'taco'],
        'pho': ['vietnamese', 'noodle soup', 'vietnam'],
        'kebab': ['middle eastern', 'turkey', 'arab', 'kebab'],
        'steak': ['western', 'grill', 'steakhouse', 'beef'],
        'seafood': ['seafood', 'fish', 'prawn', 'crab', 'lobster'],
        'vegetarian': ['vegetarian', 'vegan', 'healthy', 'salad']
    }
    
    # Check if the food item has known associations
    for food_key, associations in food_associations.items():
        if food_key in food_lower:
            # Check if any association matches cuisine
            if any(assoc in cuisine_lower for assoc in associations):
                return True
    
    # Strategy 4: Check source-specific data
    if restaurant_data.get('source') == 'google' and restaurant_data.get('place_id'):
        # Google Places was queried with the search term, so likely relevant
        return True
    
    if restaurant_data.get('source') == 'foursquare' and restaurant_data.get('fsq_id'):
        # Foursquare was queried with the search term
        return True
    
    # Strategy 5: Check for obvious mismatches
    obvious_mismatches = [
        ('sushi', ['fishhead', 'steamboat', 'hotpot', 'chinese', 'malay', 'indian']),
        ('pizza', ['chinese', 'indian', 'malay', 'seafood restaurant']),
        ('burger', ['fine dining', 'seafood', 'vegetarian']),
        ('spaghetti', ['chinese', 'indian', 'malay', 'fast food'])
    ]
    
    for search_food, not_likely in obvious_mismatches:
        if search_food in food_lower:
            if any(not_term in name_lower or not_term in cuisine_lower for not_term in not_likely):
                return False
    
    return False  # Default: not likely to serve the food item

# ============================================================================
# NAME CLEANING FOR DEDUPLICATION
# ============================================================================
def clean_name_for_comparison(name: str) -> str:
    """Cleans restaurant names to help detect duplicates"""
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
# FOOD CATEGORY VALIDATION
# ============================================================================
def is_food_related_category(cuisine: str) -> bool:
    """Checks if a category is actually food-related"""
    if not cuisine or cuisine == 'N/A':
        return True
    
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
        'beauty', 'salon', 'spa', 'barber', 'hair', 'nail',
        '7-eleven', 'cheers', 'fairprice', 'giant', 'cold storage', 'supermarket',
        'minimart', 'convenience store', 'pharmacy', 'watson', 'guardian'
    ]
    
    for keyword in non_food_keywords:
        if keyword in cuisine_lower:
            return False
    
    return True

# ============================================================================
# RESTAURANT STATUS CHECK (NEW FUNCTION)
# ============================================================================
def check_restaurant_status(restaurant: Dict) -> Dict:
    """
    Check if restaurant is likely closed based on various indicators
    
    Indicators:
    1. No recent reviews/updates
    2. "Permanently closed" in name
    3. Very low rating with no recent data
    
    Args:
        restaurant: Restaurant data
    
    Returns:
        Updated restaurant dict with status flags
    """
    name_lower = restaurant.get('name', '').lower()
    
    # Check for obvious closed indicators in name
    closed_indicators = ['permanently closed', 'closed down', 'shut down', 
                        'no longer operating', 'formerly', 'ex-', 'previous']
    
    for indicator in closed_indicators:
        if indicator in name_lower:
            restaurant['likely_closed'] = True
            restaurant['status_warning'] = f"May be closed (found '{indicator}' in name)"
            return restaurant
    
    # Check rating - extremely low ratings might indicate closed places
    rating = restaurant.get('rating')
    if rating and rating != 'N/A':
        try:
            if float(rating) < 2.0 and restaurant.get('source') == 'google':
                restaurant['status_warning'] = "Very low rating - may be problematic"
        except:
            pass
    
    restaurant['likely_closed'] = False
    return restaurant

# ============================================================================
# ENHANCED RELEVANCE SCORING
# ============================================================================
def calculate_relevance_score(restaurant: Dict, search_term: str = None) -> Dict:
    """Calculates how reliable and relevant each restaurant result is"""
    score = 50
    confidence = "Unknown"
    warnings = []
    
    # DATA QUALITY SCORING
    if restaurant.get('rating') != 'N/A' and restaurant.get('rating'):
        score += 15
    if restaurant.get('price') != 'N/A' and restaurant.get('price'):
        score += 5
    if restaurant.get('address') != 'N/A' and restaurant.get('address'):
        score += 10
    if restaurant.get('cuisine') not in ['N/A', 'Not specified', 'Restaurant']:
        score += 10
    
    # FOOD ITEM SPECIFIC SCORING (NEW)
    if search_term and search_term.strip():
        search_lower = search_term.lower()
        name_lower = restaurant.get('name', '').lower()
        cuisine_lower = restaurant.get('cuisine', '').lower()
        
        # Check if restaurant serves the specific food item
        serves_food_item = check_food_item_in_menu(restaurant, search_term)
        
        if not serves_food_item:
            score -= 40  # Heavy penalty for unlikely matches
            warnings.append(f"⚠️ Unlikely to serve '{search_term}'")
        elif search_lower in name_lower:
            score += 25  # Bonus for exact match in name
        elif search_lower in cuisine_lower:
            score += 20  # Bonus for match in cuisine
        elif any(word in name_lower or word in cuisine_lower for word in search_lower.split()):
            score += 10  # Partial match
    
    # API SOURCE RELIABILITY
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
        if restaurant.get('cuisine') == 'Not specified':
            warnings.append("⚠️ OSM data: cuisine not specified")
    
    # DISTANCE FACTOR
    distance = restaurant.get('distance', 999)
    if distance < 0.5:
        score += 10
    elif distance < 1:
        score += 5
    
    # SUSPICIOUS NAME DETECTION
    name = restaurant.get('name', '').lower()
    suspicious_words = ['convenience', 'minimart', '7-eleven', 'cheers', 'fairprice',
                       'supermarket', 'giant', 'cold storage', 'guardian', 'watson']
    if any(word in name for word in suspicious_words):
        score -= 40
        warnings.append("⚠️ Likely not a restaurant")
    
    # CLOSED STATUS DETECTION
    restaurant = check_restaurant_status(restaurant)
    if restaurant.get('likely_closed'):
        score -= 50  # Very heavy penalty for likely closed places
        warnings.append("🚫 May be permanently closed")
    
    # SET CONFIDENCE LEVEL
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
    
    restaurant['relevance_score'] = score
    restaurant['confidence'] = confidence
    restaurant['warnings'] = warnings
    
    return restaurant

# ============================================================================
# FOURSQUARE API SEARCH (ENHANCED)
# ============================================================================
def search_foursquare(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """Searches Foursquare Places API for restaurants"""
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

        # Enhanced search: if specific food item, use query
        if search_term and search_term.strip():
            params['query'] = f"{search_term} restaurant Singapore"

        r = requests.get(url, headers=headers, params=params, timeout=15)
        
        if r.status_code != 200:
            st.error(f"Foursquare API Error: {r.status_code}")
            return []
        
        r.raise_for_status()
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
                
                if not is_food_related_category(cuisine):
                    continue

                location = place.get('location', {})
                address = location.get('formatted_address', 'N/A')
                
                # Check if specific food item is likely served
                if search_term and search_term.strip():
                    venue_data = {
                        'name': place.get('name', ''),
                        'cuisine': cuisine,
                        'source': 'foursquare'
                    }
                    if not check_food_item_in_menu(venue_data, search_term):
                        continue

                # Filter out obvious non-restaurants
                venue_name = place.get('name', '').lower()
                non_food_indicators = ['mobile', 'phone', 'store', 'shop', 'retail', 'electronic', 
                                      'bank', 'atm', 'clinic', 'hospital', 'school', 'hotel',
                                      '7-eleven', 'cheers', 'fairprice', 'minimart']
                if any(indicator in venue_name for indicator in non_food_indicators):
                    continue

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
                    'fsq_id': place.get('fsq_place_id', ''),
                    'timestamp': datetime.now().isoformat()
                })

        return results
        
    except Exception as e:
        st.error(f"Foursquare error: {str(e)[:200]}")
        return []

# ============================================================================
# GOOGLE PLACES API SEARCH (ENHANCED)
# ============================================================================
def search_google(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """Searches Google Places API for restaurants with food item filtering"""
    if not api_key or not api_key.strip():
        return []
    
    try:
        # Always use textQuery for better food-specific searches
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': api_key,
            'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.priceLevel,places.photos,places.currentOpeningHours,places.types,places.primaryTypeDisplayName'
        }
        
        # Enhanced query: search for food item specifically
        query_text = f"{search_term} restaurant" if search_term and search_term.strip() else "restaurant"
        body = {
            "textQuery": f"{query_text} Singapore",
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": min(radius_m, 50000)
                }
            },
            "maxResultCount": 50
        }
        
        r = requests.post(url, headers=headers, json=body, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        results = []
        
        for place in data.get('places', []):
            loc = place.get('location', {})
            r_lat, r_lon = loc.get('latitude'), loc.get('longitude')
            
            if r_lat and r_lon:
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):
                    continue
                
                # Get primary type
                primary_type = place.get('primaryTypeDisplayName', {}).get('text', 'Restaurant')
                types = place.get('types', [])
                
                # Skip if not restaurant/food related
                if not any(t in ['restaurant', 'food', 'cafe', 'bar', 'meal_takeaway', 'meal_delivery'] for t in types):
                    continue
                
                # Map price level
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
                
                # Check if specific food item is likely served
                venue_data = {
                    'name': place.get('displayName', {}).get('text', ''),
                    'cuisine': primary_type,
                    'source': 'google',
                    'place_id': place.get('id', '')
                }
                
                if search_term and search_term.strip():
                    if not check_food_item_in_menu(venue_data, search_term):
                        continue
                
                results.append({
                    'name': place.get('displayName', {}).get('text', 'Unnamed'),
                    'lat': r_lat,
                    'lon': r_lon,
                    'cuisine': primary_type,
                    'address': place.get('formattedAddress', 'N/A'),
                    'rating': place.get('rating', 'N/A'),
                    'price': price,
                    'image_url': photo_url,
                    'is_open': place.get('currentOpeningHours', {}).get('openNow'),
                    'distance': distance,
                    'source': 'google',
                    'place_id': place.get('id', ''),
                    'timestamp': datetime.now().isoformat()
                })
        
        return results
        
    except Exception as e:
        st.warning(f"Google Places error: {str(e)[:100]}")
        return []

# ============================================================================
# OPENSTREETMAP API SEARCH (ENHANCED)
# ============================================================================
def search_osm(lat: float, lon: float, radius_m: int, search_term: str) -> List[Dict]:
    """Searches OpenStreetMap with food item filtering"""
    url = "https://overpass-api.de/api/interpreter"
    
    # Enhanced query: search by cuisine if specific food item
    if search_term and search_term.strip():
        # Try to map common food items to cuisine types
        cuisine_mapping = {
            'sushi': 'japanese',
            'pizza': 'italian',
            'burger': 'burger',
            'spaghetti': 'italian',
            'curry': 'indian',
            'nasi lemak': 'malaysian',
            'chicken rice': 'chinese',
            'dim sum': 'chinese',
            'ramen': 'japanese',
            'tacos': 'mexican',
            'pho': 'vietnamese',
            'kebab': 'kebab'
        }
        
        cuisine_filter = ""
        for food, cuisine in cuisine_mapping.items():
            if food in search_term.lower():
                cuisine_filter = f'["cuisine"~"{cuisine}",i]'
                break
        
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="restaurant"]{cuisine_filter}(around:{radius_m},{lat},{lon});
          way["amenity"="restaurant"]{cuisine_filter}(around:{radius_m},{lat},{lon});
          node["amenity"="fast_food"]{cuisine_filter}(around:{radius_m},{lat},{lon});
          way["amenity"="fast_food"]{cuisine_filter}(around:{radius_m},{lat},{lon});
          node["amenity"="cafe"]{cuisine_filter}(around:{radius_m},{lat},{lon});
          way["amenity"="cafe"]{cuisine_filter}(around:{radius_m},{lat},{lon});
        );
        out center;
        """
    else:
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="restaurant"](around:{radius_m},{lat},{lon});
          way["amenity"="restaurant"](around:{radius_m},{lat},{lon});
          node["amenity"="fast_food"](around:{radius_m},{lat},{lon});
          way["amenity"="fast_food"](around:{radius_m},{lat},{lon});
          node["amenity"="cafe"](around:{radius_m},{lat},{lon});
          way["amenity"="cafe"](around:{radius_m},{lat},{lon});
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
                
                # Check if specific food item is likely served
                venue_data = {
                    'name': name,
                    'cuisine': tags.get('cuisine', 'Not specified'),
                    'source': 'osm'
                }
                
                if search_term and search_term.strip():
                    if not check_food_item_in_menu(venue_data, search_term):
                        continue
                
                # Filter non-restaurants
                name_lower = name.lower()
                if any(word in name_lower for word in ['7-eleven', 'cheers', 'fairprice', 'minimart', 'convenience']):
                    continue
                
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):
                    continue
                
                results.append({
                    'name': name,
                    'lat': r_lat,
                    'lon': r_lon,
                    'cuisine': tags.get('cuisine', 'Not specified'),
                    'address': f"{tags.get('addr:street', '')} {tags.get('addr:housenumber', '')}".strip() or 'N/A',
                    'rating': 'N/A',
                    'price': 'N/A',
                    'image_url': '',
                    'is_open': None,
                    'distance': distance,
                    'source': 'osm',
                    'osm_id': el.get('id', ''),
                    'timestamp': datetime.now().isoformat()
                })
        
        return results
        
    except Exception as e:
        st.warning(f"OpenStreetMap error: {str(e)[:100]}")
        return []

# ============================================================================
# DEDUPLICATION FUNCTION
# ============================================================================
def deduplicate(restaurants: List[Dict]) -> List[Dict]:
    """Removes duplicate restaurants"""
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
# AUTO-SEARCH FUNCTIONALITY
# ============================================================================
def perform_search(address: str, search_term: str, radius: int, fs_key: str, g_key: str):
    """Perform search and update session state"""
    if not address:
        st.warning("⚠️ Enter a location!")
        return
    
    # Store search parameters
    st.session_state.search_params = {
        'address': address,
        'search_term': search_term,
        'radius': radius
    }
    
    with st.spinner("🔍 Finding location..."):
        lat, lon, display_name = geocode(address)
    
    if not lat:
        st.error("❌ Location not found in Singapore")
        return
    
    st.success(f"✅ {display_name}")
    
    # Perform hybrid search
    restaurants, stats = hybrid_search(lat, lon, radius * 1000, search_term, fs_key, g_key)
    
    # Save results to session state
    st.session_state.searched = True
    st.session_state.restaurants = restaurants
    st.session_state.user_lat = lat
    st.session_state.user_lon = lon
    st.session_state.display_name = display_name
    st.session_state.selected_restaurant = None
    st.session_state.last_search_stats = stats

# ============================================================================
# HYBRID SEARCH
# ============================================================================
def hybrid_search(lat: float, lon: float, radius_m: int, search_term: str, fs_key: str, g_key: str) -> Tuple[List[Dict], Dict]:
    """Combines all 3 APIs for best results"""
    all_results = []
    stats = {
        'foursquare': 0,
        'google': 0,
        'osm': 0,
        'total': 0,
        'duplicates': 0,
        'filtered': 0
    }
    
    # Search all available APIs
    if fs_key and fs_key.strip():
        with st.spinner("🔍 Searching Foursquare..."):
            fs_results = search_foursquare(lat, lon, radius_m, search_term, fs_key)
            all_results.extend(fs_results)
            stats['foursquare'] = len(fs_results)
            st.session_state.api_calls['foursquare'] += 1
    
    if g_key and g_key.strip():
        with st.spinner("🔍 Searching Google Places..."):
            time.sleep(0.3)
            g_results = search_google(lat, lon, radius_m, search_term, g_key)
            all_results.extend(g_results)
            stats['google'] = len(g_results)
            st.session_state.api_calls['google'] += 1
    
    with st.spinner("🔍 Searching OpenStreetMap..."):
        time.sleep(0.3)
        osm_results = search_osm(lat, lon, radius_m, search_term)
        all_results.extend(osm_results)
        stats['osm'] = len(osm_results)
        st.session_state.api_calls['osm'] += 1
    
    stats['total'] = len(all_results)
    
    # Remove duplicates
    unique_results = deduplicate(all_results)
    stats['duplicates'] = stats['total'] - len(unique_results)
    
    # Calculate relevance scores
    with st.spinner("📊 Analyzing results..."):
        unique_results = [calculate_relevance_score(r, search_term) for r in unique_results]
    
    # Filter out low-quality results
    before_filter = len(unique_results)
    unique_results = [r for r in unique_results if r['relevance_score'] >= 40]
    stats['filtered'] = before_filter - len(unique_results)
    
    # Sort by relevance, then distance
    unique_results.sort(key=lambda x: (-x['relevance_score'], x['distance']))
    
    return unique_results, stats

# ============================================================================
# MAP CREATION
# ============================================================================
def create_map(user_lat: float, user_lon: float, restaurants: List[Dict], selected: Dict = None) -> folium.Map:
    """Creates interactive Folium map with markers"""
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
        stars = "⭐" * int(float(r.get('rating', 0))) if r.get('rating') != 'N/A' else ''
        
        popup = f'''
        <div style="width:230px;text-align:center;">
            <h4>{r["name"]}</h4>
            <p style="color:{source_color.get(r.get('source'), '#666')};font-weight:bold;font-size:10px;">
                {r.get('source', '').upper()} • {r.get('confidence', 'N/A')}
            </p>
            {f'<p>{stars} {r.get("rating")}</p>' if r.get('rating') != 'N/A' else ''}
            <p><b>Distance:</b> {r.get('distance')} km</p>
            <p><b>Relevance:</b> {r.get('relevance_score', 0):.0f}%</p>
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
    
    # Route line to selected restaurant
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
    
    fs_key = st.text_input("Foursquare API Key", type="password",
                          help="Use your working Foursquare API key")
    g_key = st.text_input("Google Places API Key", type="password",
                         help="Paid after trial - Good for restaurants")
    
    if fs_key:
        if st.button("🧪 Test Foursquare API Key", use_container_width=True):
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
    
    # Get previous search parameters if available
    prev_params = st.session_state.get('search_params', {'address': '', 'search_term': '', 'radius': 3})
    
    address = st.text_input("📍 Location", placeholder="e.g., Sengkang, Orchard Road", 
                           value=prev_params['address'])
    search_term = st.text_input("🍜 Cuisine/Food", placeholder="e.g., sushi, pizza, spaghetti", 
                               value=prev_params['search_term'],
                               help="Search for specific cuisine OR food item (e.g., 'spaghetti', 'sushi')")
    radius = st.slider("📏 Radius (km)", 1, 10, prev_params['radius'], 1)
    
    st.caption(f"⚠️ Will search within {radius} km radius")
    
    # Search button - performs auto-search
    search_btn = st.button("Cook! 👨‍🍳", use_container_width=True, type="primary")
    
    # If search button is clicked, perform search immediately
    if search_btn:
        perform_search(address, search_term, radius, fs_key, g_key)
        st.rerun()
    
    # Clear button
    if st.session_state.searched and st.button("🗑️ Clear Results", use_container_width=True):
        st.session_state.searched = False
        st.session_state.restaurants = []
        st.session_state.selected_restaurant = None
        st.session_state.search_params = {'address': '', 'search_term': '', 'radius': 3}
        st.rerun()

# ============================================================================
# DISPLAY RESULTS
# ============================================================================
if st.session_state.searched:
    # Show search statistics
    if st.session_state.last_search_stats:
        stats = st.session_state.last_search_stats
        with st.expander(f"📊 Search Statistics ({len(st.session_state.restaurants)} results)"):
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
                st.metric("Filtered", stats.get('filtered', 0))
            
            # Show current search info
            st.info(f"📍 **Location:** {st.session_state.display_name}")
            if st.session_state.search_params.get('search_term'):
                st.info(f"🍜 **Searching for:** {st.session_state.search_params['search_term']}")
            st.info(f"📏 **Radius:** {st.session_state.search_params.get('radius', 3)} km")
    
    if st.session_state.restaurants:
        col1, col2 = st.columns([2, 1])
        
        # ---- LEFT COLUMN: MAP ----
        with col1:
            st.subheader("📍 Interactive Map")
            
            if st.session_state.selected_restaurant:
                st.success(f"⭐ Selected: {st.session_state.selected_restaurant['name']} ({st.session_state.selected_restaurant.get('distance')} km)")
            else:
                st.info("💡 Click any restaurant icon to select it")
            
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
                            if not st.session_state.selected_restaurant or st.session_state.selected_restaurant['name'] != r['name']:
                                st.session_state.selected_restaurant = r
                                st.success(f"✅ Selected: {r['name']}")
                                time.sleep(0.3)
                                st.rerun()
                            break
        
        # ---- RIGHT COLUMN: RESTAURANT LIST ----
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
                st.info("⭐ #1 = Selected (clicked from map/list)")
            
            st.caption(f"Showing {len(sorted_list)} restaurants sorted by relevance")
            
            # Display each restaurant
            for idx, r in enumerate(sorted_list, 1):
                is_sel = bool(
                    st.session_state.selected_restaurant and 
                    r['name'] == st.session_state.selected_restaurant['name'] and
                    abs(r['lat'] - st.session_state.selected_restaurant.get('lat', 0)) < 0.0001
                )
                
                # Confidence emoji indicator
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
                
                # Build label with selection indicator
                if is_sel and idx == 1:
                    label = f"⭐ **#1 (SELECTED) - {r['name']}** {conf_emoji}"
                else:
                    label = f"{idx}. {r['name']} {conf_emoji} ({score:.0f}%)"
                
                # Apply CSS class for selected restaurant
                expander_key = f"exp_{idx}_{r['name'].replace(' ', '_')}"
                
                with st.expander(label, expanded=is_sel, key=expander_key):
                    # Show confidence and relevance score
                    col_conf, col_score = st.columns(2)
                    with col_conf:
                        st.caption(f"**Confidence:** {r.get('confidence', 'Unknown')}")
                    with col_score:
                        st.caption(f"**Relevance:** {r.get('relevance_score', 0):.0f}%")
                    
                    # Show warnings if any
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
                    
                    # Additional info
                    if r.get('phone') and r['phone'] != 'N/A':
                        st.write(f"**📞 Phone:** {r['phone']}")
                    if r.get('website') and r['website'] != 'N/A':
                        st.write(f"**🌐 Website:** [Link]({r['website']})")
                    if r.get('opening_hours') and r['opening_hours'] != 'N/A':
                        st.write(f"**🕐 Hours:** {r['opening_hours']}")

    else:
        st.warning(f"No restaurants found within {radius} km. Try:")
        st.info("""
        1. Increasing the search radius
        2. Using broader search terms (e.g., 'italian' instead of 'spaghetti carbonara')
        3. Trying a different location
        4. Ensuring API keys are valid
        """)

else:
    # Welcome screen
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        ### 🎯 Smart Food Search
        - Search by cuisine **OR** specific food item
        - Finds restaurants serving your desired dish
        - Filters out non-restaurants automatically
        """)
    
    with col2:
        st.markdown("""
        ### 📍 Accurate Results
        - Combines 3 data sources for reliability
        - Filters out closed/outdated restaurants
        - Relevance scoring for better matches
        """)
    
    with col3:
        st.markdown("""
        ### 🗺️ Interactive Map
        - Click restaurants on map to select
        - Get directions via Google Maps
        - Real-time distance calculations
        """)
    
    st.markdown("---")
    st.info("💡 **Tip:** Enter a location and cuisine/food item, then click 'Cook! 👨‍🍳' to start searching!")
