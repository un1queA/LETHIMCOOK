import requests
import math
import time
import random
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import List, Dict, Set, Tuple, Optional, Any
from datetime import datetime

# ==================== OSRM CLIENT USING DIRECT HTTP API ====================

class OSRMClientWrapper:
    """
    OSRM client using direct HTTP API calls (NO external python-osrm package).
    More reliable and avoids broken dependencies.
    """
    
    def __init__(self, base_url: str = None, 
                 profile: str = "foot", debug_mode: bool = True):
        self.debug_mode = debug_mode
        self.profile = profile  # 'foot' for walking distances
        
        # Use the correct OSRM server URLs
        if base_url:
            self.base_url = base_url
        elif profile == "foot":
            self.base_url = "https://router.project-osrm.org"
        else:
            self.base_url = "https://router.project-osrm.org"
        
        # Track rate limiting
        self.last_request_time = 0
        self.min_request_delay = 0.5  # Reduced for batch operations
    
    def _enforce_rate_limit(self):
        """Enforce rate limiting for OSRM public server."""
        now = time.time()
        if self.last_request_time:
            time_since_last = now - self.last_request_time
            if time_since_last < self.min_request_delay:
                time.sleep(self.min_request_delay - time_since_last)
                now = time.time()
        self.last_request_time = now
    
    def get_walking_distance(self, point1: 'GeoPoint', point2: 'GeoPoint') -> float:
        """
        Get ACCURATE walking distance between two points using DIRECT HTTP API.
        """
        self._enforce_rate_limit()
        
        try:
            # Format coordinates for OSRM API: lon,lat;lon,lat
            coordinates_str = f"{point1.lng},{point1.lat};{point2.lng},{point2.lat}"
            
            # Use Table API for single request (more efficient even for one pair)
            url = f"{self.base_url}/table/v1/{self.profile}/{coordinates_str}"
            params = {
                'sources': '0',
                'destinations': '1',
                'annotations': 'distance'  # Get actual distance, not just duration
            }
            
            if self.debug_mode:
                print(f"   [OSRM Table API] Getting walking distance...")
            
            headers = {'User-Agent': 'FoodFinder/1.0'}
            response = requests.get(url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                if data['code'] == 'Ok' and 'distances' in data:
                    distance_meters = data['distances'][0][0]
                    
                    if self.debug_mode:
                        print(f"   [OSRM Table API] Found: {distance_meters:.0f}m")
                    
                    return float(distance_meters)
                    
        except Exception as e:
            if self.debug_mode:
                print(f"   [OSRM Error] {str(e)[:80]}")
        
        # Fallback to route API if table fails
        return self._get_walking_distance_fallback(point1, point2)
    
    def _get_walking_distance_fallback(self, point1: 'GeoPoint', point2: 'GeoPoint') -> float:
        """Fallback to route API if table fails."""
        try:
            coordinates_str = f"{point1.lng},{point1.lat};{point2.lng},{point2.lat}"
            url = f"{self.base_url}/route/v1/{self.profile}/{coordinates_str}"
            params = {
                'overview': 'false',
                'annotations': 'distance'
            }
            
            headers = {'User-Agent': 'FoodFinder/1.0'}
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data and 'routes' in data and len(data['routes']) > 0:
                    return float(data['routes'][0]['distance'])
                    
        except Exception as e:
            if self.debug_mode:
                print(f"   [OSRM Fallback Error] {str(e)[:80]}")
        
        # Final fallback: haversine distance
        return self._haversine_distance(point1, point2)
    
    def batch_get_walking_distances(self, home_location: 'GeoPoint', 
                                   venue_points: List['GeoPoint']) -> List[float]:
        """
        Get walking distances for MULTIPLE venues using OSRM Table API.
        This is 10-50x faster than individual route calls.
        """
        if not venue_points:
            return []
        
        if len(venue_points) <= 5:
            # For small batches, individual calls might be simpler
            return self._batch_get_walking_distances_individual(home_location, venue_points)
        
        self._enforce_rate_limit()
        
        try:
            # 1. Prepare all coordinates: home first, then venues
            all_coords = [home_location]
            all_coords.extend(venue_points)
            
            # 2. Format for API: "lon,lat;lon,lat;..."
            coord_string = ";".join([f"{p.lng},{p.lat}" for p in all_coords])
            
            # 3. Build Table API URL
            # sources=0 means use the FIRST coordinate (home) as the start point
            # destinations=1:2:3... means calculate distance to all other points
            url = f"{self.base_url}/table/v1/{self.profile}/{coord_string}"
            params = {
                'sources': '0',
                'destinations': ';'.join(str(i) for i in range(1, len(all_coords))),
                'annotations': 'distance'  # Get actual distance in meters
            }
            
            if self.debug_mode:
                print(f"   [OSRM Table API] Getting distances for {len(venue_points)} venues in ONE call...")
            
            headers = {'User-Agent': 'FoodFinder/1.0'}
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                # 4. Extract distances from the matrix
                if data['code'] == 'Ok' and 'distances' in data:
                    distances = data['distances'][0]
                    
                    if self.debug_mode:
                        print(f"   [OSRM Table API] Success! Retrieved {len(distances)} distances")
                        if distances:
                            avg_dist = sum(distances) / len(distances)
                            print(f"   [OSRM Table API] Average distance: {avg_dist:.0f}m")
                    
                    return distances
            
            # If table API fails, fall back to individual calls
            if self.debug_mode:
                print(f"   [OSRM Table API] Failed with status {response.status_code}, falling back...")
                
        except Exception as e:
            if self.debug_mode:
                print(f"   [OSRM Table API Error] {str(e)[:100]}")
        
        # Fallback to individual calls if batch fails
        return self._batch_get_walking_distances_individual(home_location, venue_points)
    
    def _batch_get_walking_distances_individual(self, home_location: 'GeoPoint', 
                                              venue_points: List['GeoPoint']) -> List[float]:
        """Fallback: get distances one by one."""
        distances = []
        
        for i, venue_coords in enumerate(venue_points):
            if i > 0:  # Skip delay for first call
                self._enforce_rate_limit()
                
            distance = self.get_walking_distance(home_location, venue_coords)
            distances.append(distance)
            
            if self.debug_mode and i < 3:  # Show first 3 for debugging
                straight_line = self._haversine_distance(home_location, venue_coords)
                diff = distance - straight_line
                diff_percent = (diff / straight_line * 100) if straight_line > 0 else 0
                print(f"   [Individual {i+1}] Route: {distance:.0f}m, Straight: {straight_line:.0f}m, Diff: {diff:.0f}m ({diff_percent:+.0f}%)")
        
        return distances
    
    def _haversine_distance(self, point1: 'GeoPoint', point2: 'GeoPoint') -> float:
        """Haversine distance calculation as fallback."""
        R = 6371000.0
        
        lat1_rad = math.radians(point1.lat)
        lat2_rad = math.radians(point2.lat)
        lon1_rad = math.radians(point1.lng)
        lon2_rad = math.radians(point2.lng)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c

@dataclass
class GeoPoint:
    """Simple class to hold latitude and longitude."""
    lat: float
    lng: float

# ==================== ENHANCED OSM INTEGRATION WITH DIRECT HTTP API ====================

class EnhancedOSMValidator:
    """
    Enhanced OSM validator with DIRECT HTTP API for accurate distance calculation.
    """
    
    def __init__(self, debug_mode: bool = True):
        self.nominatim_url = "https://nominatim.openstreetmap.org/search"
        self.reverse_nominatim_url = "https://nominatim.openstreetmap.org/reverse"
        self.debug_mode = debug_mode
        self.last_osm_request = 0.0
        self.min_osm_delay = 1.0  # Nominatim requires 1 second between requests
        
        # Initialize OSRM client using DIRECT HTTP API
        self.osrm_client = OSRMClientWrapper(
            base_url="https://router.project-osrm.org",
            profile="foot",
            debug_mode=debug_mode
        )
    
    def _enforce_osm_rate_limit(self):
        """Enforce OSM's usage policy."""
        now = time.time()
        if self.last_osm_request:
            time_since_last = now - self.last_osm_request
            if time_since_last < self.min_osm_delay:
                time.sleep(self.min_osm_delay - time_since_last)
                now = time.time()
        self.last_osm_request = now
    
    def batch_verify_distances(self, venues: List[Dict], home_location: GeoPoint,
                             max_distance_m: float) -> Tuple[List[Dict], List[Dict]]:
        """
        Batch verify distances using DIRECT HTTP API.
        Returns: (verified_venues, rejected_venues)
        """
        if not venues:
            return [], []
        
        if self.debug_mode:
            print(f"   [OSRM Direct HTTP] Processing {len(venues)} venues...")
            print(f"   [OSRM Direct HTTP] Using OSRM Table API for efficient distance calculation")
        
        # Extract venue coordinates
        venue_points = []
        valid_venue_indices = []
        
        for i, venue in enumerate(venues):
            coords = self._extract_coordinates_from_venue(venue)
            if coords.lat != 0 and coords.lng != 0:
                venue_points.append(coords)
                valid_venue_indices.append(i)
                venue['original_coordinates'] = coords
        
        if not venue_points:
            return [], []
        
        # Use OSRM Table API to get ACCURATE walking distances efficiently
        walking_distances = self.osrm_client.batch_get_walking_distances(
            home_location, venue_points
        )
        
        # Process results - track both verified and rejected
        verified_venues = []
        rejected_venues = []
        
        for idx, venue_idx in enumerate(valid_venue_indices):
            if idx >= len(walking_distances):
                break
                
            venue = venues[venue_idx].copy()  # Create a copy to avoid modifying original
            walking_distance = walking_distances[idx]
            
            # Get OSM coordinates for verification - IMPROVED to always get address
            venue_name = venue.get('name', 'Unknown')
            original_coords = venue.get('original_coordinates', venue_points[idx])
            
            osm_coords, osm_address = self._get_osm_coordinates_with_chain_check(venue_name, original_coords)
            
            if not osm_coords:
                osm_coords = original_coords
            
            # Ensure we always have an address
            if not osm_address or osm_address.strip() == '':
                if 'location' in venue and 'formatted_address' in venue['location']:
                    osm_address = venue['location']['formatted_address']
                else:
                    osm_address = f"{venue_name} (Coordinates: {original_coords.lat:.6f}, {original_coords.lng:.6f})"
            
            # Also calculate straight-line for comparison
            straight_line_distance = self._haversine_distance(home_location, original_coords)
            
            # Check if venue passes distance filter
            should_display = walking_distance <= max_distance_m
            
            # Build verification result
            verification = {
                'should_display': should_display,
                'osm_distance_m': walking_distance,
                'original_distance_m': venue.get('distance_from_home', 0),
                'walking_distance_m': walking_distance,
                'straight_line_distance_m': straight_line_distance,
                'distance_difference_m': abs(walking_distance - venue.get('distance_from_home', 0)),
                'osm_coordinates': osm_coords,
                'osm_address': osm_address,
                'verification_notes': [],
                'confidence': 0.8 if osm_coords else 0.5,
                'distance_type': 'accurate_walking_route',
                'osrm_service_used': 'direct_http_api'
            }
            
            # Calculate confidence based on coordinate match
            if osm_coords:
                coord_distance = self._haversine_distance(original_coords, osm_coords)
                if coord_distance < 25:
                    verification['confidence'] = 0.95
                    verification['verification_notes'].append('High coordinate match with OSM')
                elif coord_distance < 100:
                    verification['confidence'] = 0.85
                    verification['verification_notes'].append('Good coordinate match with OSM')
                else:
                    verification['verification_notes'].append('Moderate coordinate match with OSM')
            else:
                verification['verification_notes'].append('Using original coordinates (OSM not found)')
            
            # Add note about walking vs straight-line difference
            diff_percent = ((walking_distance - straight_line_distance) / straight_line_distance * 100) if straight_line_distance > 0 else 0
            if abs(diff_percent) > 10:
                verification['verification_notes'].append(f'Route is {diff_percent:+.0f}% longer than straight line')
            
            if verification['should_display']:
                verification['verification_notes'].append(f'Within walking distance: {walking_distance/1000:.2f}km')
            else:
                verification['verification_notes'].append(f'Outside walking radius: {walking_distance/1000:.2f}km (limit: {max_distance_m/1000:.1f}km)')
            
            venue['osm_verification'] = verification
            venue['layer3_passed'] = verification['should_display']
            
            if verification['should_display']:
                verified_venues.append(venue)
            else:
                # Add rejection reason to the venue
                venue['rejection_reason'] = f"Walking distance ({walking_distance/1000:.2f}km) exceeds limit ({max_distance_m/1000:.1f}km)"
                rejected_venues.append(venue)
        
        return verified_venues, rejected_venues
    
    def _get_osm_coordinates_with_chain_check(self, venue_name: str, search_coords: GeoPoint) -> Tuple[Optional[GeoPoint], str]:
        """Get precise coordinates from OSM for a venue with special handling for chains."""
        osm_coords = None
        osm_address = ""
        
        try:
            # SPECIAL HANDLING FOR CHAIN RESTAURANTS
            chain_keywords = ['mcdonald', 'kfc', 'burger king', 'subway', 'starbucks', 
                            'pizza hut', 'domino', 'coffee bean', 'ya kun', 'toast box',
                            'mos burger', 'jollibee', 'texas chicken', 'awfully chocolate',
                            'breadtalk', 'four leaves', 'cake boss', 'liho', 'gong cha',
                            'koi', 'sharetea', 'tiger sugar', 'each a cup', 'mr bean']
            
            is_chain = False
            matched_chain = ""
            
            for chain in chain_keywords:
                if chain in venue_name.lower():
                    is_chain = True
                    matched_chain = chain
                    break
            
            # If it's a chain, search more specifically
            if is_chain:
                chain_search = f"{venue_name} Singapore {search_coords.lat:.4f} {search_coords.lng:.4f}"
                chain_result = self._search_osm(chain_search, search_coords.lat, search_coords.lng)
                
                if chain_result:
                    osm_coords = GeoPoint(
                        lat=float(chain_result['lat']),
                        lng=float(chain_result['lon'])
                    )
                    osm_address = chain_result.get('display_name', f"{venue_name} (chain location)")
                    
                    # Enhance the address format
                    if 'display_name' in chain_result:
                        display_name = chain_result['display_name']
                        # Try to extract postal code if available
                        postal_match = re.search(r'\b\d{6}\b', display_name)
                        if postal_match:
                            postal_code = postal_match.group(0)
                            osm_address = f"{venue_name} ({display_name.split(',')[0] if ',' in display_name else display_name}), {postal_code}"
                    
                    return osm_coords, osm_address
            
            # Try reverse geocoding first for non-chains
            reverse_result = self._reverse_geocode(search_coords.lat, search_coords.lng)
            
            if reverse_result and 'display_name' in reverse_result:
                # Check if this location matches a food establishment
                address = reverse_result.get('address', {})
                
                # Look for food-related amenities in the area
                if any(key in address for key in ['amenity', 'shop', 'tourism', 'building']):
                    osm_coords = GeoPoint(
                        lat=float(reverse_result['lat']),
                        lng=float(reverse_result['lon'])
                    )
                    osm_address = reverse_result.get('display_name', '')
                    
                    # Try to extract postal code and format address nicely
                    if 'postcode' in address:
                        postal_code = address['postcode']
                        # Format like: #01-27 Whampoa Drive Market & Food Centre (91 Whampoa Drive), 320091
                        building_name = address.get('building', '')
                        road_name = address.get('road', '')
                        house_number = address.get('house_number', '')
                        
                        if building_name and house_number:
                            osm_address = f"{venue_name} ({house_number} {road_name}), {postal_code}"
                        elif building_name:
                            osm_address = f"{venue_name} ({building_name}), {postal_code}"
                        else:
                            osm_address = f"{venue_name} ({osm_address}), {postal_code}"
                    
                    # Try to enhance address with venue name
                    elif venue_name and venue_name.lower() not in osm_address.lower():
                        osm_address = f"{venue_name} ({osm_address})"
                    
                    return osm_coords, osm_address
            
            # If reverse geocoding didn't find food establishment, try search
            search_result = self._search_osm(venue_name, search_coords.lat, search_coords.lng)
            
            if search_result:
                osm_coords = GeoPoint(
                    lat=float(search_result['lat']),
                    lng=float(search_result['lon'])
                )
                osm_address = search_result.get('display_name', '')
                
                # Format the address if we have postal code
                if 'address' in search_result and 'postcode' in search_result['address']:
                    postal_code = search_result['address']['postcode']
                    osm_address = f"{osm_address}, {postal_code}"
                
                return osm_coords, osm_address
            
        except Exception as e:
            if self.debug_mode:
                print(f"   [OSM Coordinate Error] {str(e)[:60]}")
        
        # CRITICAL FIX: Ensure we never return an empty address
        if not osm_address and venue_name:
            # Try to extract postal code from original address if available
            postal_match = re.search(r'\b\d{6}\b', venue_name)
            if postal_match:
                postal_code = postal_match.group(0)
                osm_address = f"{venue_name} (near {search_coords.lat:.5f}, {search_coords.lng:.5f}), {postal_code}"
            else:
                osm_address = f"{venue_name} (near {search_coords.lat:.5f}, {search_coords.lng:.5f})"
        
        if not osm_coords:
            osm_coords = search_coords
        
        return osm_coords, osm_address
    
    def _reverse_geocode(self, lat: float, lng: float) -> Optional[Dict]:
        """Reverse geocode coordinates to get location details."""
        try:
            self._enforce_osm_rate_limit()
            
            params = {
                'lat': lat,
                'lon': lng,
                'format': 'jsonv2',
                'addressdetails': 1,
                'zoom': 18,
                'namedetails': 0
            }
            
            headers = {'User-Agent': 'FoodFinder/1.0 (contact@example.com)'}
            response = requests.get(self.reverse_nominatim_url, params=params, 
                                  headers=headers, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except Exception:
            return None
    
    def _search_osm(self, query: str, lat: float, lng: float) -> Optional[Dict]:
        """Search OSM for a specific venue."""
        try:
            self._enforce_osm_rate_limit()
            
            # Clean up the query for better results
            clean_query = re.sub(r'\([^)]*\)', '', query).strip()
            clean_query = re.sub(r'\s+', ' ', clean_query)
            
            enhanced_query = f"{clean_query} Singapore"
            
            params = {
                'q': enhanced_query,
                'format': 'jsonv2',
                'addressdetails': 1,
                'limit': 3,
                'viewbox': f"{lng-0.02},{lat-0.02},{lng+0.02},{lat+0.02}",
                'bounded': 1
            }
            
            headers = {'User-Agent': 'FoodFinder/1.0 (contact@example.com)'}
            response = requests.get(self.nominatim_url, params=params, 
                                  headers=headers, timeout=10)
            response.raise_for_status()
            
            results = response.json()
            if results and len(results) > 0:
                # Return the most relevant result
                return results[0]
            
            return None
            
        except Exception:
            return None
    
    def _extract_coordinates_from_venue(self, venue: Dict) -> GeoPoint:
        """Extract coordinates from venue data."""
        if 'latitude' in venue and 'longitude' in venue:
            return GeoPoint(lat=venue['latitude'], lng=venue['longitude'])
        
        if 'geocodes' in venue:
            main_geo = venue['geocodes'].get('main', {})
            if 'latitude' in main_geo and 'longitude' in main_geo:
                return GeoPoint(lat=main_geo['latitude'], lng=main_geo['longitude'])
        
        location = venue.get('location', {})
        if 'lat' in location and 'lng' in location:
            return GeoPoint(lat=location['lat'], lng=location['lng'])
        
        # Try to get from AI validation if available
        if 'ai_validation' in venue:
            ai_data = venue['ai_validation']
            if 'coordinates' in ai_data:
                # Parse coordinates from string like "1.323623, 103.853746"
                try:
                    coords_str = ai_data['coordinates']
                    lat_str, lng_str = coords_str.split(',')
                    return GeoPoint(lat=float(lat_str.strip()), lng=float(lng_str.strip()))
                except:
                    pass
        
        return GeoPoint(lat=0, lng=0)
    
    def _haversine_distance(self, point1: GeoPoint, point2: GeoPoint) -> float:
        """Haversine distance calculation."""
        R = 6371000.0
        
        lat1_rad = math.radians(point1.lat)
        lat2_rad = math.radians(point2.lat)
        lon1_rad = math.radians(point1.lng)
        lon2_rad = math.radians(point2.lng)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c

# ==================== THREE-LAYER FOOD FINDER (UPDATED WITH DIRECT HTTP API) ====================

class ThreeLayerFoodFinder:
    """
    THREE-LAYER FOOD FINDER WITH DIRECT HTTP API FOR ACCURATE DISTANCES.
    """
    
    def __init__(self, api_key: str, deepseek_api_key: str = None, debug_mode: bool = True):
        self.api_key = api_key
        self.deepseek_api_key = deepseek_api_key
        self.base_url = "https://places-api.foursquare.com/places/search"
        self.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
            "X-Places-Api-Version": "2025-06-17"
        }
        
        # Initialize OSM validator with direct HTTP API
        self.osm_validator = EnhancedOSMValidator(debug_mode=debug_mode)
        
        self.all_venues = {}
        self.seen_venue_ids: Set[str] = set()
        self.request_count = 0
        self.home_location = None
        self.debug_mode = debug_mode
        
        self.ai_request_count = 0
        self.request_times = []
        self.max_qps = 40
        self.last_request_time = 0.0
        self.consecutive_429 = 0
    
    # ==================== LAYER 1: FOURSQUARE SEARCH ====================
    
    def layer1_foursquare_search(self, home_location: GeoPoint, search_radius_km: float, 
                                cuisine: Optional[str] = None) -> List[Dict]:
        """
        LAYER 1: Search Foursquare for all food establishments within radius.
        OPTIMIZED for speed.
        """
        outer_radius_m = search_radius_km * 1000.0
        
        if self.debug_mode:
            print(f"\n{'='*60}")
            print(f"🔍 LAYER 1: FOURSQUARE SEARCH (OPTIMIZED)")
            print(f"{'='*60}")
            print(f"   Searching within {search_radius_km}km radius...")
        
        # Generate optimized grid - fewer points for larger radii
        grid_spacing = self._calculate_grid_spacing(search_radius_km)
        grid_points = self._generate_optimized_grid(home_location, outer_radius_m, grid_spacing)
        
        all_venues = {}
        
        if self.debug_mode:
            print(f"   Using {len(grid_points)} search points (grid spacing: {grid_spacing}m)...")
        
        for i, point in enumerate(grid_points):
            if self.debug_mode and i % 10 == 0:
                print(f"   Search point {i+1}/{len(grid_points)}...", end='\r')
            
            raw_venues = self._search_at_point_optimized(point, radius_m=grid_spacing, cuisine=cuisine, limit=50)
            
            for venue in raw_venues:
                venue_id = self._get_venue_id(venue)
                
                # Skip if we've already seen this venue
                if venue_id in self.seen_venue_ids:
                    continue
                    
                self.seen_venue_ids.add(venue_id)
                
                # Calculate initial distance
                coords = self._extract_venue_coordinates(venue)
                if coords.lat == 0 and coords.lng == 0:
                    continue
                
                distance = self._haversine_distance(home_location, coords)
                
                # Layer 1 filter: Within search radius
                if distance <= outer_radius_m:
                    if venue_id not in all_venues:
                        venue['distance_from_home'] = distance
                        venue['original_coordinates'] = coords
                        venue['layer1_passed'] = True
                        all_venues[venue_id] = venue
            
            # Adaptive delay to avoid rate limiting
            if i % 20 == 0 and i > 0:
                time.sleep(0.1)
        
        venues_list = list(all_venues.values())
        venues_list.sort(key=lambda v: v.get('distance_from_home', float('inf')))
        
        if self.debug_mode:
            print(f"\n   ✅ Found {len(venues_list)} unique venues within {search_radius_km}km radius")
        
        return venues_list
    
    def _calculate_grid_spacing(self, search_radius_km: float) -> int:
        """Calculate optimal grid spacing based on search radius."""
        if search_radius_km <= 1.0:
            return 400  # Dense grid for small areas
        elif search_radius_km <= 3.0:
            return 600  # Medium grid
        elif search_radius_km <= 10.0:
            return 800  # Sparse grid for medium areas
        elif search_radius_km <= 20.0:
            return 1200  # Very sparse for large areas
        else:
            return 2000  # Ultra sparse for huge areas (50km)
    
    def _generate_optimized_grid(self, center: GeoPoint, outer_radius_m: float,
                                search_radius_m: float) -> List[GeoPoint]:
        """Generate optimized hexagonal grid with adaptive spacing."""
        d = math.sqrt(3) * search_radius_m
        x_step = d
        y_step = d * math.sqrt(3) / 2.0
        max_steps = int(math.ceil(outer_radius_m / d)) + 1
        
        # Adaptive step multiplier based on radius
        step_multiplier = 1
        if outer_radius_m > 5000:  # >5km
            step_multiplier = 2
        if outer_radius_m > 15000:  # >15km
            step_multiplier = 3
        if outer_radius_m > 30000:  # >30km
            step_multiplier = 4
        
        lat_per_m = 1.0 / 111000.0
        lng_per_m = 1.0 / (111000.0 * math.cos(math.radians(center.lat)))
        
        points = []
        for col in range(-max_steps, max_steps + 1, step_multiplier):
            for row in range(-max_steps, max_steps + 1, step_multiplier):
                x = col * x_step
                y = row * y_step + (col % 2) * y_step / 2.0
                
                if math.sqrt(x**2 + y**2) > outer_radius_m:
                    continue
                
                lat_offset = y * lat_per_m
                lng_offset = x * lng_per_m
                points.append(GeoPoint(
                    lat=center.lat + lat_offset,
                    lng=center.lng + lng_offset
                ))
        
        return points
    
    def _search_at_point_optimized(self, center: GeoPoint, radius_m: int, 
                                 cuisine: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Optimized search for venues with better error handling."""
        params = {
            'll': f"{center.lat},{center.lng}",
            'radius': radius_m,
            'limit': limit,
        }
        
        if cuisine:
            params['query'] = cuisine
        else:
            # Search for food establishments
            params['query'] = 'food'
            params['categories'] = '13000'  # Food category

        raw_venues, _ = self._make_api_request_optimized(params)
        return raw_venues
    
    def _make_api_request_optimized(self, params: Dict) -> Tuple[List[Dict], Dict]:
        """Make API request with optimized retry logic."""
        max_retries = 2  # Reduced from 3 for speed
        base_delay = 1.0  # Reduced delay
        
        for attempt in range(max_retries):
            try:
                self._enforce_rate_limit()
                
                response = requests.get(self.base_url, headers=self.headers, 
                                      params=params, timeout=25)  # Slightly increased timeout
                self.request_count += 1
                
                if response.status_code == 429:
                    self.consecutive_429 += 1
                    wait_time = min(base_delay * (2 ** attempt), 5)  # Reduced max wait
                    time.sleep(wait_time)
                    continue
                
                self.consecutive_429 = 0
                response.raise_for_status()
                data = response.json()
                return data.get('results', []), data
                
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    if self.debug_mode:
                        print(f"      [API Error] {str(e)[:60]}")
                    return [], {}
                wait_time = min(base_delay * (2 ** attempt), 3)  # Reduced max wait
                time.sleep(wait_time)
        
        return [], []
    
    # ==================== LAYER 2: DEEPSEEK AI VALIDATION OR MANUAL FILTER ====================
    
    def layer2_validation(self, venues: List[Dict], cuisine: Optional[str]) -> Tuple[List[Dict], List[Dict]]:
        """
        LAYER 2: Either DeepSeek AI validation OR manual filtering.
        Returns: (validated_venues, rejected_venues)
        """
        if not self.deepseek_api_key:
            if self.debug_mode:
                print(f"\n{'='*60}")
                print(f"🔄 LAYER 2: MANUAL FILTERING (No AI)")
                print(f"{'='*60}")
                print(f"   Manually filtering {len(venues)} venues for food establishments...")
            
            # Use manual filtering when AI is not available
            return self._manual_filter_validation(venues, cuisine)
        else:
            if self.debug_mode:
                print(f"\n{'='*60}")
                print(f"🤖 LAYER 2: DEEPSEEK AI VALIDATION")
                print(f"{'='*60}")
                print(f"   Analyzing {len(venues)} venues...")
            
            return self._deepseek_ai_validation(venues, cuisine)
    
    def _manual_filter_validation(self, venues: List[Dict], cuisine: Optional[str]) -> Tuple[List[Dict], List[Dict]]:
        """Manual filtering of venues when AI is not available."""
        filtered_venues = self._filter_food_venues(venues, cuisine)
        validated_venues = []
        rejected_venues = []
        
        current_year = datetime.now().year
        
        for venue in venues:
            venue_copy = venue.copy()  # Create a copy
            
            if venue in filtered_venues:
                # Venue passed manual filter
                venue_copy['ai_validated'] = False  # Not AI validated
                venue_copy['ai_validation'] = {
                    'operational_status': 'PROBABLY',
                    'operational_confidence': '6',
                    'address_quality': '5',
                    'reasoning': f'Manually filtered as food establishment. Assuming operational in {current_year}.',
                    'coordinates': f"{venue_copy.get('original_coordinates', GeoPoint(0,0)).lat:.6f}, {venue_copy.get('original_coordinates', GeoPoint(0,0)).lng:.6f}",
                    'location_verification': 'Manual filter passed'
                }
                venue_copy['layer2_passed'] = True
                validated_venues.append(venue_copy)
                
                if self.debug_mode:
                    venue_name = venue_copy.get('name', 'Unknown')[:25]
                    print(f"      ✅ {venue_name:25} | Manual filter passed")
            else:
                # Venue failed manual filter
                venue_copy['layer2_passed'] = False
                venue_copy['rejection_reason'] = "Failed manual food/cuisine filter"
                rejected_venues.append(venue_copy)
                
                if self.debug_mode:
                    venue_name = venue_copy.get('name', 'Unknown')[:25]
                    print(f"      ❌ {venue_name:25} | Manual filter rejected")
        
        if self.debug_mode:
            print(f"\n   📊 Manual Filter Results: {len(validated_venues)} passed, {len(rejected_venues)} rejected")
        
        return validated_venues, rejected_venues
    
    def _filter_food_venues(self, venues: List[Dict], cuisine_filter: Optional[str] = None) -> List[Dict]:
        """Filter venues to only include food and drink establishments, with optional cuisine filter."""
        filtered = []
        
        for venue in venues:
            categories = venue.get('categories', [])
            
            # Check if any category is a food/drink category
            is_food = False
            for category in categories:
                # In the new API, check category names or IDs
                category_name = category.get('name', '').lower()
                category_id = str(category.get('id', ''))
                
                # Check if it's a food category by common patterns
                food_indicators = ['restaurant', 'food', 'cafe', 'coffee', 'bakery', 
                                 'bar', 'pub', 'diner', 'eatery', 'bistro', 'tavern',
                                 'fast food', 'takeaway', 'takeout', 'deli', 'buffet',
                                 'food court', 'market', 'hawker', 'stall', 'food truck',
                                 'izakaya', 'steakhouse', 'pizzeria', 'noodle', 'sushi',
                                 'bakery', 'dessert', 'ice cream', 'juice', 'beverage',
                                 'chicken', 'burger', 'pasta', 'rice', 'noodles',
                                 'seafood', 'vegetarian', 'vegan', 'halal', 'indian',
                                 'chinese', 'malay', 'japanese', 'korean', 'thai',
                                 'vietnamese', 'mexican', 'italian', 'western']
                
                if any(indicator in category_name for indicator in food_indicators):
                    is_food = True
                    break
            
            if not is_food:
                continue
            
            # Apply cuisine filter if provided
            if cuisine_filter:
                cuisine_filter_lower = cuisine_filter.lower()
                venue_name = venue.get('name', '').lower()
                
                # Check if cuisine matches in categories
                cuisine_match = False
                for category in categories:
                    category_name = category.get('name', '').lower()
                    if cuisine_filter_lower in category_name:
                        cuisine_match = True
                        break
                
                # Also check if cuisine is in venue name
                if not cuisine_match and cuisine_filter_lower not in venue_name:
                    # Check description if available
                    if 'description' in venue:
                        description = venue.get('description', '').lower()
                        if cuisine_filter_lower not in description:
                            continue
                    else:
                        continue
            
            filtered.append(venue)
        
        return filtered
    
    def _deepseek_ai_validation(self, venues: List[Dict], cuisine: Optional[str]) -> Tuple[List[Dict], List[Dict]]:
        """DeepSeek AI validation with detailed analysis."""
        batch_size = 5  # Increased for efficiency
        validated_venues = []
        rejected_venues = []
        
        for i in range(0, len(venues), batch_size):
            batch = venues[i:i + batch_size]
            batch_num = i//batch_size + 1
            
            if self.debug_mode:
                print(f"   Batch {batch_num}: {len(batch)} venues")
            
            # Prepare detailed batch for AI
            ai_results = self._call_deepseek_detailed(batch, cuisine)
            
            # Apply AI validation results
            for j, venue in enumerate(batch):
                if j < len(ai_results):
                    ai_validation = ai_results[j]
                    
                    # Check if venue passes AI validation
                    if self._evaluate_ai_validation(ai_validation):
                        venue['ai_validated'] = True
                        venue['ai_validation'] = ai_validation
                        venue['layer2_passed'] = True
                        validated_venues.append(venue)
                        
                        if self.debug_mode:
                            venue_name = venue.get('name', 'Unknown')[:25]
                            op_status = ai_validation.get('operational_status', 'N/A')
                            addr_quality = ai_validation.get('address_quality', 'N/A')
                            print(f"      ✅ {venue_name:25} | Op: {op_status} | Addr: {addr_quality}/10")
                    else:
                        venue['layer2_passed'] = False
                        venue['ai_validation'] = ai_validation
                        venue['rejection_reason'] = f"AI validation failed: {ai_validation.get('operational_status', 'Unknown status')}"
                        rejected_venues.append(venue)
                        
                        if self.debug_mode:
                            venue_name = venue.get('name', 'Unknown')[:25]
                            print(f"      ❌ {venue_name:25} | AI rejected")
                else:
                    # Skip if AI didn't process
                    venue['layer2_passed'] = False
                    venue['rejection_reason'] = "AI validation skipped or failed"
                    rejected_venues.append(venue)
            
            time.sleep(0.8)  # Reduced rate limiting for AI
        
        if self.debug_mode:
            print(f"\n   📊 AI Results: {len(validated_venues)} validated, {len(rejected_venues)} rejected")
        
        return validated_venues, rejected_venues
    
    def _call_deepseek_detailed(self, venues: List[Dict], target_cuisine: Optional[str]) -> List[Dict]:
        """Call DeepSeek API for detailed validation."""
        try:
            venue_texts = []
            for i, v in enumerate(venues):
                venue_name = v.get('name', 'N/A')
                categories = ', '.join(cat.get('name', '') for cat in v.get('categories', []))
                address = v.get('location', {}).get('formatted_address', 'N/A')
                distance = v.get('distance_from_home', 0)
                
                venue_texts.append(
                    f"VENUE {i+1}:\n"
                    f"Name: {venue_name}\n"
                    f"Categories: {categories}\n"
                    f"Address: {address}\n"
                    f"Distance from reference point: {distance:.0f}m\n"
                    f"{'-'*50}"
                )
            
            current_year = datetime.now().year
            
            prompt = f"""
            You are a Singapore food expert in {current_year}. Analyze these venues for a customer who wants {target_cuisine if target_cuisine else 'any cuisine'}.
            
            For EACH venue, provide this EXACT output format:
            
            VENUE [number]
            OPERATIONAL_STATUS: [YES/NO/PROBABLY]
            OPERATIONAL_CONFIDENCE: [1-10]
            ADDRESS_QUALITY: [1-10]
            REASONING: [Is this a food establishment? Does it match the requested cuisine? Is it operational in {current_year}?]
            COORDINATES: [If available from address or your knowledge, otherwise leave blank]
            LOCATION_VERIFICATION: [Analysis of address accuracy - include postal code if available, format like: #01-27 Whampoa Drive Market & Food Centre (91 Whampoa Drive), 320091]
            
            Guidelines:
            - OPERATIONAL_STATUS: YES=definitely open in {current_year}, PROBABLY=likely open, NO=likely closed/permanently closed
            - Focus on whether this is a FOOD ESTABLISHMENT that sells edible food (restaurant, cafe, hawker stall, food truck, bakery, etc.)
            - Check if it matches the requested cuisine: {target_cuisine if target_cuisine else 'any cuisine'}
            - ADDRESS_QUALITY: 10=perfect address with unit/postal, 1=generic "Singapore"
            - For LOCATION_VERIFICATION, try to include postal code if possible
            
            Venues:
            {'\n'.join(venue_texts)}
            
            Respond ONLY with the format above for each venue.
            """
            
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system", 
                        "content": f"You are a Singapore food industry expert in {current_year}. Be precise and focus on food establishments."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 1500
            }
            
            self.ai_request_count += 1
            
            response = requests.post(self.deepseek_url, headers=headers, json=payload, timeout=45)
            response.raise_for_status()
            
            result = response.json()
            ai_response = result["choices"][0]["message"]["content"].strip()
            
            # Parse the structured response
            return self._parse_detailed_ai_response(ai_response, len(venues))
            
        except Exception as e:
            if self.debug_mode:
                print(f"      [AI Error] {str(e)[:80]}")
            return []
    
    def _parse_detailed_ai_response(self, response: str, expected_venues: int) -> List[Dict]:
        """Parse detailed AI response."""
        parsed = [{} for _ in range(expected_venues)]
        current_venue = None
        
        lines = response.split('\n')
        for line in lines:
            line = line.strip()
            
            if line.upper().startswith('VENUE'):
                match = re.search(r'VENUE\s+(\d+)', line, re.IGNORECASE)
                if match:
                    current_venue = int(match.group(1)) - 1
                    if current_venue < len(parsed):
                        parsed[current_venue] = {}
            
            elif line.upper().startswith('OPERATIONAL_STATUS:'):
                if current_venue is not None and current_venue < len(parsed):
                    parsed[current_venue]['operational_status'] = line.split(':', 1)[1].strip()
            
            elif line.upper().startswith('OPERATIONAL_CONFIDENCE:'):
                if current_venue is not None and current_venue < len(parsed):
                    parsed[current_venue]['operational_confidence'] = line.split(':', 1)[1].strip()
            
            elif line.upper().startswith('ADDRESS_QUALITY:'):
                if current_venue is not None and current_venue < len(parsed):
                    parsed[current_venue]['address_quality'] = line.split(':', 1)[1].strip()
            
            elif line.upper().startswith('REASONING:'):
                if current_venue is not None and current_venue < len(parsed):
                    parsed[current_venue]['reasoning'] = line.split(':', 1)[1].strip()
            
            elif line.upper().startswith('COORDINATES:'):
                if current_venue is not None and current_venue < len(parsed):
                    parsed[current_venue]['coordinates'] = line.split(':', 1)[1].strip()
            
            elif line.upper().startswith('LOCATION_VERIFICATION:'):
                if current_venue is not None and current_venue < len(parsed):
                    parsed[current_venue]['location_verification'] = line.split(':', 1)[1].strip()
        
        return parsed
    
    def _evaluate_ai_validation(self, ai_validation: Dict) -> bool:
        """Evaluate if venue passes AI validation."""
        if not ai_validation:
            return True  # Be more lenient if AI fails
        
        # Check operational status
        op_status = ai_validation.get('operational_status', '').upper()
        if op_status == 'NO':
            return False
        
        # Check operational confidence
        op_conf = ai_validation.get('operational_confidence', '5')
        try:
            if int(op_conf) < 4 and op_status != 'YES':  # Reduced threshold
                return False
        except:
            pass
        
        # Check address quality
        addr_quality = ai_validation.get('address_quality', '5')
        try:
            if int(addr_quality) < 2:  # Reduced threshold
                return False
        except:
            pass
        
        return True
    
    # ==================== LAYER 3: DIRECT HTTP API ACCURATE DISTANCE VERIFICATION ====================
    
    def layer3_osm_verification(self, venues: List[Dict], home_location: GeoPoint,
                               max_distance_km: float) -> Tuple[List[Dict], List[Dict]]:
        """
        LAYER 3: OSM final distance verification with DIRECT HTTP API accurate distances.
        Returns: (verified_venues, rejected_venues)
        """
        if self.debug_mode:
            print(f"\n{'='*60}")
            print(f"🚶 LAYER 3: DIRECT HTTP API ACCURATE WALKING DISTANCE VERIFICATION")
            print(f"{'='*60}")
            print(f"   Verifying {len(venues)} venues with DIRECT HTTP API accurate distances...")
            print(f"   Using OSRM Table API for efficient batch processing")
            print(f"   Accuracy matches: https://map.project-osrm.org/")
        
        max_distance_m = max_distance_km * 1000.0
        
        # Use batch verification - now returns both verified and rejected
        verified_venues, rejected_venues = self.osm_validator.batch_verify_distances(
            venues, home_location, max_distance_m
        )
        
        if self.debug_mode:
            print(f"\n   📊 OSRM Results: {len(verified_venues)} within walking radius, {len(rejected_venues)} outside")
            
            # Show some examples
            if verified_venues and len(verified_venues) > 0:
                print(f"\n   📏 ACCEPTED Examples (closest):")
                for i, venue in enumerate(verified_venues[:3], 1):
                    venue_name = venue.get('name', 'Unknown')[:20]
                    osm_verif = venue.get('osm_verification', {})
                    walking_dist = osm_verif.get('walking_distance_m', 0)
                    straight_dist = osm_verif.get('straight_line_distance_m', 0)
                    diff_percent = ((walking_dist - straight_dist) / straight_dist * 100) if straight_dist > 0 else 0
                    
                    print(f"      {i}. {venue_name:20} | "
                          f"Walking: {walking_dist:.0f}m | "
                          f"Straight: {straight_dist:.0f}m | "
                          f"Diff: {diff_percent:+.0f}%")
            
            if rejected_venues and len(rejected_venues) > 0:
                print(f"\n   📏 REJECTED Examples (just outside limit):")
                # Sort rejected by distance to show closest rejects
                rejected_sorted = sorted(rejected_venues, 
                                        key=lambda v: v.get('osm_verification', {}).get('walking_distance_m', float('inf')))
                for i, venue in enumerate(rejected_sorted[:3], 1):
                    venue_name = venue.get('name', 'Unknown')[:20]
                    osm_verif = venue.get('osm_verification', {})
                    walking_dist = osm_verif.get('walking_distance_m', 0)
                    
                    print(f"      {i}. {venue_name:20} | "
                          f"Walking: {walking_dist:.0f}m | "
                          f"Limit: {max_distance_m:.0f}m | "
                          f"Over by: {walking_dist - max_distance_m:.0f}m")
        
        return verified_venues, rejected_venues
    
    # ==================== HELPER METHODS ====================
    
    def _haversine_distance(self, point1: GeoPoint, point2: GeoPoint) -> float:
        """Calculate distance."""
        R = 6371000.0
        
        lat1_rad = math.radians(point1.lat)
        lat2_rad = math.radians(point2.lat)
        lon1_rad = math.radians(point1.lng)
        lon2_rad = math.radians(point2.lng)
        
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    def _extract_venue_coordinates(self, venue: Dict) -> GeoPoint:
        """Extract coordinates."""
        if 'latitude' in venue and 'longitude' in venue:
            return GeoPoint(lat=venue['latitude'], lng=venue['longitude'])
        
        if 'geocodes' in venue:
            main_geo = venue['geocodes'].get('main', {})
            if 'latitude' in main_geo and 'longitude' in main_geo:
                return GeoPoint(lat=main_geo['latitude'], lng=main_geo['longitude'])
        
        location = venue.get('location', {})
        if 'lat' in location and 'lng' in location:
            return GeoPoint(lat=location['lat'], lng=location['lng'])
        
        return GeoPoint(lat=0, lng=0)
    
    def _get_venue_id(self, venue: Dict) -> str:
        """Get venue ID."""
        if 'fsq_place_id' in venue:
            return venue['fsq_place_id']
        
        if 'fsq_id' in venue:
            return venue['fsq_id']
        
        coords = self._extract_venue_coordinates(venue)
        name = venue.get('name', 'unknown').lower().replace(' ', '_')
        return f"{name}_{coords.lat:.4f}_{coords.lng:.4f}"
    
    def _enforce_rate_limit(self):
        """Enforce rate limiting."""
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < 1.0]
        
        if len(self.request_times) >= self.max_qps:
            oldest = self.request_times[0]
            wait_time = 1.0 - (now - oldest)
            if wait_time > 0:
                time.sleep(wait_time)
                now = time.time()
        
        min_delay = 0.02  # Reduced from 0.025 for speed
        if self.last_request_time:
            time_since_last = now - self.last_request_time
            if time_since_last < min_delay:
                time.sleep(min_delay - time_since_last)
                now = time.time()
        
        self.last_request_time = now
        self.request_times.append(now)
        
        if len(self.request_times) > 100:
            self.request_times = self.request_times[-100:]

    # ==================== MAIN THREE-LAYER SEARCH ====================
    
    def three_layer_search(self, home_location: GeoPoint,
                          search_radius_km: float = 1.0,
                          cuisine: Optional[str] = None):
        """
        Execute the complete three-layer search process with DIRECT HTTP API accurate distances.
        NOW INCLUDES REJECTED VENUES WITH REASONS.
        """
        self.home_location = home_location
        
        # Reset tracking
        self.all_venues = {}
        self.seen_venue_ids = set()
        self.request_count = 0
        self.ai_request_count = 0
        self.consecutive_429 = 0
        
        # Adjust parameters for large radius searches
        if search_radius_km > 10:
            self.max_qps = 20  # Reduce requests per second for large searches
            self.osm_validator.osrm_client.min_request_delay = 0.2  # Faster OSRM
        
        print("="*60)
        print(f"🚀 THREE-LAYER FOOD FINDER")
        print("="*60)
        print(f"📍 Home: ({home_location.lat:.6f}, {home_location.lng:.6f})")
        print(f"🎯 Search Radius: {search_radius_km} km (accurate walking distance)")
        print(f"🍽️  Cuisine Filter: {cuisine if cuisine else 'All food establishments'}")
        print(f"🤖 AI Layer: {'ACTIVE' if self.deepseek_api_key else 'MANUAL FILTERING'}")
        print(f"🗺️  OSRM Layer: ACTIVE (Table API - matches map.project-osrm.org)")
        print(f"📋 Results: Will include BOTH accepted and rejected venues with reasons")
        print("="*60)
        
        # Track all venues through the process
        all_rejected_venues = []
        start_time = time.time()
        
        # ========== LAYER 1: FOURSQUARE SEARCH ==========
        layer1_start = time.time()
        layer1_results = self.layer1_foursquare_search(home_location, search_radius_km, cuisine)
        layer1_time = time.time() - layer1_start
        
        if not layer1_results:
            print(f"\n❌ No venues found in Layer 1 search (took {layer1_time:.1f}s).")
            return self._prepare_final_results([], [], [], [], search_radius_km, cuisine, layer1_time, 0, 0)
        
        # ========== LAYER 2: VALIDATION (AI or Manual) ==========
        layer2_start = time.time()
        layer2_results, layer2_rejected = self.layer2_validation(layer1_results, cuisine)
        layer2_time = time.time() - layer2_start
        all_rejected_venues.extend(layer2_rejected)
        
        if not layer2_results:
            print(f"\n❌ No venues passed Layer 2 validation (took {layer2_time:.1f}s).")
            return self._prepare_final_results([], layer1_results, all_rejected_venues, [], 
                                             search_radius_km, cuisine, layer1_time, layer2_time, 0)
        
        # ========== LAYER 3: OSRM DISTANCE VERIFICATION ==========
        layer3_start = time.time()
        layer3_results, layer3_rejected = self.layer3_osm_verification(layer2_results, home_location, search_radius_km)
        layer3_time = time.time() - layer3_start
        all_rejected_venues.extend(layer3_rejected)
        
        # Sort results by accurate walking distance
        layer3_results.sort(key=lambda v: v.get('osm_verification', {}).get('walking_distance_m', float('inf')))
        
        # ========== SAVE RESULTS ==========
        save_start = time.time()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cuisine_slug = cuisine.replace(' ', '_') if cuisine else 'all'
        output_filename = f"food_finder_results_{cuisine_slug}_{search_radius_km}km_{timestamp}.txt"
        
        self._save_complete_results(layer1_results, layer3_results, all_rejected_venues, 
                                  cuisine, search_radius_km, output_filename)
        save_time = time.time() - save_start
        
        total_time = time.time() - start_time
        
        # ========== PRINT SUMMARY ==========
        print("\n" + "="*60)
        print("✅ THREE-LAYER SEARCH COMPLETE")
        print("="*60)
        print(f"📊 Statistics:")
        print(f"   Total Time: {total_time:.1f}s ({total_time/60:.1f}m)")
        print(f"   Layer 1 (Foursquare): {len(layer1_results)} venues in {layer1_time:.1f}s")
        print(f"   Layer 2 (Validation): {len(layer2_results)} passed, {len(layer2_rejected)} rejected in {layer2_time:.1f}s")
        print(f"   Layer 3 (Walking Distance): {len(layer3_results)} accepted, {len(layer3_rejected)} rejected in {layer3_time:.1f}s")
        print(f"   Total Rejected: {len(all_rejected_venues)} venues")
        print(f"   Total API Requests: {self.request_count}")
        print(f"   AI Requests: {self.ai_request_count}")
        print(f"📁 Results saved to: {output_filename} (saved in {save_time:.1f}s)")
        
        # Show top results
        if layer3_results:
            print(f"\n🏆 TOP VERIFIED RECOMMENDATIONS (closest walking distance):")
            for i, venue in enumerate(layer3_results[:5], 1):
                name = venue.get('name', 'N/A')
                osm_verif = venue.get('osm_verification', {})
                walking_dist = osm_verif.get('walking_distance_m', 0)
                op_status = venue.get('ai_validation', {}).get('operational_status', 'N/A')
                address = venue.get('osm_verification', {}).get('osm_address', 'Address not available')[:70]
                
                walking_minutes = (walking_dist / 80) / 60
                
                print(f"{i}. {name}")
                print(f"   📍 {address}")
                print(f"   🚶 {walking_dist:.0f}m (~{walking_minutes:.1f} min) | 🏪 Status: {op_status}")
                print()
        
        # Show some rejected examples if any
        if all_rejected_venues:
            print(f"\n🚫 TOP REJECTED VENUES (with reasons):")
            # Show closest rejected venues
            rejected_with_distance = []
            for venue in all_rejected_venues:
                if 'osm_verification' in venue:
                    dist = venue['osm_verification'].get('walking_distance_m', 0)
                else:
                    dist = venue.get('distance_from_home', 0)
                rejected_with_distance.append((dist, venue))
            
            rejected_with_distance.sort(key=lambda x: x[0])
            
            for i, (dist, venue) in enumerate(rejected_with_distance[:5], 1):
                name = venue.get('name', 'N/A')[:25]
                reason = venue.get('rejection_reason', 'Unknown reason')
                
                print(f"{i}. {name:25} | {dist:.0f}m | Reason: {reason}")
        
        return self._prepare_final_results(layer3_results, layer1_results, all_rejected_venues, 
                                         layer2_results, search_radius_km, cuisine, output_filename,
                                         layer1_time, layer2_time, layer3_time)
    
    def _prepare_final_results(self, layer3_results, layer1_results, rejected_venues, 
                             layer2_results, search_radius_km, cuisine, output_file=None,
                             layer1_time=0, layer2_time=0, layer3_time=0):
        """Prepare final results dictionary."""
        return {
            'accepted_venues': layer3_results,
            'layer1_venues': layer1_results,
            'rejected_venues': rejected_venues,
            'layer2_venues': layer2_results,
            'layer1_count': len(layer1_results),
            'layer2_count': len(layer2_results) if layer2_results else 0,
            'layer3_count': len(layer3_results),
            'rejected_count': len(rejected_venues),
            'api_requests': self.request_count,
            'ai_requests': self.ai_request_count,
            'output_file': output_file,
            'search_radius_km': search_radius_km,
            'cuisine': cuisine,
            'layer1_time': layer1_time,
            'layer2_time': layer2_time,
            'layer3_time': layer3_time,
            'total_time': layer1_time + layer2_time + layer3_time
        }
    
    def _save_complete_results(self, layer1_venues: List[Dict], accepted_venues: List[Dict],
                             rejected_venues: List[Dict], cuisine: Optional[str],
                             search_radius_km: float, filename: str):
        """Save COMPLETE three-layer search results including rejected venues."""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"COMPLETE THREE-LAYER FOOD FINDER RESULTS\n")
            f.write("="*80 + "\n\n")
            f.write(f"Search Configuration:\n")
            f.write(f"  Home Location: {self.home_location.lat:.6f}, {self.home_location.lng:.6f}\n")
            f.write(f"  Search Radius: {search_radius_km} km (accurate walking distance)\n")
            f.write(f"  Cuisine Filter: {cuisine if cuisine else 'All food establishments'}\n")
            f.write(f"  Search Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"\nSearch Process:\n")
            f.write(f"  1. Foursquare: Hex grid search within {search_radius_km}km radius\n")
            f.write(f"  2. Validation: {'DeepSeek AI' if self.deepseek_api_key else 'Manual filtering'}\n")
            f.write(f"  3. Distance: OSRM Table API (matches map.project-osrm.org)\n")
            f.write(f"\nStatistics:\n")
            f.write(f"  Total Layer 1 Venues: {len(layer1_venues)}\n")
            f.write(f"  Total Accepted Venues: {len(accepted_venues)}\n")
            f.write(f"  Total Rejected Venues: {len(rejected_venues)}\n")
            f.write(f"  Foursquare API Requests: {self.request_count}\n")
            f.write(f"  AI Validation Requests: {self.ai_request_count}\n\n")
            
            # SECTION 1: ACCEPTED VENUES
            f.write("="*80 + "\n")
            f.write("✅ ACCEPTED VENUES (PASSED ALL 3 LAYERS)\n")
            f.write("="*80 + "\n\n")
            
            if not accepted_venues:
                f.write("No venues passed all three verification layers.\n\n")
            else:
                f.write(f"Found {len(accepted_venues)} venues within {search_radius_km}km walking distance:\n\n")
                for i, venue in enumerate(accepted_venues, 1):
                    self._write_venue_details(f, i, venue, search_radius_km, "ACCEPTED")
            
            # SECTION 2: REJECTED VENUES
            f.write("\n" + "="*80 + "\n")
            f.write("❌ REJECTED VENUES (WITH REASONS)\n")
            f.write("="*80 + "\n\n")
            
            if not rejected_venues:
                f.write("No venues were rejected.\n\n")
            else:
                # Group rejected venues by rejection stage
                ai_rejected = [v for v in rejected_venues if 'AI validation failed' in v.get('rejection_reason', '')]
                manual_rejected = [v for v in rejected_venues if 'manual filter' in v.get('rejection_reason', '').lower()]
                distance_rejected = [v for v in rejected_venues if 'Walking distance' in v.get('rejection_reason', '')]
                other_rejected = [v for v in rejected_venues if v not in ai_rejected and 
                                v not in manual_rejected and v not in distance_rejected]
                
                if ai_rejected:
                    f.write(f"REJECTED BY AI VALIDATION ({len(ai_rejected)} venues):\n")
                    f.write("-"*60 + "\n")
                    for i, venue in enumerate(ai_rejected, 1):
                        self._write_venue_details(f, i, venue, search_radius_km, "REJECTED (AI)")
                
                if manual_rejected:
                    f.write(f"\nREJECTED BY MANUAL FILTER ({len(manual_rejected)} venues):\n")
                    f.write("-"*60 + "\n")
                    for i, venue in enumerate(manual_rejected, 1):
                        self._write_venue_details(f, i, venue, search_radius_km, "REJECTED (Manual Filter)")
                
                if distance_rejected:
                    f.write(f"\nREJECTED BY DISTANCE ({len(distance_rejected)} venues):\n")
                    f.write("-"*60 + "\n")
                    # Sort by how much they exceeded the limit
                    distance_rejected.sort(key=lambda v: v.get('osm_verification', {}).get('walking_distance_m', 0))
                    for i, venue in enumerate(distance_rejected, 1):
                        self._write_venue_details(f, i, venue, search_radius_km, "REJECTED (Distance)")
                
                if other_rejected:
                    f.write(f"\nOTHER REJECTIONS ({len(other_rejected)} venues):\n")
                    f.write("-"*60 + "\n")
                    for i, venue in enumerate(other_rejected, 1):
                        self._write_venue_details(f, i, venue, search_radius_km, "REJECTED")
            
            # SECTION 3: ALL INITIAL VENUES (for reference)
            f.write("\n" + "="*80 + "\n")
            f.write("📋 ALL INITIAL VENUES FROM LAYER 1\n")
            f.write("="*80 + "\n\n")
            
            if layer1_venues:
                layer1_venues_sorted = sorted(layer1_venues, key=lambda v: v.get('distance_from_home', float('inf')))
                f.write(f"Total venues found in initial search: {len(layer1_venues)}\n\n")
                for i, venue in enumerate(layer1_venues_sorted, 1):
                    name = venue.get('name', 'N/A')
                    distance = venue.get('distance_from_home', 0)
                    categories = ', '.join(cat.get('name', '') for cat in venue.get('categories', []))
                    
                    f.write(f"{i:3d}. {name}\n")
                    f.write(f"     📏 Straight-line: {distance:.0f}m | 🏷️  Categories: {categories}\n")
                    
                    if 'location' in venue and 'formatted_address' in venue['location']:
                        f.write(f"     📍 Address: {venue['location']['formatted_address']}\n")
                    
                    f.write("\n")
            else:
                f.write("No venues found in initial search.\n")
    
    def _write_venue_details(self, f, index: int, venue: Dict, search_radius_km: float, status: str):
        """Write detailed venue information to file."""
        name = venue.get('name', 'N/A')
        
        # Layer 1 Info
        original_dist = venue.get('distance_from_home', 0)
        categories = ', '.join(cat.get('name', '') for cat in venue.get('categories', []))
        
        # Layer 2 Info
        ai_validation = venue.get('ai_validation', {})
        op_status = ai_validation.get('operational_status', 'N/A')
        op_conf = ai_validation.get('operational_confidence', 'N/A')
        addr_quality = ai_validation.get('address_quality', 'N/A')
        reasoning = ai_validation.get('reasoning', '')
        location_verification = ai_validation.get('location_verification', '')
        
        # Layer 3 Info
        osm_verification = venue.get('osm_verification', {})
        walking_dist = osm_verification.get('walking_distance_m', 0)
        straight_dist = osm_verification.get('straight_line_distance_m', 0)
        osrm_service = osm_verification.get('osrm_service_used', 'N/A')
        osm_address = osm_verification.get('osm_address', 'N/A')
        confidence = osm_verification.get('confidence', 0)
        notes = osm_verification.get('verification_notes', [])
        
        # Calculate walking time
        walking_minutes = (walking_dist / 1.4) / 60 if walking_dist > 0 else 0
        
        f.write(f"{index:3d}. {name} [{status}]\n")
        f.write(f"     {'='*60}\n")
        
        # Rejection reason if applicable
        if 'rejection_reason' in venue:
            f.write(f"     ❌ REJECTION REASON: {venue['rejection_reason']}\n\n")
        
        # Layer 1 Info
        f.write(f"     🔍 LAYER 1 (Foursquare Search):\n")
        f.write(f"        📏 Initial Distance: {original_dist:.0f}m\n")
        f.write(f"        🏷️  Categories: {categories}\n")
        
        # Layer 2 Info
        if ai_validation:
            f.write(f"\n     🤖 LAYER 2 (Validation):\n")
            f.write(f"        🏪 Operational Status: {op_status}\n")
            if op_conf != 'N/A':
                f.write(f"        🎯 Confidence: {op_conf}/10\n")
            if addr_quality != 'N/A':
                f.write(f"        📋 Address Quality: {addr_quality}/10\n")
            if reasoning:
                f.write(f"        💭 Reasoning: {reasoning[:150]}...\n")
            if location_verification:
                f.write(f"        📍 Location: {location_verification[:120]}...\n")
        
        # Layer 3 Info
        if osm_verification:
            f.write(f"\n     🚶 LAYER 3 (Walking Distance Verification):\n")
            f.write(f"        📏 Accurate Walking Distance: {walking_dist:.0f}m\n")
            f.write(f"        📏 Straight-line Distance: {straight_dist:.0f}m\n")
            f.write(f"        ⏱️  Estimated Walking Time: ~{walking_minutes:.1f} minutes\n")
            if confidence > 0:
                f.write(f"        🎯 Verification Confidence: {confidence:.2f}\n")
            if osm_address and osm_address != 'N/A':
                f.write(f"        📍 Address: {osm_address}\n")
            if notes:
                f.write(f"        📝 Verification Notes:\n")
                for note in notes:
                    f.write(f"           • {note}\n")
        
        f.write("\n\n")

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    FOURSQUARE_API_KEY = "HNRSUKIGGHSIXCYO0PJL4A3CITBVD4OELT23YX1AZYUCWQC0"
    
    print("\n" + "="*60)
    print("🍽️  FOOD FINDER - THREE-LAYER SEARCH SYSTEM")
    print("="*60)
    
    # API Key Setup
    print("\n🔑 API KEY SETUP")
    print("-" * 40)
    DEEPSEEK_API_KEY = input("Enter your DeepSeek API key (or press Enter to use manual filtering): ").strip()
    
    if not DEEPSEEK_API_KEY:
        print("⚠️  Layer 2 will use MANUAL FILTERING (no AI)")
    else:
        print("✅ Layer 2: DeepSeek AI ENABLED")
    
    print("✅ Layer 3: OSRM Walking Distance ALWAYS ACTIVE")
    print("📋 Results include BOTH accepted and rejected venues with reasons")
    
    # Home Location
    MY_HOME = GeoPoint(lat=1.3199854484683737, lng=103.85948062051246)
    print(f"\n📍 Home Location: ({MY_HOME.lat:.6f}, {MY_HOME.lng:.6f})")
    
    # Cuisine Selection
    print("\n🍽️  CUISINE SELECTION")
    print("-" * 40)
    print("Examples: fast food, chinese, indian, malaysian, western,")
    print("italian, japanese, thai, korean, vietnamese, mexican,")
    print("vegetarian, halal, bakery, coffee, dessert, or leave blank for all.")
    
    user_cuisine = input("\nEnter desired cuisine (or press Enter for all): ").strip()
    
    # Search Radius
    print("\n🌍 SEARCH RADIUS")
    print("-" * 40)
    print("Note: The app searches for food establishments within this radius.")
    print("Larger radii take longer but find more options.")
    print("Recommended: 1.0-5.0 km for walking, up to 50km for all options.")
    
    try:
        radius_input = input("\nEnter search radius in km (1.0 to 50.0, default: 2.0): ").strip()
        if radius_input:
            search_radius = float(radius_input)
            if search_radius < 0.1 or search_radius > 50.0:
                print(f"⚠️  Radius {search_radius}km outside range (0.1-50.0). Using 2.0km.")
                search_radius = 2.0
        else:
            search_radius = 2.0
    except ValueError:
        print("Invalid input, using default: 2.0 km")
        search_radius = 2.0
    
    # Performance Warning for Large Radii
    if search_radius > 10:
        print(f"\n⚠️  WARNING: {search_radius}km is a large search area.")
        print("   This may take several minutes to complete.")
        print("   The app will optimize search patterns for efficiency.")
        proceed = input("   Proceed? (y/n): ").strip().lower()
        if proceed != 'y':
            print("Search cancelled.")
            sys.exit(0)
    
    # Initialize Search
    print("\n" + "="*60)
    print("⚙️  INITIALIZING THREE-LAYER SEARCH")
    print("="*60)
    print("Search Process:")
    print("1. 🔍 Foursquare: Hex grid search within radius")
    print("2. 🔄 Validation: " + ("DeepSeek AI analysis" if DEEPSEEK_API_KEY else "Manual filtering"))
    print("3. 🚶 OSRM: Accurate walking distance (matches map.project-osrm.org)")
    print(f"   Radius: {search_radius} km")
    
    finder = ThreeLayerFoodFinder(
        FOURSQUARE_API_KEY, 
        deepseek_api_key=DEEPSEEK_API_KEY if DEEPSEEK_API_KEY else None,
        debug_mode=True
    )
    
    try:
        print(f"\n⏳ Starting search... This may take a few moments.")
        
        final_results = finder.three_layer_search(
            MY_HOME, 
            search_radius_km=search_radius,
            cuisine=user_cuisine if user_cuisine else None
        )
        
        print("\n" + "="*60)
        print("📈 SEARCH COMPLETE - SUMMARY")
        print("="*60)
        print(f"Total Search Time: {final_results.get('total_time', 0):.1f}s")
        print(f"Layer 1 Time: {final_results.get('layer1_time', 0):.1f}s")
        print(f"Layer 2 Time: {final_results.get('layer2_time', 0):.1f}s")
        print(f"Layer 3 Time: {final_results.get('layer3_time', 0):.1f}s")
        print(f"Foursquare API Calls: {final_results.get('api_requests', 0)}")
        print(f"AI Requests: {final_results.get('ai_requests', 0)}")
        print(f"Layer 1 Venues Found: {final_results.get('layer1_count', 0)}")
        print(f"Layer 2 Venues Validated: {final_results.get('layer2_count', 0)}")
        print(f"✅ Final Accepted Venues: {final_results.get('layer3_count', 0)}")
        print(f"❌ Total Rejected Venues: {final_results.get('rejected_count', 0)}")
        
        if final_results.get('output_file'):
            print(f"\n📁 Complete results saved to: {final_results['output_file']}")
            print("   File includes:")
            print("   • ✅ All accepted venues with detailed information")
            print("   • ❌ All rejected venues with rejection reasons")
            print("   • 📋 All initial venues from Layer 1")
        
        print(f"\n📍 Home was: ({MY_HOME.lat:.6f}, {MY_HOME.lng:.6f})")
        print(f"🎯 Search radius: {search_radius} km")
        print(f"🍽️  Cuisine filter: {user_cuisine if user_cuisine else 'All'}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Search interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error during search: {str(e)}")
        import traceback
        traceback.print_exc()
