🍽️ Singapore Restaurant Finder (Let Him Cook!)


📍 Find Food Near You: Enter any Singapore address or area (like "Orchard Road" or "Chinatown").

🔍 Search by Dish or Cuisine: Look for "chicken rice," "laksa," "Italian," or just browse all nearby restaurants.

🗺️ See It on a Map: Your location and all suggested restaurants are pinned on an interactive OpenStreetMap.

🤝 Interactive List & Map: Click a restaurant in the list to highlight it on the map. Click a pin on the map to jump that restaurant to the top of the list.

🧭 Get Directions Instantly: Hit the "Directions" button for any restaurant, and it opens Google Maps with the route already set from your searched location.

🛠️ Hybrid API Magic: It doesn't rely on just one source. It smartly combines results from:

Google Places API (for mainstream spots and dish-specific searches).

Foursquare Places API v3 (great for finding hawker centres and local coffee shops).

OpenStreetMap (always-on, free fallback for broad coverage).


🧠 How It Works (Behind the Scenes)
You type a location. It gets converted to coordinates using Nominatim (OpenStreetMap's geocoder).

You type a dish or cuisine. The app fires off parallel requests to the APIs you've enabled.

It filters out any places outside your chosen radius, combines the results, and removes duplicates.

Everything is displayed on a Folium/OpenStreetMap map and in a sortable sidebar list.

Clicking "Directions" simply opens a pre-filled Google Maps URL with your start and end points.


⚠️ Honest Limitations (A Reality Check)
This is a proof of concept. Its accuracy is directly tied to the sometimes-messy data from its free sources.

APIs sometimes list coffee shops, food courts, or bakeries as "restaurants." We show what they give us.

Menu Gaps: Just because a place has spaghetti doesn't mean Google or Foursquare's data knows about it. Dish searches are good, but not 100% perfect.

The Paid Stuff: For truly comprehensive, real-time menu data in Singapore, you'd want APIs from Grab or Apify. Those cost real money, which I dont want to spend XD

OpenStreetMap's Strength: It's fantastic for finding places tagged with a specific cuisine type (like "cuisine":"chinese"), which is why it's a crucial part of our hybrid approach.
