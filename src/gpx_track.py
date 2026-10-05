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
