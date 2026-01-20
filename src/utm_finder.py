"""
UTM Finder Module

This module provides functionality to:
    Automatically determine optimal UTM zone

Author: TreeDimension Project
"""

import os
from typing import Optional


# Configure GDAL for shapefile handling
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

def get_utm_zone_from_lon(lon: float) -> int:
    """Calculate UTM zone number from longitude."""
    return int((lon + 180) / 6) + 1


def is_in_norway_special_zone(lat: float, lon: float) -> Optional[int]:
    """Check if coordinates are in Norway's special UTM zone (56-64N, 3-12E → zone 32)."""
    if 56 <= lat < 64 and 3 <= lon < 12:
        return 32
    return None


def is_in_svalbard_special_zone(lat: float, lon: float) -> Optional[int]:
    """Check if coordinates are in Svalbard's special UTM zones (72-84N)."""
    if 72 <= lat < 84:
        if 0 <= lon < 9:
            return 31
        elif 9 <= lon < 21:
            return 33
        elif 21 <= lon < 33:
            return 35
        elif 33 <= lon < 42:
            return 37
    return None

def _get_epsg_from_zone(
    zone: int,
    hemisphere: str,
    prefer_etrs89: bool,
    lat: float,
    lon: float
) -> int:
    """Convert UTM zone and hemisphere to EPSG code."""
    if hemisphere == 'north':
        # Check for ETRS89 in Europe
        if prefer_etrs89 and _is_in_europe(lat, lon):
            return 25800 + zone  # ETRS89 UTM zones
        else:
            return 32600 + zone  # WGS84 UTM north
    else:
        return 32700 + zone  # WGS84 UTM south


def _is_in_europe(lat: float, lon: float) -> bool:
    """Check if coordinates are in Europe (rough bounds for ETRS89 applicability)."""
    # Rough European bounds
    return (35 <= lat <= 72) and (-10 <= lon <= 40)


