import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from typing import List, Dict, Tuple, Set
import time
from folium import plugins
import re
import concurrent.futures
from datetime import datetime

st.set_page_config(page_title="LETHIMCOOK", page_icon="🍽️", layout="wide")

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================
# Initialize all session state variables
default_values = {
    'searched': False,
    'restaurants': [],
    'user_lat': None,
    'user_lon': None,
    'display_name': None,
    'selected_restaurant': None,
    'api_calls': {'foursquare': 0, 'google': 0, 'osm': 0},
    'last_search_stats': {},
    'last_search_term': '',
    'address': '',
    'search_term': '',
    'radius': 3
}

for key, default_value in default_values.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# ============================================================================
# CSS STYLING
# ============================================================================
st.markdown("""
<style>
.main-header{font-size:2.5rem;color:#FF6B6B;text-align:center;margin-bottom:2rem;}
.stButton>button{background-color:#FF6B6B;color:white;font-weight:bold;border-radius:10px;padding:0.5rem 2rem;}
.api-badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;margin:2px;display:inline-block;}
.google{background:#4285F4;color:white;} .foursquare{background:#F94877;color:white;} .osm{background:#7EBC6F;color:white;}
.restaurant-list {max-height: 600px; overflow-y: auto;}
.restaurant-list::-webkit-scrollbar {width: 8px;}
.restaurant-list::-webkit-scrollbar-track {background: #f1f1f1;}
.restaurant-list::-webkit-scrollbar-thumb {background: #FF6B6B; border-radius: 4px;}
.expander-header {font-size: 1.1em; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

# ============================================================================
# GEOCODING FUNCTION
# ============================================================================
def geocode(address: str) -> Tuple:
    """Convert address to coordinates using OpenStreetMap"""
    if not address:
        return None, None, None
    
    url = "https://nominatim.openstreetmap.org/search"
    try:
        r = requests.get(url, params={
            'q': address, 
            'format': 'json', 
            'limit': 1, 
            'countrycodes': 'sg',
            'addressdetails': 1
        }, headers={'User-Agent': 'RestaurantFinderApp/1.0'}, timeout=15)
        
        if r.status_code == 200:
            data = r.json()
            if data:
                return (float(data[0]['lat']), float(data[0]['lon']), data[0]['display_name'])
        return None, None, None
    except Exception as e:
        st.error(f"Geocoding error: {str(e)[:200]}")
        return None, None, None

# ============================================================================
# DISTANCE CALCULATION
# ============================================================================
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two coordinates in kilometers"""
    from math import radians, cos, sin, asin, sqrt
    
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Earth radius in km
    return round(6371 * c, 2)

# ============================================================================
# NAME CLEANING
# ============================================================================
def clean_name_for_comparison(name: str) -> str:
    """Clean restaurant name for duplicate detection"""
    if not name:
        return ""
    
    name = name.lower()
    remove_words = {'restaurant', 'cafe', 'bistro', 'eatery', 'kitchen', 
                   'food', 'house', 'bar', 'grill', 'diner', 'eats', 
                   'the', 'a', 'an', 'singapore', 'sg', 'pte', 'ltd', '&', 'and'}
    
    name = re.sub(r'[^\w\s]', ' ', name)
    words = name.split()
    filtered_words = [word for word in words if word not in remove_words]
    filtered_words.sort()
    
    return ' '.join(filtered_words).strip()

# ============================================================================
# FOOD VALIDATION
# ============================================================================
def validate_food_relevance(restaurant_name: str, cuisine: str, search_term: str = None) -> bool:
    """Validate if restaurant likely serves the searched food"""
    if not search_term or not search_term.strip():
        return True
    
    search_term = search_term.lower().strip()
    name_lower = restaurant_name.lower()
    cuisine_lower = (cuisine or '').lower()
    
    # Common contradictions
    contradictions = {
        'sushi': ['fish head', 'steamboat', 'hotpot', 'teochew', 'porridge', 'bak kut teh'],
        'pizza': ['dim sum', 'nasi lemak', 'chicken rice', 'bakery', 'baker'],
        'burger': ['dim sum', 'sushi', 'seafood', 'vegetarian'],
        'spaghetti': ['chinese', 'malay', 'indian', 'thai', 'vietnamese'],
        'ramen': ['western', 'italian', 'french', 'mexican'],
        'curry': ['western', 'italian', 'mexican', 'japanese']
    }
    
    # Check for contradictions
    for food, invalid_terms in contradictions.items():
        if food in search_term:
            for term in invalid_terms:
                if term in name_lower or term in cuisine_lower:
                    return False
    
    # Check if search term appears in name or cuisine
    if (search_term in name_lower or 
        search_term in cuisine_lower or
        any(word in name_lower or word in cuisine_lower for word in search_term.split())):
        return True
    
    # For specific food items, require a match
    specific_foods = ['sushi', 'pizza', 'burger', 'spaghetti', 'pasta', 'ramen', 
                     'pho', 'tacos', 'dim sum', 'curry', 'steak']
    
    if search_term in specific_foods:
        return False  # Require explicit match for specific foods
    
    return True  # For general cuisines, be more lenient

# ============================================================================
# RELEVANCE SCORING
# ============================================================================
def calculate_relevance_score(restaurant: Dict, search_term: str = None) -> Dict:
    """Calculate relevance score for a restaurant"""
    score = 50
    confidence = "Unknown"
    warnings = []
    
    # Data Quality
    if restaurant.get('rating') and restaurant.get('rating') != 'N/A':
        score += 15
    if restaurant.get('price') and restaurant.get('price') != 'N/A':
        score += 5
    if restaurant.get('address') and restaurant.get('address') != 'N/A':
        score += 10
    if restaurant.get('cuisine') not in ['N/A', 'Not specified', 'Restaurant', '']:
        score += 10
    
    # Food Relevance
    if search_term and search_term.strip():
        search_lower = search_term.lower()
        name_lower = restaurant.get('name', '').lower()
        cuisine_lower = restaurant.get('cuisine', '').lower()
        
        if not validate_food_relevance(restaurant.get('name', ''), 
                                      restaurant.get('cuisine', ''), 
                                      search_term):
            score -= 30
            warnings.append(f"⚠️ Unlikely to serve {search_term}")
        elif search_lower in name_lower:
            score += 25
        elif search_lower in cuisine_lower:
            score += 20
        elif any(word in name_lower or word in cuisine_lower for word in search_lower.split()):
            score += 10
        else:
            score -= 10
    
    # API Source
    source = restaurant.get('source', 'unknown')
    if source == 'google':
        score += 20
        confidence = "High"
    elif source == 'foursquare':
        score += 12
        confidence = "Medium-High"
    elif source == 'osm':
        score += 8
        confidence = "Medium"
    
    # Business Status
    if restaurant.get('business_status') == 'CLOSED_PERMANENTLY':
        score -= 50
        warnings.append("🚫 Permanently closed")
    elif restaurant.get('is_open') == True:
        score += 5
    
    # Distance
    distance = restaurant.get('distance', 999)
    if distance < 0.5:
        score += 10
    elif distance < 1:
        score += 5
    elif distance > 5:
        score -= 5
    
    # Suspicious names
    name = restaurant.get('name', '').lower()
    suspicious = ['7-eleven', 'cheers', 'fairprice', 'minimart', 'convenience',
                 'atm', 'bank', 'clinic', 'hospital', 'school', 'hotel', 'motel']
    if any(word in name for word in suspicious):
        score -= 30
        warnings.append("⚠️ May not be a restaurant")
    
    # Confidence level
    if score >= 85:
        confidence = "Very High"
    elif score >= 75:
        confidence = "High"
    elif score >= 60:
        confidence = "Medium"
    elif score >= 45:
        confidence = "Low"
    else:
        confidence = "Very Low"
    
    restaurant['relevance_score'] = max(0, min(100, score))
    restaurant['confidence'] = confidence
    restaurant['warnings'] = warnings
    
    return restaurant

# ============================================================================
# API SEARCH FUNCTIONS
# ============================================================================
def search_foursquare(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """Search Foursquare API"""
    if not api_key or not api_key.strip():
        return []
    
    try:
        url = "https://api.foursquare.com/v3/places/search"
        headers = {
            "Accept": "application/json",
            "Authorization": f"{api_key.strip()}",
        }
        
        # Restaurant categories
        categories = "13000,13065,13066,13068,13070,13071,13072,13073,13076,13077,13079,13080"
        
        params = {
            'll': f"{lat},{lon}",
            'radius': min(radius_m, 100000),
            'categories': categories,
            'limit': 50,
            'sort': 'DISTANCE'
        }
        
        if search_term and search_term.strip():
            params['query'] = search_term
        
        response = requests.get(url, headers=headers, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for place in data.get('results', []):
                r_lat = place.get('geocodes', {}).get('main', {}).get('latitude')
                r_lon = place.get('geocodes', {}).get('main', {}).get('longitude')
                
                if r_lat and r_lon:
                    distance = calculate_distance(lat, lon, r_lat, r_lon)
                    if distance > (radius_m / 1000):
                        continue
                    
                    # Get cuisine
                    categories = place.get('categories', [])
                    cuisine = 'Restaurant'
                    if categories:
                        cuisine = categories[0].get('name', 'Restaurant')
                    
                    # Food relevance check
                    if search_term and search_term.strip():
                        if not validate_food_relevance(place.get('name', ''), cuisine, search_term):
                            continue
                    
                    location = place.get('location', {})
                    address_parts = []
                    if location.get('formatted_address'):
                        address_parts.append(location['formatted_address'])
                    if location.get('locality'):
                        address_parts.append(location['locality'])
                    
                    results.append({
                        'name': place.get('name', 'Unnamed'),
                        'lat': r_lat,
                        'lon': r_lon,
                        'cuisine': cuisine,
                        'address': ', '.join(address_parts) if address_parts else 'N/A',
                        'rating': place.get('rating', 'N/A'),
                        'price': place.get('price', 'N/A'),
                        'image_url': '',
                        'is_open': place.get('hours', {}).get('is_open'),
                        'distance': distance,
                        'source': 'foursquare',
                        'fsq_id': place.get('fsq_id', '')
                    })
            
            return results
        else:
            return []
            
    except Exception as e:
        return []

def search_google(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """Search Google Places API"""
    if not api_key or not api_key.strip():
        return []
    
    try:
        # Use Text Search API for better results
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        
        params = {
            'key': api_key.strip(),
            'location': f"{lat},{lon}",
            'radius': min(radius_m, 50000),
            'type': 'restaurant',
            'language': 'en'
        }
        
        if search_term and search_term.strip():
            params['query'] = f"{search_term} restaurant"
        else:
            params['query'] = 'restaurant'
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for place in data.get('results', []):
                r_lat = place.get('geometry', {}).get('location', {}).get('lat')
                r_lon = place.get('geometry', {}).get('location', {}).get('lng')
                
                if r_lat and r_lon:
                    distance = calculate_distance(lat, lon, r_lat, r_lon)
                    if distance > (radius_m / 1000):
                        continue
                    
                    # Get cuisine from types
                    types = place.get('types', [])
                    cuisine = 'Restaurant'
                    if types:
                        # Filter restaurant-related types
                        food_types = [t.replace('_', ' ').title() for t in types 
                                    if any(keyword in t for keyword in ['restaurant', 'food', 'cafe', 'bar'])]
                        if food_types:
                            cuisine = ', '.join(food_types[:2])
                    
                    # Food relevance check
                    if search_term and search_term.strip():
                        if not validate_food_relevance(place.get('name', ''), cuisine, search_term):
                            continue
                    
                    # Get photo
                    photo_url = ''
                    if place.get('photos') and place['photos']:
                        photo_ref = place['photos'][0].get('photo_reference')
                        if photo_ref:
                            photo_url = f"https://maps.googleapis.com/maps/api/place/photo?key={api_key.strip()}&photoreference={photo_ref}&maxwidth=400"
                    
                    # Price level
                    price_level = place.get('price_level')
                    price = 'N/A'
                    if price_level is not None:
                        price_map = {1: '$', 2: '$$', 3: '$$$', 4: '$$$$', 5: '$$$$$'}
                        price = price_map.get(price_level, 'N/A')
                    
                    results.append({
                        'name': place.get('name', 'Unnamed'),
                        'lat': r_lat,
                        'lon': r_lon,
                        'cuisine': cuisine,
                        'address': place.get('formatted_address', 'N/A'),
                        'rating': place.get('rating', 'N/A'),
                        'price': price,
                        'image_url': photo_url,
                        'is_open': place.get('opening_hours', {}).get('open_now'),
                        'distance': distance,
                        'source': 'google',
                        'place_id': place.get('place_id', '')
                    })
            
            return results
        else:
            return []
            
    except Exception as e:
        return []

def search_osm(lat: float, lon: float, radius_m: int, search_term: str) -> List[Dict]:
    """Search OpenStreetMap"""
    url = "https://overpass-api.de/api/interpreter"
    
    # Build query
    query_parts = []
    for amenity in ['restaurant', 'fast_food', 'cafe']:
        query_parts.append(f'node["amenity"="{amenity}"](around:{radius_m},{lat},{lon});')
        query_parts.append(f'way["amenity"="{amenity}"](around:{radius_m},{lat},{lon});')
    
    query = f"""
    [out:json][timeout:30];
    (
      {"".join(query_parts)}
    );
    out center;
    """
    
    try:
        response = requests.post(url, data={'data': query}, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for element in data.get('elements', []):
                # Get coordinates
                if element['type'] == 'node':
                    r_lat = element.get('lat')
                    r_lon = element.get('lon')
                else:
                    center = element.get('center', {})
                    r_lat = center.get('lat')
                    r_lon = center.get('lon')
                
                if r_lat and r_lon:
                    distance = calculate_distance(lat, lon, r_lat, r_lon)
                    if distance > (radius_m / 1000):
                        continue
                    
                    tags = element.get('tags', {})
                    name = tags.get('name', 'Unnamed Restaurant')
                    cuisine = tags.get('cuisine', 'Not specified')
                    
                    # Food relevance check
                    if search_term and search_term.strip():
                        if not validate_food_relevance(name, cuisine, search_term):
                            continue
                    
                    # Build address
                    address_parts = []
                    if tags.get('addr:street'):
                        street = tags.get('addr:street', '')
                        housenumber = tags.get('addr:housenumber', '')
                        if housenumber:
                            address_parts.append(f"{housenumber} {street}")
                        else:
                            address_parts.append(street)
                    if tags.get('addr:city'):
                        address_parts.append(tags['addr:city'])
                    
                    results.append({
                        'name': name,
                        'lat': r_lat,
                        'lon': r_lon,
                        'cuisine': cuisine,
                        'address': ', '.join(address_parts) if address_parts else 'N/A',
                        'rating': 'N/A',
                        'price': 'N/A',
                        'image_url': '',
                        'is_open': None,
                        'distance': distance,
                        'source': 'osm',
                        'osm_id': element.get('id', ''),
                        'phone': tags.get('phone', 'N/A'),
                        'website': tags.get('website', 'N/A'),
                        'opening_hours': tags.get('opening_hours', 'N/A')
                    })
            
            return results
        else:
            return []
            
    except Exception as e:
        return []

# ============================================================================
# DEDUPLICATION
# ============================================================================
def deduplicate(restaurants: List[Dict]) -> List[Dict]:
    """Remove duplicate restaurants"""
    seen = set()
    unique = []
    
    for r in restaurants:
        # Create multiple identification keys
        keys = []
        
        # Exact coordinates + name
        keys.append(f"{round(r['lat'], 5)}_{round(r['lon'], 5)}_{r['name'].lower()}")
        
        # Cleaned name + approximate coordinates
        cleaned_name = clean_name_for_comparison(r['name'])
        if cleaned_name:
            keys.append(f"{round(r['lat'], 4)}_{round(r['lon'], 4)}_{cleaned_name}")
        
        # API-specific IDs
        if r.get('fsq_id'):
            keys.append(f"fsq_{r['fsq_id']}")
        if r.get('place_id'):
            keys.append(f"google_{r['place_id']}")
        if r.get('osm_id'):
            keys.append(f"osm_{r['osm_id']}")
        
        # Check if any key has been seen
        is_duplicate = False
        for key in keys:
            if key in seen:
                is_duplicate = True
                break
        
        if not is_duplicate:
            # Add all keys to seen set
            seen.update(keys)
            unique.append(r)
    
    return unique

# ============================================================================
# HYBRID SEARCH
# ============================================================================
def hybrid_search(lat: float, lon: float, radius_m: int, search_term: str, fs_key: str, g_key: str) -> Tuple[List[Dict], Dict]:
    """Combine results from all APIs"""
    all_results = []
    stats = {'foursquare': 0, 'google': 0, 'osm': 0, 'total': 0, 'duplicates': 0, 'filtered': 0}
    
    # Run searches in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        
        if fs_key and fs_key.strip():
            futures['foursquare'] = executor.submit(search_foursquare, lat, lon, radius_m, search_term, fs_key)
        
        if g_key and g_key.strip():
            futures['google'] = executor.submit(search_google, lat, lon, radius_m, search_term, g_key)
        
        futures['osm'] = executor.submit(search_osm, lat, lon, radius_m, search_term)
        
        # Collect results
        for source, future in futures.items():
            try:
                results = future.result(timeout=20)
                all_results.extend(results)
                stats[source] = len(results)
                if source in st.session_state.api_calls:
                    st.session_state.api_calls[source] += 1
            except Exception as e:
                pass
    
    stats['total'] = len(all_results)
    
    # Deduplicate
    unique_results = deduplicate(all_results)
    stats['duplicates'] = stats['total'] - len(unique_results)
    
    # Calculate relevance scores
    unique_results = [calculate_relevance_score(r, search_term) for r in unique_results]
    
    # Filter low-quality results
    before_filter = len(unique_results)
    unique_results = [r for r in unique_results if r['relevance_score'] >= 40]
    stats['filtered'] = before_filter - len(unique_results)
    
    # Sort by relevance and distance
    unique_results.sort(key=lambda x: (-x['relevance_score'], x['distance']))
    
    return unique_results, stats

# ============================================================================
# MAP CREATION
# ============================================================================
def create_map(user_lat: float, user_lon: float, restaurants: List[Dict], selected: Dict = None) -> folium.Map:
    """Create interactive map"""
    # Determine center
    if selected:
        center = [selected['lat'], selected['lon']]
        zoom = 16
    else:
        center = [user_lat, user_lon]
        zoom = 14
    
    # Create map
    m = folium.Map(location=center, zoom_start=zoom, tiles='OpenStreetMap')
    
    # Add fullscreen control
    plugins.Fullscreen(position='topright').add_to(m)
    
    # Add user location marker
    folium.Marker(
        [user_lat, user_lon],
        popup="📍 <b>Your Location</b>",
        tooltip="You are here",
        icon=folium.Icon(color='blue', icon='home', prefix='fa')
    ).add_to(m)
    
    # Add restaurant markers
    for r in restaurants:
        is_selected = selected and r['name'] == selected['name']
        
        # Choose icon color
        if is_selected:
            icon_color = 'orange'
            icon_type = 'star'
            tooltip = f"⭐ {r['name']}"
        else:
            icon_color = 'red'
            icon_type = 'cutlery'
            tooltip = f"🍽️ {r['name']} ({r['distance']} km)"
        
        # Create popup
        popup_html = f"""
        <div style="width: 250px;">
            <h4>{r['name']}</h4>
            <p><b>Cuisine:</b> {r.get('cuisine', 'N/A')}</p>
            <p><b>Distance:</b> {r['distance']} km</p>
            <p><b>Source:</b> {r['source'].upper()}</p>
            <p style="color: #666; font-size: 0.9em;">
                Click on map or list to select
            </p>
        </div>
        """
        
        # Add marker
        folium.Marker(
            [r['lat'], r['lon']],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=tooltip,
            icon=folium.Icon(color=icon_color, icon=icon_type, prefix='fa')
        ).add_to(m)
    
    # Add route line if restaurant selected
    if selected:
        folium.PolyLine(
            [[user_lat, user_lon], [selected['lat'], selected['lon']]],
            color='blue',
            weight=3,
            opacity=0.7,
            dash_array='5, 5'
        ).add_to(m)
    
    return m

# ============================================================================
# MAIN APP
# ============================================================================

# App title
st.markdown('<h1 class="main-header">🍽️ LETHIMCOOK<br><small>Find restaurants near you</small></h1>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("🔑 API Configuration")
    
    # API keys
    fs_key = st.text_input("Foursquare API Key", type="password", 
                          help="Optional but recommended for better results")
    g_key = st.text_input("Google Places API Key", type="password",
                         help="Optional but recommended for photos and ratings")
    
    st.divider()
    st.header("🔍 Search Parameters")
    
    # Store inputs in session state to preserve them
    address = st.text_input("📍 Location / Address", 
                           value=st.session_state.get('address', ''),
                           placeholder="e.g., Orchard Road, Singapore")
    
    search_term = st.text_input("🍜 Cuisine / Food", 
                               value=st.session_state.get('search_term', ''),
                               placeholder="e.g., sushi, pizza, spaghetti")
    
    radius = st.slider("📏 Search Radius (km)", 1, 10, 
                      value=st.session_state.get('radius', 3))
    
    # Update session state
    st.session_state.address = address
    st.session_state.search_term = search_term
    st.session_state.radius = radius
    
    col1, col2 = st.columns(2)
    with col1:
        search_clicked = st.button("🔍 Search", type="primary", use_container_width=True)
    with col2:
        if st.session_state.searched:
            if st.button("🗑️ Clear", use_container_width=True):
                for key in ['searched', 'restaurants', 'selected_restaurant']:
                    if key in st.session_state:
                        if key == 'searched':
                            st.session_state[key] = False
                        elif key == 'restaurants':
                            st.session_state[key] = []
                        else:
                            st.session_state[key] = None
                st.rerun()

# Handle search
if search_clicked:
    if not address:
        st.error("⚠️ Please enter a location!")
        st.stop()
    
    # Clear previous selection
    st.session_state.selected_restaurant = None
    
    # Geocode
    with st.spinner("📍 Finding location..."):
        lat, lon, display_name = geocode(address)
    
    if not lat:
        st.error("❌ Could not find location. Please try a different address.")
        st.stop()
    
    # Perform search
    with st.spinner(f"🍽️ Searching for restaurants..."):
        restaurants, stats = hybrid_search(lat, lon, radius * 1000, search_term, fs_key, g_key)
    
    # Update session state
    st.session_state.searched = True
    st.session_state.restaurants = restaurants
    st.session_state.user_lat = lat
    st.session_state.user_lon = lon
    st.session_state.display_name = display_name
    st.session_state.last_search_stats = stats
    st.session_state.last_search_term = search_term
    
    # Show results
    if restaurants:
        st.success(f"✅ Found {len(restaurants)} restaurants!")
    else:
        st.warning("No restaurants found. Try adjusting your search criteria.")
    
    st.rerun()

# Display results if searched
if st.session_state.searched and st.session_state.restaurants:
    # Statistics
    if st.session_state.last_search_stats:
        stats = st.session_state.last_search_stats
        
        with st.expander("📊 Search Statistics", expanded=False):
            cols = st.columns(5)
            with cols[0]:
                st.metric("Total Found", len(st.session_state.restaurants))
            with cols[1]:
                st.metric("Foursquare", stats['foursquare'])
            with cols[2]:
                st.metric("Google", stats['google'])
            with cols[3]:
                st.metric("OpenStreetMap", stats['osm'])
            with cols[4]:
                st.metric("Duplicates", stats['duplicates'])
            
            st.caption(f"📍 {st.session_state.display_name}")
            if st.session_state.last_search_term:
                st.caption(f"🔍 Searching for: {st.session_state.last_search_term}")
            st.caption(f"📏 Radius: {st.session_state.radius} km")
    
    # Create two columns
    map_col, list_col = st.columns([2, 1])
    
    # Map column
    with map_col:
        st.subheader("📍 Map View")
        
        if st.session_state.selected_restaurant:
            selected_name = st.session_state.selected_restaurant['name']
            st.info(f"⭐ Selected: **{selected_name}**")
        else:
            st.info("💡 Click any restaurant on the map or list to select it")
        
        # Create and display map
        m = create_map(
            st.session_state.user_lat,
            st.session_state.user_lon,
            st.session_state.restaurants,
            st.session_state.selected_restaurant
        )
        
        map_data = st_folium(m, width=None, height=500, key="map")
        
        # Handle map clicks
        if map_data and map_data.get("last_object_clicked"):
            clicked_lat = map_data["last_object_clicked"]["lat"]
            clicked_lon = map_data["last_object_clicked"]["lng"]
            
            # Find clicked restaurant
            for restaurant in st.session_state.restaurants:
                if (abs(restaurant['lat'] - clicked_lat) < 0.0001 and 
                    abs(restaurant['lon'] - clicked_lon) < 0.0001):
                    st.session_state.selected_restaurant = restaurant
                    st.rerun()
    
    # List column
    with list_col:
        st.subheader("📋 Restaurants")
        st.markdown(f"**{len(st.session_state.restaurants)} restaurants found**")
        
        # Create sorted list with selected first
        sorted_restaurants = st.session_state.restaurants.copy()
        selected = st.session_state.selected_restaurant
        
        if selected:
            # Move selected to front
            if selected in sorted_restaurants:
                sorted_restaurants.remove(selected)
            sorted_restaurants.insert(0, selected)
        
        # Display restaurants
        for idx, restaurant in enumerate(sorted_restaurants, 1):
            is_selected = (selected and 
                          restaurant['name'] == selected['name'] and 
                          restaurant['distance'] == selected['distance'])
            
            # Confidence emoji
            confidence_emoji = {
                'Very High': '🟢',
                'High': '🟢',
                'Medium': '🟡',
                'Low': '🟠',
                'Very Low': '🔴',
                'Unknown': '⚪'
            }
            conf_emoji = confidence_emoji.get(restaurant.get('confidence', 'Unknown'), '⚪')
            
            # Create expander label
            if is_selected:
                label = f"⭐ **{restaurant['name']}** {conf_emoji}"
            else:
                score = restaurant.get('relevance_score', 0)
                label = f"{idx}. {restaurant['name']} {conf_emoji} ({score:.0f}%)"
            
            # FIX: Ensure is_selected is a boolean
            is_selected_bool = bool(is_selected)
            
            with st.expander(label, expanded=is_selected_bool):
                # Confidence and warnings
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.caption(f"**Confidence:** {restaurant.get('confidence', 'Unknown')}")
                with col2:
                    st.caption(f"**Score:** {restaurant.get('relevance_score', 0):.0f}%")
                
                # Warnings
                warnings = restaurant.get('warnings', [])
                for warning in warnings:
                    if 'PERMANENTLY CLOSED' in warning:
                        st.error(warning)
                    elif 'Unlikely' in warning:
                        st.warning(warning)
                    else:
                        st.info(warning)
                
                # API source badge
                source = restaurant.get('source', 'unknown')
                st.markdown(f'<span class="api-badge {source}">{source.upper()}</span>', 
                           unsafe_allow_html=True)
                
                # Action buttons
                btn_col1, btn_col2 = st.columns(2)
                with btn_col1:
                    if not is_selected:
                        if st.button("📍 Select", key=f"select_{idx}", use_container_width=True):
                            st.session_state.selected_restaurant = restaurant
                            st.rerun()
                
                with btn_col2:
                    # Google Maps directions
                    if st.session_state.user_lat and st.session_state.user_lon:
                        url = f"https://www.google.com/maps/dir/?api=1&origin={st.session_state.user_lat},{st.session_state.user_lon}&destination={restaurant['lat']},{restaurant['lon']}"
                        st.link_button("🧭 Directions", url, use_container_width=True)
                
                # Restaurant details
                st.write(f"**Cuisine:** {restaurant.get('cuisine', 'N/A')}")
                st.write(f"**Distance:** {restaurant.get('distance', 'N/A')} km")
                st.write(f"**Address:** {restaurant.get('address', 'N/A')}")
                
                # Rating
                rating = restaurant.get('rating', 'N/A')
                if rating != 'N/A':
                    stars = "⭐" * min(5, int(float(rating)))
                    st.write(f"**Rating:** {stars} {rating}/5")
                
                # Price
                price = restaurant.get('price', 'N/A')
                if price != 'N/A':
                    st.write(f"**Price:** {price}")
                
                # Open status
                is_open = restaurant.get('is_open')
                if is_open is True:
                    st.success("● Open Now")
                elif is_open is False:
                    st.error("● Closed")
                
                # Photo
                image_url = restaurant.get('image_url')
                if image_url:
                    try:
                        st.image(image_url, use_column_width=True)
                    except:
                        pass
                
                # Additional info
                phone = restaurant.get('phone')
                if phone and phone != 'N/A':
                    st.write(f"**Phone:** {phone}")
                
                website = restaurant.get('website')
                if website and website != 'N/A':
                    st.write(f"**Website:** [{website[:50]}...]({website})" if len(website) > 50 else f"**Website:** [Link]({website})")
                
                hours = restaurant.get('opening_hours')
                if hours and hours != 'N/A':
                    st.write(f"**Hours:** {hours}")

elif st.session_state.searched and not st.session_state.restaurants:
    st.warning("""
    No restaurants found matching your criteria. Try:
    - Increasing the search radius
    - Using a broader search term
    - Trying a different location
    - Adding API keys for more comprehensive results
    """)

else:
    # Welcome screen
    st.markdown("---")
    st.markdown("""
    <div style="text-align:center;color:#666;">
        <h3>🎯 Welcome to LETHIMCOOK!</h3>
        <p>Find restaurants serving your favorite food near any location in Singapore.</p>
        
        <div style="margin:2rem 0; padding:1.5rem; background:#f8f9fa; border-radius:10px; text-align:left;">
            <h4>✨ Key Features:</h4>
            <ul>
                <li><strong>Smart Search</strong> - Find restaurants by cuisine or specific dishes</li>
                <li><strong>Multi-API Integration</strong> - Combines Google, Foursquare, and OpenStreetMap</li>
                <li><strong>Relevance Scoring</strong> - Each result gets a confidence score</li>
                <li><strong>Interactive Map</strong> - Visualize restaurants on an interactive map</li>
                <li><strong>One-Click Directions</strong> - Get Google Maps directions instantly</li>
            </ul>
            
            <h4>🚀 Getting Started:</h4>
            <ol>
                <li>Enter API keys (optional but recommended)</li>
                <li>Enter a location or address in Singapore</li>
                <li>Search for a cuisine or specific food item</li>
                <li>Set your search radius</li>
                <li>Click <strong>Search</strong> to find restaurants!</li>
            </ol>
        </div>
        
        <p><em>Tip: For best results, use all available API keys and be specific with your search terms!</em></p>
    </div>
    """, unsafe_allow_html=True)
