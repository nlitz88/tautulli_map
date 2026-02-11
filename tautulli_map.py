import requests
import folium
from folium.plugins import MarkerCluster, HeatMap
import json
import time
import os
from urllib.parse import urljoin

# ================= CONFIGURATION =================
# Your Tautulli URL (e.g., http://192.168.1.5:8181)
TAUTULLI_URL = 'http://192.168.0.51:8181'

# Your Tautulli API Key (Settings -> Web Interface -> API Key)
TAUTULLI_API_KEY = '1ce97cde2283434c93550d45f322a835'

# Filename for the output map
OUTPUT_FILE = 'plex_map.html'
# =================================================

CACHE_FILE = 'ip_location_cache.json'

def get_tautulli_history():
    """Fetches the entire history from Tautulli."""
    print("Connecting to Tautulli...")
    base_url = urljoin(TAUTULLI_URL, '/api/v2')
    history_data = []
    start = 0
    length = 1000 # Batch size

    while True:
        params = {
            'apikey': TAUTULLI_API_KEY,
            'cmd': 'get_history',
            'start': start,
            'length': length
        }
        
        try:
            r = requests.get(base_url, params=params)
            r.raise_for_status()
            data = r.json()
            
            records = data['response']['data']['data']
            if not records:
                break
                
            history_data.extend(records)
            print(f"Fetched {len(history_data)} records so far...")
            
            if len(records) < length:
                break
                
            start += length
            
        except Exception as e:
            print(f"Error connecting to Tautulli: {e}")
            return []

    print(f"Total history records retrieved: {len(history_data)}")
    return history_data

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
    history = get_tautulli_history()
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
