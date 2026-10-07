"""Read GPX track segments and project them into the map's coordinate system."""
import math
import xml.etree.ElementTree as ET

from pyproj import Transformer

DEFAULT_LINE_THICKNESS = 1.5


def validate_line_thickness(value):
    try:
        width = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError('gpx_line_thickness must be a positive, finite number of points.') from exc
    if isinstance(value, bool) or not math.isfinite(width) or width <= 0:
        raise ValueError('gpx_line_thickness must be a positive, finite number of points.')
    return width


def read_gpx_segments(filename):
    """Return separate lists of (longitude, latitude); never connect segments."""
    try:
        root = ET.parse(filename).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f'Cannot read GPX file {filename}: {exc}') from exc
    if root.tag.split('}')[-1] != 'gpx':
        raise ValueError(f'Invalid GPX file {filename}: expected a gpx root element.')
    namespace = root.tag.rsplit('}', 1)[0] + '}' if root.tag.startswith('{') else ''
    segments = []
    for track in root.findall(f'{namespace}trk'):
        for segment in track.findall(f'{namespace}trkseg'):
            points = []
            for point in segment.findall(f'{namespace}trkpt'):
                try:
                    lon, lat = float(point.attrib['lon']), float(point.attrib['lat'])
                    if not math.isfinite(lon) or not math.isfinite(lat) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
                        raise ValueError('coordinates out of range')
                except (KeyError, ValueError) as exc:
                    raise ValueError(f'Invalid track coordinates in GPX file {filename}.') from exc
                points.append((lon, lat))
            if len(points) >= 2 and len(set(points)) >= 2:
                segments.append(points)
    if not segments:
        raise ValueError(f'GPX file {filename} has no drawable track segments (at least two distinct points required).')
    return segments


def project_gpx_segments(segments, target_crs):
    transformer = Transformer.from_crs('EPSG:4326', target_crs, always_xy=True)
    projected = []
    for segment in segments:
        longitudes, latitudes = zip(*segment)
        eastings, northings = transformer.transform(longitudes, latitudes, errcheck=True)
        points = list(zip(eastings, northings))
        if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
            raise ValueError('GPX coordinates could not be projected into the map CRS.')
        projected.append(points)
    return projected


def compute_gpx_center(filename, target_crs=None, prefer_etrs89=False):
    """Return (latitude, longitude) of the projected track bounding-box midpoint."""
    from utm_finder import (
        get_utm_zone_from_lon, is_in_norway_special_zone,
        is_in_svalbard_special_zone, _get_epsg_from_zone,
    )
    segments = read_gpx_segments(filename)
    if target_crs is None or str(target_crs).strip().lower() in ('', 'none'):
        points = [point for segment in segments for point in segment]
        lon = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
        lat = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
        zone = (is_in_svalbard_special_zone(lat, lon)
                or is_in_norway_special_zone(lat, lon)
                or get_utm_zone_from_lon(lon))
        target_crs = _get_epsg_from_zone(zone, 'north' if lat >= 0 else 'south',
                                        prefer_etrs89, lat, lon)
    projected = project_gpx_segments(segments, target_crs)
    points = [point for segment in projected for point in segment]
    x = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
    y = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
    lon, lat = Transformer.from_crs(target_crs, 'EPSG:4326', always_xy=True).transform(x, y, errcheck=True)
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError('GPX center could not be transformed to latitude/longitude.')
    return lat, lon
