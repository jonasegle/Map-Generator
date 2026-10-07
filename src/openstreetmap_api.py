import requests
from requests.adapters import HTTPAdapter
from pyproj import Transformer
import re
from osm_download import (
    ENDPOINT, FEATURES, CACHE_DIR, selections, build_query, cached_query,
    validate_payload, merge_elements, feature_elements, post_overpass,
)

def extract_first_float_from_string(s):
    match = re.search(r'-?\d+(\.\d+)?', s)
    if match:
        return float(match.group(0))
    return None

def construct_polygon_boundary(boundaries, tol=0.01):
    """
    Order and stitch boundary pieces into a single polygon ring (list of (lat, lon) tuples).
    Strategy:
      1) normalize input pieces (remove degenerate segments)
      2) try Shapely: build MultiLineString -> unary_union -> linemerge -> polygonize -> pick largest polygon
      3) fallback: tolerant greedy stitching with snapping (rounding) and reversing pieces as needed
    tol: tolerance for snapping endpoints (in coordinate units; for lat/lon use ~1e-6 degrees ~0.11m)
    Returns an ordered list of vertices (lat, lon) without duplicate closing point. Returns [] if nothing sensible.
    """
    if not boundaries:
        return []

    # normalize: ensure each piece is list of tuples and has >=2 distinct points
    pieces = []
    for seg in boundaries:
        if not seg:
            continue
        pts = [tuple(p) for p in seg]
        # remove consecutive duplicates
        clean = [pts[0]]
        for p in pts[1:]:
            if p != clean[-1]:
                clean.append(p)
        if len(clean) >= 2:
            pieces.append(clean)
    if not pieces:
        return []

    # Try shapely pipeline if available (most robust)
    try:
        from shapely.geometry import LineString, MultiLineString
        from shapely.ops import linemerge, unary_union, polygonize
        # shapely expects (x,y) -> (lon,lat)
        mls = MultiLineString([[(lon, lat) for lat, lon in seg] for seg in pieces])
        merged = linemerge(unary_union(mls))
        polys = list(polygonize(merged))
        if polys:
            # choose largest polygon (in case of multiple rings)
            poly = max(polys, key=lambda p: p.area)
            # exterior coords are (x,y) -> (lon,lat); drop duplicate closing point
            coords = [(y, x) for x, y in poly.exterior.coords[:-1]]
            return coords
    except Exception:
        # shapely not available or failed -> fallback to greedy stitching
        print("Shapely not available or failed, falling back to greedy stitching for polygon construction.")

    # Fallback: greedy tolerant stitching
    import math
    # snapping via rounding based on tol
    if tol <= 0:
        ndigits = 9
    else:
        ndigits = max(0, -int(math.floor(math.log10(tol))))
    def snap(pt):
        return (round(pt[0], ndigits), round(pt[1], ndigits))

    # build list of pieces (mutable)
    remaining = [list(p) for p in pieces]

    # helper to try to pop a piece that starts or ends at point p (snapped)
    def find_and_pop(p_snap):
        for i, seg in enumerate(remaining):
            if snap(seg[0]) == p_snap:
                return remaining.pop(i), False  # already oriented
            if snap(seg[-1]) == p_snap:
                return remaining.pop(i), True   # need reverse
        return None, None

    # build all loops produced by greedy chaining; then pick the longest
    loops = []
    while remaining:
        seg = remaining.pop(0)
        # start a new chain
        chain = list(seg)
        # extend forwards
        while True:
            end_snap = snap(chain[-1])
            next_seg, rev = find_and_pop(end_snap)
            if not next_seg:
                break
            if rev:
                next_seg.reverse()
            # avoid duplicating the connecting point
            chain.extend(next_seg[1:])
        # extend backwards
        while True:
            start_snap = snap(chain[0])
            prev_seg, rev = find_and_pop(start_snap)
            if not prev_seg:
                break
            if rev:
                prev_seg.reverse()
            chain = prev_seg[:-1] + chain

        # if chain is nearly closed (end == start within tol) drop last duplicate
        if snap(chain[0]) == snap(chain[-1]):
            chain = chain[:-1]

        loops.append(chain)

    if not loops:
        return []

    # choose the longest loop (by number of vertices)
    best = max(loops, key=lambda x: len(x))

    # final: if not closed, try to close by appending start (only if within tol distance)
    def close_distance(a, b):
        # Euclidean in degrees; if you need meters, project first
        return math.hypot(a[0]-b[0], a[1]-b[1])

    if best and close_distance(best[0], best[-1]) <= tol:
        best = best[:-1] if snap(best[0]) == snap(best[-1]) else best
    else:
        # if not closed but start and end are far, attempt simple closure by appending start
        if close_distance(best[0], best[-1]) <= tol * 10:
            best.append(best[0])

    # remove trivial duplicates (consecutive identical points)
    cleaned = [best[0]]
    for p in best[1:]:
        if p != cleaned[-1]:
            cleaned.append(p)
    # ensure not returning a 2-point "polygon"
    if len(cleaned) < 3:
        return []
    # if last equals first, drop last (caller likely wants no duplicated closing point)
    if snap(cleaned[0]) == snap(cleaned[-1]):
        cleaned = cleaned[:-1]
    return cleaned

def getName(tags, preferred_language='de'):
    """
    Extracts the name of an OSM element from its tags, preferring a specific language if available.
    """
    name = tags.get(f'name:{preferred_language}', None)
    if not name:
        name = tags.get('name', None)
    return name

class OpenStreetMapAPI():
    def __init__(self, target_epsg="32633"):
        self.transformer_geo_to_proj = Transformer.from_crs("EPSG:4326", target_epsg, always_xy=True)
        # Create a session with retry/backoff and a polite User-Agent for Overpass
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MapGenerator/1.0 (contact: jonas25.egle@gmail.com)"})

        adapter = HTTPAdapter(max_retries=0)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.cache_dir = CACHE_DIR

    def _post_overpass(self, query, overpass_url=ENDPOINT, timeout=(10, 60), max_attempts=3):
        return post_overpass(self.session, query, endpoint=overpass_url,
                             timeout=timeout, max_attempts=max_attempts)

    def fetch_map_features(self, bounds, config, force_refresh=False):
        chosen = selections(config)
        if not chosen:
            print('[Overpass] No OSM features selected; skipping download.')
            return {feature: [] for feature in FEATURES}
        print('[Overpass] Selected features: ' + ', '.join(chosen))
        query = build_query(bounds, chosen)
        data = cached_query(query, lambda: self._post_overpass(query).json(),
                            enabled=config.get('osm_cache_enabled', True),
                            force_refresh=force_refresh, cache_dir=self.cache_dir)
        elements = merge_elements(data['elements'])
        result = {}
        for feature in FEATURES:
            selected = {'elements': feature_elements(elements, feature, chosen)}
            geographic = getattr(self, '_parse_' + feature)(selected)
            result[feature] = getattr(self, '_project_' + feature)(geographic)
        return result

    def fetch_osm_data(self, types, key, values, bounds, output="geom"):
        """
        Fetches data of types with given key and list of values using Overpass API
        """
        # Overpass API endpoint
        overpass_url = "https://overpass-api.de/api/interpreter"

        # Query to get nodes with specified key and values
        if not values:
            return {"elements": []}
        values_str = "|".join(values)

        min_lat, min_lon, max_lat, max_lon = bounds

        conditions = (
            f'["{key}"~"^({values_str})$"]'
            f'({min_lat},{min_lon},{max_lat},{max_lon})'
        )

        query_body = ""
        for t in types:
            query_body += t + conditions + ";\n"

        overpass_query = f"""
        [out:json][timeout:45];
        (
        {query_body}
        );
        out body {output};
        """

        response = self._post_overpass(overpass_query, overpass_url=overpass_url, timeout=(10, 60))
        data = validate_payload(response.json())
        return data

    def fetch_mountain_peaks_in_geographic_coordinates(self, bounds):
        """
        Fetches mountain peaks within a bounding box using Overpass API

        :param bounds: (min_lat, min_lon, max_lat, max_lon)
        """
        data = self.fetch_osm_data(["node"], "natural", ["peak"], bounds)
        return self._parse_peaks(data)

    def _parse_peaks(self, data):

        # Extract peak information
        peaks = []
        for element in data['elements']:
            tags = element.get('tags', {})
            ele_str = tags.get('ele')
            ele = extract_first_float_from_string(ele_str) if ele_str else None
            prom_str = tags.get('prominence')
            prom = extract_first_float_from_string(prom_str) if prom_str else None
            peak = {
                'name': getName(tags),
                'type': 'mountain_peak',
                'element_type': "node",
                'elevation': ele,
                'prominence': prom,
                'latitude': element.get('lat'),
                'longitude': element.get('lon')
            }
            peaks.append(peak)

        return peaks

    def fetch_mountain_peaks_in_projected_coordinates(self, bounds):
        """
        Fetches mountain peaks within a bounding box and transforms to projected coordinates

        :param bounds: (min_lat, min_lon, max_lat, max_lon)
        """
        mountain_peaks_geographic_coordinates = self.fetch_mountain_peaks_in_geographic_coordinates(bounds)
        return self._project_peaks(mountain_peaks_geographic_coordinates)

    def _project_peaks(self, mountain_peaks_geographic_coordinates):

        return [{
            "name": peak["name"],
            "type": peak["type"],
            "element_type": peak["element_type"],
            "elevation": peak["elevation"],
            "prominence": peak["prominence"],
            "easting": self.transformer_geo_to_proj.transform(float(peak["longitude"]), float(peak["latitude"]))[0],
            "northing": self.transformer_geo_to_proj.transform(float(peak["longitude"]), float(peak["latitude"]))[1]
        } for peak in mountain_peaks_geographic_coordinates]

    def fetch_mountain_huts_in_geographic_coordinates(self, bounds):
        """
        Fetch tourism=alpine_hut / tourism=hut / tourism=refuge (nodes/ways/relations) within bbox.
        Returns list of dicts with: name, type, elevation, latitude, longitude
        """

        data = self.fetch_osm_data(
            ["node", "way", "relation"],
            "tourism", ["alpine_hut", "hut", "refuge"],
            bounds, output="center"
        )
        return self._parse_huts(data)

    def _parse_huts(self, data):

        huts = []
        for element in data.get('elements', []):
            tags = element.get('tags', {})
            ele_str = tags.get('ele')
            ele = extract_first_float_from_string(ele_str) if ele_str else None
            # determine representative coordinates: nodes have lat/lon, others provide center when using "out center"
            if element.get('type') == 'node':
                lat = element.get('lat')
                lon = element.get('lon')
            else:
                center = element.get('center', {})
                lat = center.get('lat')
                lon = center.get('lon')
            if lat is None or lon is None:
                continue
            hut = {
                'name': getName(tags),
                'type': 'mountain_hut',
                'element_type': "node",
                'elevation': ele,
                'latitude': lat,
                'longitude': lon
            }
            huts.append(hut)
        return huts

    def fetch_mountain_huts_in_projected_coordinates(self, bounds):
        huts_geo = self.fetch_mountain_huts_in_geographic_coordinates(bounds)
        return self._project_huts(huts_geo)

    def _project_huts(self, huts_geo):
        projected = []
        for h in huts_geo:
            if h.get('latitude') is None or h.get('longitude') is None:
                continue
            x, y = self.transformer_geo_to_proj.transform(float(h['longitude']), float(h['latitude']))
            projected.append({
                'name': h['name'],
                'type': h['type'],
                'element_type': h['element_type'],
                'elevation': h['elevation'],
                'easting': x,
                'northing': y
            })
        return projected

    def fetch_water_in_geographic_coordinates(self, bounds, lake=True, reservoir=True, river=True, canal=True, lock=True):
        """
        Fetches mountain peaks within a bounding box using Overpass API
        """

        # Parse the response
        data = self.fetch_osm_data(
            ["way", "relation"],
            "natural",
            ["water"],
            bounds
        )
        values = [name for name, enabled in dict(lake=lake, reservoir=reservoir, river=river, canal=canal, lock=lock).items() if enabled]
        selected = feature_elements(data['elements'], 'water', {'water': ('water', values)})
        return self._parse_water({'elements': selected})

    def _parse_water(self, data):

        water_areas = []
        for element in data['elements']:
            tags = element.get('tags', {})
            if 'geometry' in element and len(element['geometry']) >= 3:
                coords = [(pt['lat'], pt['lon']) for pt in element['geometry']]
                ele_str = tags.get('ele')
                ele = extract_first_float_from_string(ele_str) if ele_str else None
                water_area = {
                    'name': getName(tags),
                    'type': 'water',
                    'element_type': "area",
                    'water': tags.get('water', None),
                    'elevation': ele,
                    'coords': coords
                }
                water_areas.append(water_area)
            if tags.get('type', None) == "multipolygon":
                outers = []
                inners = []
                for member in element.get('members', []):
                    if member.get('type') == 'way' and member.get('role') == 'outer' and len(member.get('geometry', [])) >= 2:
                        outers.append([(pt['lat'], pt['lon']) for pt in member.get('geometry', [])])
                    elif member.get('type') == 'way' and member.get('role') == 'inner' and len(member.get('geometry', [])) >= 3:
                        inners.append([(pt['lat'], pt['lon']) for pt in member.get('geometry', [])])
                if not outers:
                    continue
                coords = construct_polygon_boundary(outers)
                if len(coords) < 3:
                    continue
                ele_str = tags.get('ele')
                ele = extract_first_float_from_string(ele_str) if ele_str else None
                water_area = {
                    'name': getName(tags),
                    'type': 'water',
                    'element_type': "area",
                    'water': tags.get('water', None),
                    'elevation': ele,
                    'coords': coords,
                    'inners': inners,
                }
                water_areas.append(water_area)
        return water_areas

    def fetch_water_in_projected_coordinates(self, bounds, lake=True, reservoir=True, river=True, canal=True, lock=True):
        water_areas_geographic_coordinates = self.fetch_water_in_geographic_coordinates(bounds, lake=lake, reservoir=reservoir, river=river, canal=canal, lock=lock)
        return self._project_water(water_areas_geographic_coordinates)

    def _project_water(self, water_areas_geographic_coordinates):

        return [{
            "name": water_area["name"],
            "type": water_area["type"],
            "element_type": water_area["element_type"],
            "water": water_area["water"],
            "elevation": water_area["elevation"],
            "coords": [self.transformer_geo_to_proj.transform(lon, lat) for lat, lon in water_area["coords"]],
            "inners": [[self.transformer_geo_to_proj.transform(lon, lat) for lat, lon in inner] for inner in water_area.get("inners", [])]
        } for water_area in water_areas_geographic_coordinates]



    def fetch_waterways_in_geographic_coordinates(self, bounds, river=True, stream=False, canal=False, ditch=False, drain=False):
        """
        Fetches mountain peaks within a bounding box using Overpass API
        """
        min_lat, min_lon, max_lat, max_lon = bounds
        # Overpass API endpoint
        overpass_url = "https://overpass-api.de/api/interpreter"

        waterway_types = {
            "river": river,
            "canal": canal,
            "stream": stream,
            "ditch": ditch,
            "drain": drain,
        }
        values = "|".join(k for k, v in waterway_types.items() if v)

        if not values:
            print("No waterway types selected, returning empty list.")
            return []

        # Query to get natural=peak nodes within the bounding box
        overpass_query = f"""
        [out:json][timeout:45];
        (
            way["waterway"~"^({values})$"]({min_lat},{min_lon},{max_lat},{max_lon});
        );
        out geom;
        """

        print("Sending Overpass query for waterways...")
        # Send request to Overpass API
        response = self._post_overpass(overpass_query, overpass_url=overpass_url, timeout=(10, 60))

        # Parse the response
        data = validate_payload(response.json())
        return self._parse_waterways(data)

    def _parse_waterways(self, data):

        waterways = []
        for element in data['elements']:
            tags = element.get('tags', {})
            if 'geometry' in element:
                coords = [(pt['lat'], pt['lon']) for pt in element['geometry']]
                waterway = {
                    'name': getName(tags),
                    'type': 'waterway',
                    'element_type': "way",
                    'waterway': tags.get('waterway', tags.get('water', None)),
                    'coords': coords,
                    'tunnel': tags.get('tunnel', None),
                }
                waterways.append(waterway)
        return waterways

    def fetch_waterways_in_projected_coordinates(self, bounds, river=True, stream=False, canal=False, ditch=False, drain=False):
        waterways_geographic_coordinates = self.fetch_waterways_in_geographic_coordinates(bounds, river=river, canal=canal, stream=stream, ditch=ditch, drain=drain)
        return self._project_waterways(waterways_geographic_coordinates)

    def _project_waterways(self, waterways_geographic_coordinates):

        return [{
            "name": waterway["name"],
            "type": waterway["type"],
            "element_type": waterway["element_type"],
            "waterway": waterway["waterway"],
            "coords": [self.transformer_geo_to_proj.transform(lon, lat) for lat, lon in waterway["coords"]],
            "tunnel": waterway.get("tunnel", None),
        } for waterway in waterways_geographic_coordinates]



    def fetch_streets_in_geographic_coordinates(self, bounds, motorway=True, trunk=True, primary=True, secondary=True, tertiary=False, residential=False, service=False, path=True, footway=True, track=True):
        """
        Fetches streets (ways with a highway tag) within a bounding box using Overpass API
        """
        min_lat, min_lon, max_lat, max_lon = bounds
        overpass_url = "https://overpass-api.de/api/interpreter"

        highway_types = {
            "motorway": motorway,
            "trunk": trunk,
            "primary": primary,
            "secondary": secondary,
            "tertiary": tertiary,
            "residential": residential,
            "service": service,
            "path": path,
            "track": track,
            "footway": footway,
        }
        values = "|".join(k for k, v in highway_types.items() if v)

        if not values:
            print("No street types selected, returning empty list.")
            return []

        # Query for common highway types (matches any way with a highway tag)
        overpass_query = f"""
        [out:json][timeout:45];
        (
            way["highway"~"^({values})"]({min_lat},{min_lon},{max_lat},{max_lon});
        );
        out geom;
        """

        print("Sending Overpass query for streets...")
        response = self._post_overpass(overpass_query, overpass_url=overpass_url, timeout=(10, 60))
        data = validate_payload(response.json())
        return self._parse_streets(data)

    def _parse_streets(self, data):
        streets = []

        for element in data.get('elements', []):
            tags = element.get('tags', {})
            # geometry present for ways (and for relation members when out geom used)
            if 'geometry' in element:
                coords = [(pt['lat'], pt['lon']) for pt in element['geometry']]
                street = {
                    'name': getName(tags),
                    'type': 'street',
                    'element_type': "way",
                    'highway': tags.get('highway', None),
                    'oneway': tags.get('oneway', None),
                    'tunnel': tags.get('tunnel', None),
                    'sac_scale': tags.get('sac_scale', None),
                    'coords': coords
                }
                streets.append(street)
        return streets

    def fetch_streets_in_projected_coordinates(self, bounds, motorway=True, trunk=True, primary=True, secondary=True, tertiary=False, residential=False, service=False, path=False, footway=False, track=False):
        streets_geographic_coordinates = self.fetch_streets_in_geographic_coordinates(bounds, motorway=motorway, trunk=trunk, primary=primary, secondary=secondary, tertiary=tertiary, residential=residential, service=service, path=path, footway=footway, track=track)
        return self._project_streets(streets_geographic_coordinates)

    def _project_streets(self, streets_geographic_coordinates):

        return [{
            'name': s['name'],
            'type': s['type'],
            'element_type': s.get('element_type'),
            'highway': s.get('highway'),
            'oneway': s.get('oneway'),
            'tunnel': s.get('tunnel'),
            'sac_scale': s.get('sac_scale'),
            'coords': [self.transformer_geo_to_proj.transform(lon, lat) for lat, lon in s['coords']]
        } for s in streets_geographic_coordinates]



    def fetch_railways_in_geographic_coordinates(self, bounds, rail=True, light_rail=True, narrow_gauge=True):
        """
        Docstring für fetch_railways_in_geographic_coordinates

        :param self: Beschreibung
        :param bounds: Beschreibung
        """

        railway_types = {
            "rail": rail,
            "light_rail": light_rail,
            "narrow_gauge": narrow_gauge,
        }
        values = [k for k, v in railway_types.items() if v]

        data = self.fetch_osm_data(["way"], "railway", values, bounds)
        return self._parse_railways(data)

    def _parse_railways(self, data):

        railways = []
        for element in data.get('elements', []):
            tags = element.get('tags', {})
            if 'geometry' in element:
                coords = [(pt['lat'], pt['lon']) for pt in element['geometry']]
                railway = {
                    'name': getName(tags),
                    'type': 'railway',
                    'element_type': "way",
                    'railway': tags.get('railway', None),
                    'coords': coords
                }
                railways.append(railway)
        return railways

    def fetch_railways_in_projected_coordinates(self, bounds, rail=True, light_rail=True, narrow_gauge=True):
        railways_geographic_coordinates = self.fetch_railways_in_geographic_coordinates(bounds, rail=rail, light_rail=light_rail, narrow_gauge=narrow_gauge)
        return self._project_railways(railways_geographic_coordinates)

    def _project_railways(self, railways_geographic_coordinates):

        return [{
            "name": railway["name"],
            "type": railway["type"],
            "element_type": railway["element_type"],
            "railway": railway["railway"],
            "coords": [self.transformer_geo_to_proj.transform(lon, lat) for lat, lon in railway["coords"]],
        } for railway in railways_geographic_coordinates]



    def fetch_settlements_in_geographic_coordinates(self, bounds, city=True, town=True, suburb=True, village=True, neighbourhood=True, hamlet=False, isolated_dwelling=False):
        """
        Fetches suburb nodes (place=suburb) within a bounding box using Overpass API
        Returns a list of dicts with keys: name, admin_level (if present), latitude, longitude
        """
        min_lat, min_lon, max_lat, max_lon = bounds
        overpass_url = "https://overpass-api.de/api/interpreter"

        settlement_types = {
            "city": city,
            "town": town,
            "suburb": suburb,
            "village": village,
            "neighbourhood": neighbourhood,
            "hamlet": hamlet,
            "isolated_dwelling": isolated_dwelling,
        }
        values = "|".join(k for k, v in settlement_types.items() if v)

        if not values:
            print("No settlement types selected, returning empty list.")
            return []

        overpass_query = f"""
        [out:json][timeout:45];
        (
            node["place"~"^({values})"]({min_lat},{min_lon},{max_lat},{max_lon});
        );
        out body;
        """

        print("Sending Overpass query for settlements...")
        response = self._post_overpass(overpass_query, overpass_url=overpass_url, timeout=(10, 60))
        data = validate_payload(response.json())
        return self._parse_settlements(data)

    def _parse_settlements(self, data):
        suburbs = []

        for element in data.get('elements', []):
            # Only consider node elements
            if element.get('type') != 'node':
                continue
            tags = element.get('tags', {})
            suburb = {
                'name': getName(tags),
                'type': 'settlement',
                'element_type': "node",
                'place': tags.get('place', None),
                'latitude': element.get('lat'),
                'longitude': element.get('lon')
            }
            suburbs.append(suburb)

        return suburbs

    def fetch_settlements_in_projected_coordinates(self, bounds, city=True, town=True, suburb=True, village=True, neighbourhood=True, hamlet=False, isolated_dwelling=False):
        """
        Returns settlement nodes transformed to projected coordinates (easting, northing) using the instance transformer.
        """
        suburbs_geo = self.fetch_settlements_in_geographic_coordinates(bounds, city=city, town=town, suburb=suburb, village=village, neighbourhood=neighbourhood, hamlet=hamlet, isolated_dwelling=isolated_dwelling)
        return self._project_settlements(suburbs_geo)

    def _project_settlements(self, suburbs_geo):
        return [{
            'name': s['name'],
            'type': s['type'],
            'element_type': s.get('element_type'),
            'place': s.get('place'),
            'easting': self.transformer_geo_to_proj.transform(float(s['longitude']), float(s['latitude']))[0] if s.get('longitude') is not None and s.get('latitude') is not None else None,
            'northing': self.transformer_geo_to_proj.transform(float(s['longitude']), float(s['latitude']))[1] if s.get('longitude') is not None and s.get('latitude') is not None else None
        } for s in suburbs_geo]



if __name__ == "__main__":
    # Example usage
    osm_api = OpenStreetMapAPI(target_epsg="EPSG:25832")
    bounds = (46.0, 7.0, 46.5, 7.5)  # Example bounding box
    peaks = osm_api.fetch_osm_data(["node"], "natural", ["peak"], bounds)

