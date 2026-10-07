"""Combined Overpass queries, validated disk caching, and explicit retries."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import random
import tempfile
import time

import requests

ENDPOINT = 'https://overpass-api.de/api/interpreter'
CACHE_DIR = Path(__file__).resolve().parents[1] / '.cache' / 'osm'
CACHE_VERSION = 1
CACHE_TTL = 7 * 24 * 60 * 60
FEATURES = ('peaks', 'huts', 'settlements', 'streets', 'railways', 'waterways', 'water')
# Defaults match map generation, including its explicit subtype defaults.
SUBTYPES = {
    'settlements': ('place', {'city': True, 'town': True, 'suburb': True, 'village': True,
                            'neighbourhood': True, 'hamlet': False, 'isolated_dwelling': False}),
    'streets': ('highway', {'motorway': True, 'trunk': True, 'primary': True, 'secondary': True,
                          'tertiary': True, 'residential': False, 'service': False,
                          'path': False, 'footway': False, 'track': False}),
    'railways': ('railway', {'rail': True, 'light_rail': True, 'narrow_gauge': True}),
    'waterways': ('waterway', {'river': True, 'stream': True, 'canal': False, 'ditch': False, 'drain': False}),
    'water': ('water', {'lake': True, 'reservoir': True, 'river': True, 'canal': False, 'lock': False}),
}
TOGGLES = {'peaks': 'map_peaks', 'huts': 'map_mountain_huts', 'settlements': 'map_settlements',
           'streets': 'map_streets', 'railways': 'map_railways', 'waterways': 'map_waterways', 'water': 'map_water'}


def selections(config):
    chosen = {}
    for feature in FEATURES:
        if not config.get(TOGGLES[feature], False):
            continue
        if feature == 'peaks':
            chosen[feature] = ('natural', ['peak'])
        elif feature == 'huts':
            chosen[feature] = ('tourism', ['alpine_hut', 'hut', 'refuge'])
        else:
            tag, defaults = SUBTYPES[feature]
            prefix = 'map_waterway_' if feature == 'waterways' else 'map_water_' if feature == 'water' else 'map_'
            values = sorted(value for value, default in defaults.items() if config.get(prefix + value, default))
            if values:
                chosen[feature] = (tag, values)
    return chosen


def build_query(bounds, chosen):
    bbox = ','.join(format(float(value), '.12g') for value in bounds)
    points, geometry = [], []
    for feature in FEATURES:
        if feature not in chosen:
            continue
        tag, values = chosen[feature]
        condition = f'["{tag}"~"^({"|".join(sorted(values))})$"]'
        if feature == 'water':
            for kind in ('way', 'relation'):
                geometry.append(f'{kind}["natural"="water"]{condition}({bbox});')
                if 'lake' in values:
                    geometry.append(f'{kind}["natural"="water"][!"water"]({bbox});')
        else:
            kind = 'nwr' if feature == 'huts' else 'node' if feature in ('peaks', 'settlements') else 'way'
            (points if feature in ('peaks', 'huts', 'settlements') else geometry).append(f'{kind}{condition}({bbox});')
    statements = ['[out:json][timeout:45];']
    if points:
        statements += ['(' + '\n'.join(points) + ')->.points;', '.points out body center;']
    if geometry:
        statements += ['(' + '\n'.join(geometry) + ')->.geometry;', '.geometry out body geom;']
    return '\n'.join(statements)


def validate_payload(data):
    if not isinstance(data, dict) or not isinstance(data.get('elements'), list):
        raise ValueError('Invalid Overpass response: expected an elements list.')
    if data.get('remark'):
        raise ValueError('Overpass returned an error or partial response: ' + str(data['remark'])[:500])
    for element in data['elements']:
        if (not isinstance(element, dict) or element.get('type') not in ('node', 'way', 'relation')
                or type(element.get('id')) is not int or not isinstance(element.get('tags', {}), dict)):
            raise ValueError('Invalid Overpass element.')
        if element['type'] == 'node' and not valid_coordinate(element):
            raise ValueError('Invalid Overpass node coordinates.')
        if 'center' in element and not valid_coordinate(element['center']):
            raise ValueError('Invalid Overpass center coordinates.')
        containers = [element] + element.get('members', []) if isinstance(element.get('members', []), list) else []
        if not containers:
            raise ValueError('Invalid Overpass relation members.')
        for container in containers:
            if not isinstance(container, dict):
                raise ValueError('Invalid Overpass relation member.')
            if 'geometry' in container and (not isinstance(container['geometry'], list)
                    or not all(valid_coordinate(point) for point in container['geometry'])):
                raise ValueError('Invalid Overpass geometry.')
    return data


def valid_coordinate(point):
    if not isinstance(point, dict):
        return False
    try:
        lat, lon = float(point['lat']), float(point['lon'])
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
    except (KeyError, TypeError, ValueError):
        return False


def merge_elements(elements):
    merged = {}
    for element in elements:
        key = element['type'], element['id']
        old = merged.get(key, {})
        tags = {**old.get('tags', {}), **element.get('tags', {})}
        merged[key] = {**old, **element, 'tags': tags}
        if 'members' in old and 'members' in element:
            members = {}
            for member in old['members'] + element['members']:
                member_key = member.get('type'), member.get('ref'), member.get('role')
                members[member_key] = {**members.get(member_key, {}), **member}
            merged[key]['members'] = list(members.values())
    return list(merged.values())


def feature_elements(elements, feature, chosen):
    if feature not in chosen:
        return []
    tag, values = chosen[feature]
    types = ('node', 'way', 'relation') if feature == 'huts' else ('way', 'relation') if feature == 'water' else ('node',) if feature in ('peaks', 'settlements') else ('way',)
    return [element for element in elements if element['type'] in types
            and (element.get('tags', {}).get('natural') == 'water' if feature == 'water' else True)
            and element.get('tags', {}).get(tag, 'lake' if feature == 'water' else None) in values]


def cached_query(query, download, enabled=True, force_refresh=False, cache_dir=CACHE_DIR, endpoint=ENDPOINT):
    key = hashlib.sha256(f'{CACHE_VERSION}\n{endpoint}\n{query}'.encode()).hexdigest()
    cache_path = Path(cache_dir) / (key + '.json')
    if enabled and not force_refresh:
        try:
            entry = json.loads(cache_path.read_text(encoding='utf-8'))
            age = time.time() - entry['fetched_at']
            if entry['version'] == CACHE_VERSION and 0 <= age < CACHE_TTL:
                data = validate_payload(entry['data'])
                print(f'[Overpass cache] Hit ({age / 3600:.1f} hours old).')
                return data
            print('[Overpass cache] Entry expired.')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'[Overpass cache] Ignoring unreadable entry: {exc}')
    print('[Overpass cache] ' + ('Refresh requested.' if force_refresh else 'Miss.' if enabled else 'Disabled.'))
    data = validate_payload(download())
    if enabled:
        temp_path = None
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=cache_path.parent, delete=False) as handle:
                temp_path = Path(handle.name)
                json.dump({'version': CACHE_VERSION, 'fetched_at': time.time(), 'data': data}, handle)
            os.replace(temp_path, cache_path)
        except OSError as exc:
            print(f'[Overpass cache] Could not save downloaded data: {exc}')
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError as exc:
                    print(f'[Overpass cache] Could not remove temporary entry: {exc}')
    return data


def retry_after(value):
    if value is None:
        return None
    try:
        delay = float(value)
        return max(0, delay) if math.isfinite(delay) else None
    except (TypeError, ValueError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def post_overpass(session, query, endpoint=ENDPOINT, max_attempts=3, timeout=(10, 60)):
    started = time.monotonic()
    max_attempts = min(3, max_attempts)
    try:
        for attempt in range(1, max_attempts + 1):
            attempt_start = time.monotonic()
            print(f'[Overpass] Attempt {attempt}/{max_attempts} - POSTing to {endpoint}...')
            try:
                response = session.post(endpoint, data=query, timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                print(f'[Overpass] Request failed after {time.monotonic() - attempt_start:.1f}s: {exc}')
                if attempt == max_attempts:
                    raise
                delay = 2 ** attempt + random.random()
            else:
                print(f'[Overpass] HTTP {response.status_code} after {time.monotonic() - attempt_start:.1f}s.')
                if response.status_code == 200:
                    return response
                excerpt = response.text[:500]
                if response.status_code not in (429, 500, 502, 503, 504) or attempt == max_attempts:
                    raise requests.HTTPError(f'Overpass HTTP {response.status_code}: {excerpt}', response=response)
                delay = retry_after(response.headers.get('Retry-After'))
                if delay is None:
                    delay = 2 ** attempt + random.random()
                if delay > 60:
                    raise requests.HTTPError(f'Overpass HTTP {response.status_code}: retry after {delay:.0f}s; try again later. {excerpt}', response=response)
            print(f'[Overpass] Waiting {delay:.1f}s before retry.')
            time.sleep(delay)
        raise ValueError('max_attempts must be positive.')
    finally:
        print(f'[Overpass] Total request time: {time.monotonic() - started:.1f}s.')
