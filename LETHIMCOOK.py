import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
from typing import List, Dict, Tuple, Set
import time
from folium import plugins

st.set_page_config(page_title="LETHIMCOOK", page_icon="🍽️", layout="wide")

# Session state
for key in ['searched', 'restaurants', 'user_lat', 'user_lon', 'display_name', 'selected_restaurant', 'api_calls', 'last_search_stats']:
    if key not in st.session_state:
        st.session_state[key] = False if key == 'searched' else [] if key == 'restaurants' else None if key not in ['api_calls', 'last_search_stats'] else {'foursquare': 0, 'google': 0, 'osm': 0} if key == 'api_calls' else {}

st.markdown("""
<style>
.main-header{font-size:2.5rem;color:#FF6B6B;text-align:center;margin-bottom:2rem;}
.stButton>button{background-color:#FF6B6B;color:white;font-weight:bold;border-radius:10px;padding:0.5rem 2rem;}
.api-badge{padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;margin:2px;display:inline-block;}
.google{background:#4285F4;color:white;} .foursquare{background:#F94877;color:white;} .osm{background:#7EBC6F;color:white;}
</style>
""", unsafe_allow_html=True)

def geocode(address: str) -> Tuple:
    """Geocode address using Nominatim"""
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

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km using Haversine formula"""
    from math import radians, cos, sin, asin, sqrt
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    return round(6371 * 2 * asin(sqrt(a)), 2)

def search_foursquare(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """Foursquare Places API (Current API) with refined filters."""
    if not api_key or not api_key.strip():
        return []

    try:
        url = "https://places-api.foursquare.com/places/search"

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",  # Must include 'Bearer'
            "X-Places-Api-Version": "2025-06-17"  # REQUIRED header
        }

        # ========== REFINEMENT 1: SPECIFIC CATEGORY FILTER ==========
        # A curated list of specific food & drink venue categories for Singapore.
        # This EXCLUDES broad categories like 'Food Court' (13099) or 'Metro Station' (transport categories).
        category_list = (
            '13065,13145,13314,13236,13066,13068,13070,13071,13072,13073,13076,13077,13079,13080,'
            '13081,13082,13083,13084,13085,13086,13087,13088,13089,13090,13091,13092,13093,13094,'
            '13095,13096,13097,13144,13146,13147,13148,13149,13150,13151,13152,13153,13154,13155'
        )
        # Categories include: Restaurant, Hawker Centre, Noodle House, Indian Restaurant,
        # Chinese Restaurant, Japanese Restaurant, etc.

        params = {
            'll': f"{lat},{lon}",
            'radius': min(radius_m, 100000),
            'categories': category_list,  # Use the refined, specific list
            'limit': 50,
            'sort': 'POPULARITY'  # Prioritize well-regarded spots
        }

        if search_term and search_term.strip():
            params['query'] = search_term

        r = requests.get(url, headers=headers, params=params, timeout=15)

        if r.status_code != 200:
            st.error(f"Foursquare API Error: {r.status_code}")
            if r.text:
                st.error(f"Response: {r.text[:300]}")
            return []

        r.raise_for_status()
        data = r.json()

        results = []
        for place in data.get('results', []):
            # Extract coordinates from new response structure
            r_lat = place.get('latitude')
            r_lon = place.get('longitude')

            if r_lat and r_lon:
                # Calculate distance and enforce radius filter
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):
                    continue

                # Get categories and cuisine
                categories = place.get('categories', [])
                cuisine_list = [cat.get('name', '') for cat in categories]
                cuisine = ', '.join(cuisine_list) if cuisine_list else 'Restaurant'

                # Get address
                location = place.get('location', {})
                address = location.get('formatted_address', 'N/A')

                # ========== REFINEMENT 2: LOCAL CUISINE/NAME MATCH ==========
                # Apply an extra filter if the user searched for a specific cuisine/food.
                if search_term and search_term.strip():
                    search_lower = search_term.lower()
                    venue_cuisine_lower = cuisine.lower()
                    venue_name_lower = place.get('name', '').lower()

                    # Skip this venue if the search term is NOT found in EITHER its name or its listed cuisine.
                    # This catches stalls selling different foods under a generic "Food" category.
                    if (search_lower not in venue_cuisine_lower) and (search_lower not in venue_name_lower):
                        continue  # This venue is irrelevant to the user's request

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
                    'source': 'foursquare'
                })

        return results
    except requests.exceptions.RequestException as e:
        st.error(f"Foursquare network error: {str(e)[:200]}")
        return []
    except Exception as e:
        st.error(f"Foursquare error: {str(e)[:200]}")
        return []

def search_google(lat: float, lon: float, radius_m: int, search_term: str, api_key: str) -> List[Dict]:
    """Google Places API (New)"""
    if not api_key or not api_key.strip():
        return []
    
    try:
        if search_term and search_term.strip():
            url = "https://places.googleapis.com/v1/places:searchText"
            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.priceLevel,places.photos,places.currentOpeningHours'
            }
            body = {
                "textQuery": f"{search_term} restaurant Singapore",
                "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": min(radius_m, 50000)}},
                "maxResultCount": 50
            }
        else:
            url = "https://places.googleapis.com/v1/places:searchNearby"
            headers = {
                'Content-Type': 'application/json',
                'X-Goog-Api-Key': api_key,
                'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.priceLevel,places.photos,places.currentOpeningHours'
            }
            body = {
                "includedTypes": ["restaurant"],
                "maxResultCount": 50,
                "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": min(radius_m, 50000)}}
            }
        
        r = requests.post(url, headers=headers, json=body, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        results = []
        for place in data.get('places', []):
            loc = place.get('location', {})
            r_lat, r_lon = loc.get('latitude'), loc.get('longitude')
            
            if r_lat and r_lon:
                # Calculate distance and filter by radius
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):  # radius_m in meters, distance in km
                    continue
                
                price_map = {'PRICE_LEVEL_INEXPENSIVE': '$', 'PRICE_LEVEL_MODERATE': '$$', 'PRICE_LEVEL_EXPENSIVE': '$$$', 'PRICE_LEVEL_VERY_EXPENSIVE': '$$$$'}
                price = price_map.get(place.get('priceLevel', ''), 'N/A')
                
                photos = place.get('photos', [])
                photo_url = f"https://places.googleapis.com/v1/{photos[0].get('name', '')}/media?key={api_key}&maxHeightPx=400" if photos and photos[0].get('name') else ''
                
                results.append({
                    'name': place.get('displayName', {}).get('text', 'Unnamed'),
                    'lat': r_lat,
                    'lon': r_lon,
                    'cuisine': 'Restaurant',
                    'address': place.get('formattedAddress', 'N/A'),
                    'rating': place.get('rating', 'N/A'),
                    'price': price,
                    'image_url': photo_url,
                    'is_open': place.get('currentOpeningHours', {}).get('openNow'),
                    'distance': distance,
                    'source': 'google'
                })
        
        return results
    except Exception as e:
        st.warning(f"Google Places error: {str(e)[:100]}")
        return []

def search_osm(lat: float, lon: float, radius_m: int, search_term: str) -> List[Dict]:
    """OpenStreetMap Overpass API"""
    url = "https://overpass-api.de/api/interpreter"
    
    # Build query with proper filtering
    if search_term and search_term.strip():
        search_filter = f'["cuisine"~"{search_term}",i]'
    else:
        search_filter = ""
    
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="restaurant"]{search_filter}(around:{radius_m},{lat},{lon});
      way["amenity"="restaurant"]{search_filter}(around:{radius_m},{lat},{lon});
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
                description = tags.get('description', '')
                
                # Additional text filtering if search term provided
                if search_term and search_term.strip():
                    search_lower = search_term.lower()
                    if (search_lower not in name.lower() and 
                        search_lower not in cuisine.lower() and 
                        search_lower not in description.lower()):
                        continue
                
                # Calculate distance and verify within radius
                distance = calculate_distance(lat, lon, r_lat, r_lon)
                if distance > (radius_m / 1000):  # radius_m in meters, distance in km
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
                    'phone': tags.get('phone', tags.get('contact:phone', 'N/A')),
                    'website': tags.get('website', tags.get('contact:website', 'N/A')),
                    'opening_hours': tags.get('opening_hours', 'N/A')
                })
        
        return results
    except Exception as e:
        st.warning(f"OpenStreetMap error: {str(e)[:100]}")
        return []

def deduplicate(restaurants: List[Dict]) -> List[Dict]:
    """Remove duplicates based on name and location"""
    seen: Set[str] = set()
    unique = []
    
    for r in restaurants:
        key = f"{r['name'].lower().strip()}_{round(r['lat'], 4)}_{round(r['lon'], 4)}"
        if key not in seen:
            seen.add(key)
            unique.append(r)
    
    return unique

def hybrid_search(lat: float, lon: float, radius_m: int, search_term: str, fs_key: str, g_key: str) -> Tuple[List[Dict], Dict]:
    """Hybrid search - combines all 3 APIs"""
    all_results = []
    stats = {'foursquare': 0, 'google': 0, 'osm': 0, 'total': 0, 'duplicates': 0}
    
    # Always try all 3 APIs (not just when others fail)
    
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
            time.sleep(0.3)
            g_results = search_google(lat, lon, radius_m, search_term, g_key)
            all_results.extend(g_results)
            stats['google'] = len(g_results)
            st.session_state.api_calls['google'] += 1
    
    # 3. OpenStreetMap (ALWAYS as fallback/supplement)
    with st.spinner("🔍 Searching OpenStreetMap..."):
        time.sleep(0.3)
        osm_results = search_osm(lat, lon, radius_m, search_term)
        all_results.extend(osm_results)
        stats['osm'] = len(osm_results)
        st.session_state.api_calls['osm'] += 1
    
    stats['total'] = len(all_results)
    
    # Deduplicate
    unique_results = deduplicate(all_results)
    stats['duplicates'] = stats['total'] - len(unique_results)
    
    # Sort by distance (NO CAP - show all results)
    unique_results.sort(key=lambda x: x['distance'])
    
    return unique_results, stats

def create_map(user_lat: float, user_lon: float, restaurants: List[Dict], selected: Dict = None) -> folium.Map:
    """Create map with all markers"""
    center = [selected['lat'], selected['lon']] if selected else [user_lat, user_lon]
    m = folium.Map(location=center, zoom_start=16 if selected else 14, tiles='OpenStreetMap')
    plugins.Fullscreen(position='topright', title='Fullscreen', title_cancel='Exit').add_to(m)
    
    # User location
    folium.Marker([user_lat, user_lon], popup="<b>📍 Your Location</b>", tooltip="🔵 You are here",
                  icon=folium.Icon(color='blue', icon='home', prefix='fa')).add_to(m)
    
    # Restaurant markers
    for r in restaurants:
        is_sel = selected and r['name'] == selected['name'] and abs(r['lat'] - selected['lat']) < 0.0001
        
        source_color = {'foursquare': '#F94877', 'google': '#4285F4', 'osm': '#7EBC6F'}
        stars = "⭐" * int(float(r.get('rating', 0))) if r.get('rating') != 'N/A' else ''
        
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
        
        icon = folium.Icon(color='orange', icon='star', prefix='fa') if is_sel else folium.Icon(color='red', icon='cutlery', prefix='fa')
        tooltip = f"⭐ SELECTED: {r['name']}" if is_sel else f"🍽️ {r['name']} - {r['distance']} km"
        
        folium.Marker([r['lat'], r['lon']], popup=folium.Popup(popup, max_width=250), tooltip=tooltip, icon=icon).add_to(m)
    
    # Route line
    if selected:
        folium.PolyLine([[user_lat, user_lon], [selected['lat'], selected['lon']]], 
                       color='blue', weight=4, opacity=0.7,
                       popup=f"<b>Route:</b> {selected.get('distance')} km").add_to(m)
    
    return m

# Main UI
st.markdown('<h1 class="main-header">🍽️ LETHIMCOOK<br><small>Cooking up restaurant/food recommendations</small></h1>', unsafe_allow_html=True)

with st.sidebar:
    st.header("🔑 API Keys")
    
    st.info("💡 **Use multiple APIs for best results!**")
    
    fs_key = st.text_input("Foursquare API Key", type="password", 
                          value="VUKP54231AII5PDZLZRFZ0SBLX5U25FARAWRKSMA1OFO5GYV",
                          help="Use your working Foursquare API key")
    g_key = st.text_input("Google Places API Key", type="password",
                         help="Paid after trial - Good for restaurants")
    
    # UPDATED TEST FOURSQUARE API KEY
    if fs_key:
        if st.button("🧪 Test Foursquare API Key", use_container_width=True):
            with st.spinner("Testing Foursquare API..."):
                # CORRECTED: Updated test to use current API endpoint
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
                    
                    st.write("**🔍 DEBUG INFO:**")
                    st.code(f"Status Code: {test_response.status_code}")
                    st.code(f"Request URL: {test_url}")
                    st.code(f"Authorization Header: Bearer {fs_key[:10]}...{fs_key[-10:]}")
                    st.code(f"Response: {test_response.text[:500]}")
                    
                    if test_response.status_code == 200:
                        st.success("✅ API KEY WORKS! Foursquare is responding correctly!")
                        data = test_response.json()
                        st.write(f"Found {len(data.get('results', []))} test results")
                    elif test_response.status_code == 401:
                        st.error("❌ 401 ERROR: Invalid API Key!")
                        st.warning("""
                        **This means:**
                        - Your API key format is wrong
                        - OR you copied the wrong key from Foursquare dashboard
                        
                        **What to check:**
                        1. Make sure you're using the correct key format
                        2. Ensure the key is from the Service API Keys section
                        3. Verify you're using 'Bearer' prefix in the header
                        """)
                    else:
                        st.error(f"❌ ERROR {test_response.status_code}")
                        st.write(test_response.text[:500])
                        
                except Exception as e:
                    st.error(f"Connection error: {str(e)}")
    

    

    st.divider()
    st.header("🔍 Search")
    
    address = st.text_input("📍 Location")
    search_term = st.text_input("🍜 Cuisine/Food")
    radius = st.slider("📏 Radius (km)", 1, 10, 3, 1)
    
    st.caption(f"⚠️ Will show ALL restaurants within {radius} km")
    
    search_btn = st.button("Cook! 👨‍🍳", use_container_width=True)
    
    if st.session_state.searched and st.button("🗑️ Clear", use_container_width=True):
        st.session_state.searched = False
        st.session_state.restaurants = []
        st.session_state.selected_restaurant = None
        st.rerun()

if search_btn:
    if not address:
        st.warning("⚠️ Enter a location!")
    else:
        with st.spinner("🔍 Finding location..."):
            time.sleep(1)
            lat, lon, display_name = geocode(address)
        
        if not lat:
            st.error("❌ Location not found in Singapore")
        else:
            st.success(f"✅ {display_name}")
            
            restaurants, stats = hybrid_search(lat, lon, radius * 1000, search_term, fs_key, g_key)
            
            st.session_state.searched = True
            st.session_state.restaurants = restaurants
            st.session_state.user_lat = lat
            st.session_state.user_lon = lon
            st.session_state.display_name = display_name
            st.session_state.selected_restaurant = None
            st.session_state.last_search_stats = stats
            
            if restaurants:
                st.success(f"🎉 Found {len(restaurants)} restaurants within {radius} km!")
            else:
                st.warning(f"No restaurants found within {radius} km. Try increasing radius or broader search.")
            
            st.rerun()

if st.session_state.searched:
    # Show stats
    if st.session_state.last_search_stats:
        stats = st.session_state.last_search_stats
        with st.expander(f"📊 Search Statistics ({len(st.session_state.restaurants)} total results)"):
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Foursquare", stats['foursquare'])
            with col2:
                st.metric("Google", stats['google'])
            with col3:
                st.metric("OpenStreetMap", stats['osm'])
            with col4:
                st.metric("Duplicates", stats['duplicates'])
            
            st.caption(f"✅ All results are within {radius} km radius")
    
    if st.session_state.restaurants:
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("📍 Interactive Map")
            
            if st.session_state.selected_restaurant:
                st.success(f"⭐ Selected: {st.session_state.selected_restaurant['name']} ({st.session_state.selected_restaurant.get('distance')} km)")
            else:
                st.info("💡 Click any red icon to select")
            
            m = create_map(st.session_state.user_lat, st.session_state.user_lon, 
                          st.session_state.restaurants, st.session_state.selected_restaurant)
            map_data = st_folium(m, width=None, height=600, key="map")
            
            # Handle map clicks
            if map_data and map_data.get("last_object_clicked"):
                clicked_lat = map_data["last_object_clicked"]["lat"]
                clicked_lon = map_data["last_object_clicked"]["lng"]
                
                # Ignore clicks on user location
                if abs(clicked_lat - st.session_state.user_lat) > 0.0001 or abs(clicked_lon - st.session_state.user_lon) > 0.0001:
                    for r in st.session_state.restaurants:
                        if abs(r['lat'] - clicked_lat) < 0.0001 and abs(r['lon'] - clicked_lon) < 0.0001:
                            if not st.session_state.selected_restaurant or st.session_state.selected_restaurant['name'] != r['name']:
                                st.session_state.selected_restaurant = r
                                st.success(f"✅ Selected: {r['name']}")
                                time.sleep(0.3)
                                st.rerun()
                            break
        
        with col2:
            st.subheader("📋 Restaurant List")
            
            # Sort: selected first
            sorted_list = []
            selected = None
            
            for r in st.session_state.restaurants:
                is_sel = bool(st.session_state.selected_restaurant and 
                             r['name'] == st.session_state.selected_restaurant['name'] and
                             abs(r['lat'] - st.session_state.selected_restaurant.get('lat', 0)) < 0.0001)
                if is_sel:
                    selected = r
                else:
                    sorted_list.append(r)
            
            if selected:
                sorted_list.insert(0, selected)
                st.info("⭐ #1 = Selected (from map/list)")
            
            st.caption(f"Showing all {len(sorted_list)} restaurants within radius")
            
            for idx, r in enumerate(sorted_list, 1):
                is_sel = bool(st.session_state.selected_restaurant and 
                             r['name'] == st.session_state.selected_restaurant['name'] and
                             abs(r['lat'] - st.session_state.selected_restaurant.get('lat', 0)) < 0.0001)
                
                label = f"⭐ #1 (SELECTED) - {r['name']} ({r['distance']} km)" if is_sel and idx == 1 else f"{idx}. {r['name']} ({r['distance']} km)"
                
                with st.expander(label, expanded=is_sel):
                    st.markdown(f'<span class="api-badge {r["source"]}">{r["source"].upper()}</span>', unsafe_allow_html=True)
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("📍 Select", key=f"s{idx}"):
                            st.session_state.selected_restaurant = r
                            st.rerun()
                    with col_b:
                        url = f"https://www.google.com/maps/dir/?api=1&origin={st.session_state.user_lat},{st.session_state.user_lon}&destination={r['lat']},{r['lon']}&travelmode=driving"
                        st.link_button("🧭 Directions", url)
                    
                    if is_sel:
                        st.success("✅ Currently selected!")
                    
                    st.divider()
                    
                    st.write(f"**🍽️ Cuisine:** {r['cuisine']}")
                    st.write(f"**📍 Distance:** {r['distance']} km")
                    st.write(f"**📫 Address:** {r['address']}")
                    
                    if r.get('rating') != 'N/A':
                        stars = "⭐" * int(float(r['rating']))
                        st.write(f"**Rating:** {stars} {r['rating']}/5")
                    
                    if r.get('price') != 'N/A':
                        st.write(f"**Price:** {r['price']}")
                    
                    if r.get('is_open') == True:
                        st.success("● OPEN NOW")
                    elif r.get('is_open') == False:
                        st.error("● CLOSED")
                    
                    if r.get('image_url'):
                        st.image(r['image_url'], use_column_width=True)
                    
                    if r.get('phone') and r['phone'] != 'N/A':
                        st.write(f"**📞 Phone:** {r['phone']}")
                    if r.get('website') and r['website'] != 'N/A':
                        st.write(f"**🌐 Website:** [Link]({r['website']})")
                    if r.get('opening_hours') and r['opening_hours'] != 'N/A':
                        st.write(f"**🕐 Hours:** {r['opening_hours']}")

else:


    st.markdown("---")
    st.markdown('<div style="text-align:center;color:#666;"><p>Hybrid Multi-API System with Smart Filters</p><p>Foursquare Places API + Google Places + OpenStreetMap</p></p></div>', unsafe_allow_html=True)

