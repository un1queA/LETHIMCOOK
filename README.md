

[![Streamlit App])](https://lethimcook-duvafpd6cmjx72g9kejply.streamlit.app)

Ever had that feeling of wanting to eat a certain food or cuisine but just know where to look? Look no further, with LETHIMCOOK it'll cook up as many food establishments as long as a cuisine/food is given to it.
The app makes use of google places api, foursquare api to search for food establishments around the area and provides the location of it and how to go there. It specialises in finding hidden gems like hawker stalls or pop up shops. 

user inputs google places api
user inputs foursquare api 
user inputs cuisine/food
user inputs traveling distance he/she is willing to go
user inputs current location

i want foursquare to search for all food establishments in a given radius. thats it. but i realised that foursquare is at its most accurate when searching for smaller spots like 50m. however i want the app to be able to search for radiuses of up to 10km.  a hierarchical search strategy is the most practical and efficient method. This approach intelligently combines a wide-area scan with targeted, high-resolution searches, making optimal use of your API calls.
 This code uses a hexagonal grid for efficient area coverage, searches in two phases, and carefully handles duplicates. After all food establishments have been found all of it goes to deepseek. deepseek will handle the results based on user input. Upon looking at the user inputs (food/cuisine user wants to eat), deepseek will search with the given output of foursquare and return the food establishment which matches what the user wants. In return, deepseek should return the establishments name, why it was chosen and where is it located at. 


how the foursquare part of the code works:
Layer 1: Foursquare Search
Searches within user-defined radius (e.g., 1km)
Uses hexagonal grid for comprehensive coverage
Returns all food establishments within the radius

Layer 2: DeepSeek AI Validation
Provides detailed validation exactly as you specified:
📍 Address: #01-27 Whampoa Drive Market & Food Centre (91 Whampoa Drive), 320091
📌 Coordinates: 1.323623, 103.853746
🏷️ Categories: Fried Chicken Joint, Halal Restaurant, Malay Restaurant
🏪 Operational Status: YES
🎯 Operational Confidence: 9/10
📋 Address Quality: 10/10

🤖 Reasoning: [detailed explanation]

🗺️ Location Verification: [analysis]

Layer 3: OSM Distance Verification
Checks if the AI-validated venue is actually within the 1km radius
Uses OSM's accurate coordinates for final distance calculation
Compares OSM distance with original Foursquare distance
Only displays venues where OSM confirms they're within the radius
Provides confidence scores for the verification


google places searches for all food establishments in given radius and matches it with given user inputs both cuisine/food & distance. google places then produces the result (might use ai to crosscheck). the results from google places combines with foursquare api as foursquare can find those little stores unlike google places which is more suitiable for restaurants. get the best results possible

cons: might not be accurate, might be outdated as there is not enough data of singapore/no one has collected such data and made it publically accessible/free :( esp for the hawker stalls. accuracy is all based on AI as well nothing to use to crosscheck







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
