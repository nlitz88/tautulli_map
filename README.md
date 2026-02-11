# Tautulli Map

A Python script to visualize Plex server access locations from Tautulli data on an interactive map.

## Setup

1. Install dependencies:
   ```bash
   pip install requests folium
   ```

2. Set environment variables:
   ```bash
   export TAUTULLI_URL="http://your-tautulli-server:8181"
   export TAUTULLI_API_KEY="your-api-key-here"
   ```

   Or edit the script directly to set `TAUTULLI_URL` and `TAUTULLI_API_KEY`.

## Usage

Run the script:
```bash
python tautulli_map.py
```

The script will:
- Fetch history from Tautulli
- Geocode IP addresses (with caching)
- Generate an interactive map with heatmap and markers
- Save as `plex_map.html`

Open `plex_map.html` in your browser to view the map.

## Features

- Heatmap showing access frequency
- Clustered markers with play counts and IP info
- IP geocoding with caching to avoid repeated API calls
- Skips private IP addresses

## Troubleshooting

- Ensure Tautulli is running and accessible
- Check your API key in Tautulli Settings > Web Interface > API Key
- Verify the TAUTULLI_URL is correct
