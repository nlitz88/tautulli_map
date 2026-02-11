import requests
import folium
from folium.plugins import MarkerCluster, HeatMap
import json
import time
import os
import argparse
from urllib.parse import urljoin
from dotenv import load_dotenv
from tqdm import tqdm

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
    """Fetches history from Tautulli. length=0 means all records via pagination."""
    print("Connecting to Tautulli...")
    base_url = urljoin(TAUTULLI_URL.rstrip('/') + '/', 'api/v2')

    all_records = []
    start = 0
    batch_size = 1000 if length == 0 else min(length, 1000)  # API max is 1000

    # Progress bar for API requests - use total=None when fetching all records
    total_records = length if length > 0 else None
    pbar = tqdm(desc="Fetching history records", total=total_records, unit=" records")
    total_discovered = False  # Track if we've discovered the total from API

    while True:
        params = {
            'apikey': TAUTULLI_API_KEY,
            'cmd': 'get_history',
            'start': start,
            'length': batch_size
        }

        try:
            url = f"{base_url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
            pbar.write(f"Requesting batch starting at {start}: {url}")
            r = requests.get(url)
            pbar.write(f"Response status: {r.status_code}")
            if r.status_code != 200:
                pbar.write(f"Response text: {r.text}")
                break
            r.raise_for_status()
            data = r.json()

            if 'response' in data and 'data' in data['response']:
                response_data = data['response']['data']
                if 'data' in response_data:
                    records = response_data['data']
                    pbar.write(f"Retrieved {len(records)} records in this batch")

                    # Try to get total count from API response if we haven't discovered it yet
                    if not total_discovered and length == 0:
                        # Check common total count field names
                        possible_total_keys = ['total_count', 'count', 'total', 'recordsTotal', 'totalRecords']
                        for key in possible_total_keys:
                            if key in response_data and isinstance(response_data[key], int):
                                total_from_api = response_data[key]
                                if total_from_api > 0:
                                    pbar.total = total_from_api
                                    pbar.refresh()  # Update the display
                                    total_discovered = True
                                    pbar.write(f"Total records available: {total_from_api}")
                                    break

                    if not records:
                        break  # No more records

                    all_records.extend(records)
                    pbar.update(len(records))  # Update progress bar

                    if length > 0 and len(all_records) >= length:
                        # If user specified a limit, stop when we reach it
                        all_records = all_records[:length]
                        break

                    start += len(records)

                    # Safety check: if we get less than batch_size, we've reached the end
                    if len(records) < batch_size:
                        break
                else:
                    pbar.write("Unexpected response structure: no 'data' in response.data")
                    pbar.write(f"Response: {data}")
                    break
            else:
                pbar.write("Unexpected response structure: no 'response' or 'data'")
                pbar.write(f"Response: {data}")
                break

        except Exception as e:
            pbar.write(f"Error connecting to Tautulli: {e}")
            break

    pbar.close()  # Close the progress bar
    print(f"Total history records retrieved: {len(all_records)}")
    if all_records:
        print(f"Sample record keys: {list(all_records[0].keys())}")
        print(f"Sample record: {all_records[0]}")
    return all_records

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
                tqdm.write(f"Geolocated new IP: {ip} -> {data['city']}, {data['country']}")
                return (lat, lon)
    except Exception as e:
        tqdm.write(f"Error locating {ip}: {e}")

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

    print("Geolocating IP addresses...")
    pbar_geo = tqdm(total=len(unique_ips), desc="Geolocating IPs", unit=" IPs")
    for i, ip in enumerate(unique_ips):
        loc = get_ip_location(ip, ip_cache)
        if loc:
            # Add the location to the list as many times as it appeared in history
            # This makes the heatmap 'hotter' for frequent locations
            count = ip_counts[ip]
            locations.append({'loc': loc, 'ip': ip, 'count': count})

        pbar_geo.update(1)  # Update progress bar for every IP processed

        # Save cache periodically
        if i % 10 == 0:
            with open(CACHE_FILE, 'w') as f:
                json.dump(ip_cache, f)

    pbar_geo.close()

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
