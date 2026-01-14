

[![Streamlit App])](https://lethimcook-duvafpd6cmjx72g9kejply.streamlit.app)

📍 Find Food Near You: Enter any Singapore address or area (like "Orchard Road" or "Chinatown").

🔍 Search by Dish or Cuisine: Look for "chicken rice," "laksa," "Italian," or just browse all nearby restaurants.

🗺️ See It on a Map: Your location and all suggested restaurants are pinned on an interactive OpenStreetMap.

🤝 Interactive List & Map: Click a restaurant in the list to highlight it on the map. Click a pin on the map to jump that restaurant to the top of the list.

🧭 Get Directions Instantly: Hit the "Directions" button for any restaurant, and it opens Google Maps with the route already set from your searched location.

🛠️ Hybrid API Magic: It doesn't rely on just one source. It smartly combines results from:

Google Places API (for mainstream spots and dish-specific searches).

Foursquare Places API v3 (great for finding hawker centres and local coffee shops).

OpenStreetMap (always-on, free fallback for broad coverage).


# 🧠 How It Works (Behind the Scenes)
You type a location. It gets converted to coordinates using Nominatim (OpenStreetMap's geocoder).

You type a dish or cuisine. The app fires off parallel requests to the APIs you've enabled.

It filters out any places outside your chosen radius, combines the results, and removes duplicates.

Everything is displayed on a Folium/OpenStreetMap map and in a sortable sidebar list.

Clicking "Directions" simply opens a pre-filled Google Maps URL with your start and end points.


# Limitations
This is a proof of concept. Its accuracy is directly tied to the api data from googleplaces, foursquare and openstreetmap.

All results are taken from the APIs and sometimes they list coffee shops, food courts, or bakeries as "restaurants."

Menu Gaps: Just because a place has spaghetti doesn't mean Google or Foursquare's data knows about it. Dish searches are good, but not 100% perfect.

The Paid Stuff: For truly comprehensive, real-time menu data for a specific country like for example Singapore, getting a specific and local APIs from something like Grab or Apify would let you get more accuarte results. However, since this IS a proof of concept and those cost real money, I am sticking to free alternatives for now XD.

OpenStreetMap's Strength: It's fantastic for finding places tagged with a specific cuisine type (like "cuisine":"chinese"), which is why it's a crucial part of our hybrid approach.

# What you would need
u would need an api from google places and foursquarespaces to run the app at its best potential. It can both be found via these 2 links down below respectively 

# 🔑 HOW TO GET GOOGLE PLACES API KEY (FREE $200/MONTH):
Step 1: Create Google Cloud Account (2 min)

Go to: https://console.cloud.google.com/
Sign in with your Google account
Accept terms and conditions
Add billing information (credit card required, but won't be charged within free tier)

⚠️ Important: You MUST add a credit card, but Google gives you $200 free credit every month. You won't be charged unless you exceed $200/month.

Step 2: Create a Project (1 min)

Click the project dropdown (top bar, says "Select a project")
Click "New Project"
Name it: "Restaurant Finder"
Click "Create"


Step 3: Enable Places API (1 min)

Go to: APIs & Services > Library (left sidebar)
Search for: "Places API"
Click on "Places API"
Click "ENABLE" button


Step 4: Create API Key (1 min)

Go to: APIs & Services > Credentials (left sidebar)
Click "+ CREATE CREDENTIALS" (top bar)
Select "API key"
Copy your API key (looks like: AIzaSyB1x2y3...)


# 🔑 HOW TO GET FOURSQUARE API KEY (100% FREE FOREVER):
Step 1: Sign Up (1 minute)

Go to: https://foursquare.com/developers/signup
Click "Sign up"
Enter your email and create password
No credit card required! ✅


Step 2: Verify Email (30 seconds)

Check your email inbox
Click the verification link
Log back into Foursquare Developers


Step 3: Create Project (1 minute)

Once logged in, click "Create a new project"
Project name: "Restaurant Finder"
Click "Create"


Step 4: Get API Key (30 seconds)

Your project opens automatically
You'll see your API Key displayed
It starts with: fsq... (example: AbC123XyZ...)
Click "Copy" or manually copy it


Step 5: Add to App

Paste your API key into the sidebar: "Foursquare API Key"
Start searching! 🚀
