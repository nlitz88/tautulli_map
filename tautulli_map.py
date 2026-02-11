import requests
import folium
from folium.plugins import MarkerCluster, HeatMap
import json
import time
import os
import argparse
from urllib.parse import urljoin
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

# ================= CONFIGURATION =================
# Set these environment variables or edit below
TAUTULLI_URL = os.getenv('TAUTULLI_URL', 'http://localhost:8181')  # Your Tautulli URL (e.g., http://192.168.1.5:8181)
TAUTULLI_API_KEY = os.getenv('TAUTULLI_API_KEY', '')  # Your Tautulli API Key (Settings -> Web Interface -> API Key)

# Filename for the output map
OUTPUT_FILE = 'plex_map.html'
# =================================================

CACHE_FILE = 'ip_location_cache.json'

def get_tautulli_history(length=0):
    """Fetches history from Tautulli. length=0 means all records."""
    print("Connecting to Tautulli...")
    base_url = urljoin(TAUTULLI_URL.rstrip('/') + '/', 'api/v2')
    params = {
        'apikey': TAUTULLI_API_KEY,
        'cmd': 'get_history'
    }
    if length > 0:
        params['length'] = length

    try:
        url = f"{base_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
        print(f"Requesting: {url}")
        r = requests.get(url)
        print(f"Response status: {r.status_code}")
        if r.status_code != 200:
            print(f"Response text: {r.text}")
        r.raise_for_status()
        data = r.json()

        if 'response' in data and 'data' in data['response']:
            if 'data' in data['response']['data']:
                records = data['response']['data']['data']
                print(f"Total history records retrieved: {len(records)}")
                if records:
                    print(f"Sample record keys: {list(records[0].keys())}")
                    print(f"Sample record: {records[0]}")
                return records
            else:
                print("Unexpected response structure: no 'data' in response.data")
                print(f"Response: {data}")
        else:
            print("Unexpected response structure: no 'response' or 'data'")
            print(f"Response: {data}")

    except Exception as e:
        print(f"Error connecting to Tautulli: {e}")
        return []

    return []

def get_ip_location(ip, cache):
    """
    Returns (lat, lon) for an IP. 
    Checks cache first, then hits ip-api.com.
    """
    # Skip private IPs immediately
    if ip.startswith(('192.168.', '10.', '127.', '172.16.', '172.17.', '172.18.', '172.19.', '172.2', '172.30.', '172.31.')):
        return None

    if ip in cache:
        return cache[ip]

    # Rate limiting for free API (45 requests per minute)
    time.sleep(1.5) 
    
    try:
        url = f"http://ip-api.com/json/{ip}"
        r = requests.get(url)
        if r.status_code == 200:
            data = r.json()
            if data['status'] == 'success':
                lat = data['lat']
                lon = data['lon']
                cache[ip] = (lat, lon)
                print(f"Geolocated new IP: {ip} -> {data['city']}, {data['country']}")
                return (lat, lon)
    except Exception as e:
        print(f"Error locating {ip}: {e}")

    return None

def main():
    parser = argparse.ArgumentParser(description='Generate map of Plex access locations from Tautulli')
    parser.add_argument('--length', type=int, default=0,
                       help='Number of history records to fetch (0 = all, default: 0)')
    args = parser.parse_args()

    if not TAUTULLI_API_KEY:
        print("ERROR: TAUTULLI_API_KEY environment variable not set.")
        print("Please set it with: export TAUTULLI_API_KEY='your_api_key_here'")
        print("Or edit the script to set TAUTULLI_API_KEY directly.")
        exit(1)

    # 1. Load Cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            ip_cache = json.load(f)
            # Convert lists back to tuples if JSON loaded them as lists
            for k, v in ip_cache.items():
                ip_cache[k] = tuple(v)
    else:
        ip_cache = {}

    # 2. Get History
    history = get_tautulli_history(args.length)
    if not history:
        print("No history found or could not connect.")
        return

    # 3. Extract Unique IPs and Geolocate
    print("Processing IP addresses...")
    # We only care about unique IPs to save API calls, but we store the count for the heatmap
    ip_counts = {} 
    
    for entry in history:
        ip = entry.get('ip_address')
        if ip:
            ip_counts[ip] = ip_counts.get(ip, 0) + 1

    unique_ips = list(ip_counts.keys())
    print(f"Found {len(unique_ips)} unique IP addresses.")

    locations = []
    
    for i, ip in enumerate(unique_ips):
        loc = get_ip_location(ip, ip_cache)
        if loc:
            # Add the location to the list as many times as it appeared in history
            # This makes the heatmap 'hotter' for frequent locations
            count = ip_counts[ip]
            locations.append({'loc': loc, 'ip': ip, 'count': count})
        
        # Save cache periodically
        if i % 10 == 0:
            with open(CACHE_FILE, 'w') as f:
                json.dump(ip_cache, f)

    # Final cache save
    with open(CACHE_FILE, 'w') as f:
        json.dump(ip_cache, f)

    # 4. Create Map
    print("Generating Map...")
    if not locations:
        print("No valid locations found to plot.")
        return

    # Center map on the first location found
    start_coords = locations[0]['loc']
    m = folium.Map(location=start_coords, zoom_start=3, tiles="OpenStreetMap")

    # A. Add Heatmap
    # Heatmap data format: [[lat, lon, weight], ...]
    heat_data = [[item['loc'][0], item['loc'][1], item['count']] for item in locations]
    HeatMap(heat_data, radius=25, blur=15, max_zoom=1).add_to(m)

    # B. Add Markers (Clustered)
    marker_cluster = MarkerCluster().add_to(m)
    
    # We group by location to avoid stacking 1000 markers on the exact same pixel
    grouped_locs = {}
    for item in locations:
        coord = item['loc']
        if coord not in grouped_locs:
            grouped_locs[coord] = {'count': 0, 'ips': set()}
        grouped_locs[coord]['count'] += item['count']
        grouped_locs[coord]['ips'].add(item['ip'])

    for coord, data in grouped_locs.items():
        popup_text = f"<b>Plays:</b> {data['count']}<br><b>IPs:</b> {', '.join(list(data['ips'])[:3])}"
        if len(data['ips']) > 3: 
            popup_text += "..."
            
        folium.Marker(
            location=coord,
            popup=popup_text,
            icon=folium.Icon(color="blue", icon="info-sign"),
        ).add_to(marker_cluster)

    # 5. Save
    m.save(OUTPUT_FILE)
    print(f"\nDone! Open '{OUTPUT_FILE}' in your web browser to view the map.")

if __name__ == "__main__":
    main()
