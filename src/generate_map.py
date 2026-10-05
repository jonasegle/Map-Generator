from functools import reduce
from pyproj import Transformer
import shapefile
import os

import yaml
import argparse

from map_class import Map
from gpx_track import (DEFAULT_LINE_THICKNESS, read_gpx_segments,
                       project_gpx_segments, validate_line_thickness)
from openstreetmap_api import OpenStreetMapAPI

from pyproj import CRS

def generate_map(config):
    # Read the shapefile to get the projected coordinates
    shape = shapefile.Reader(config["input_file"])
    prj_path = os.path.splitext(config["input_file"])[0] + ".prj"
    shapefile_crs = None
    if os.path.exists(prj_path):
        with open(prj_path, 'r') as prj_file:
            prj_wkt = prj_file.read()
        try:
            crs_obj = CRS.from_wkt(prj_wkt)
            auth = crs_obj.to_authority()
            if auth:
                shapefile_crs = f"{auth[0]}:{auth[1]}"  # e.g. "EPSG:21781"
            else:
                shapefile_crs = crs_obj.to_string()
            print(f"Detected shapefile CRS: {shapefile_crs}")
        except Exception as e:
            print(f"Unable to parse .prj file {prj_path}: {e}")
    else:
        print(f"No .prj file found next to shapefile: {prj_path}")
    feature = shape.shapeRecords()[0]
    first = feature.shape.__geo_interface__

    shape_vertices_in_projected_coordinates = []
    for coordinate in first.get("coordinates", [])[0]:
        shape_vertices_in_projected_coordinates.append((coordinate[0], coordinate[1]))

    eastings = list(map(lambda x : float(x[0]), shape_vertices_in_projected_coordinates))
    northings = list(map(lambda x : float(x[1]), shape_vertices_in_projected_coordinates))

    min_easting = reduce(lambda x, y : min(x, y), eastings)
    min_northing = reduce(lambda x, y :  min(x, y), northings)
    max_easting = reduce(lambda x, y :  max(x, y), eastings)
    max_northing = reduce(lambda x, y :  max(x, y), northings)

    # Convert projected coordinates to geographical coordinates (latitude, longitude)
    transformer_proj_to_geo = Transformer.from_crs(shapefile_crs, "EPSG:4326", always_xy=False)
    
    shape_vertices_in_geographical_coordinates = []
    for coordinate in first.get("coordinates", [])[0]:
        shape_vertices_in_geographical_coordinates.append(transformer_proj_to_geo.transform(coordinate[0], coordinate[1]))

    latitudes = list(map(lambda x : float(x[0]), shape_vertices_in_geographical_coordinates))
    longitudes = list(map(lambda x : float(x[1]), shape_vertices_in_geographical_coordinates))

    # Example coordinates for Switzerland
    min_lat = reduce(lambda x, y : min(x, y), latitudes)
    min_lon = reduce(lambda x, y : min(x, y), longitudes)
    max_lat = reduce(lambda x, y : max(x, y), latitudes)
    max_lon = reduce(lambda x, y : max(x, y), longitudes)

    bounds = (min_lat, min_lon, max_lat, max_lon)

    print(f"Bounding box in projected coordinates: ({min_easting}, {min_northing}) to ({max_easting}, {max_northing})")
    print(f"Bounding box in geographical coordinates: ({min_lat}, {min_lon}) to ({max_lat}, {max_lon})")

    gpx_file = config.get('gpx_file', config.get('gpxfile', ''))
    gpx_width = validate_line_thickness(config.get('gpx_line_thickness', DEFAULT_LINE_THICKNESS))
    gps_segments = []
    if gpx_file and str(gpx_file).strip():
        gps_segments = project_gpx_segments(read_gpx_segments(gpx_file), shapefile_crs)

    # request data from OpenStreetMap API
    print("Requesting data from OpenStreetMap API...")

    osm_api = OpenStreetMapAPI(target_epsg=shapefile_crs)

    # Create a Map instance with the given configuration
    map_instance = Map(
            scale=config["scale"],
            bounds=(min_easting, min_northing, max_easting, max_northing),
            bounding_shape=shape_vertices_in_projected_coordinates,
            dpi=config["map_dpi"],
            font=(config["map_font_family"], config["map_font_size"]),
            keep_markers=config["map_keep_markers"],
            attempt_label_repositioning=config["map_attempt_label_repositioning"],
            settlement_label_padding_cm=config.get("map_settlement_label_padding_cm", 0),
            peak_label_padding_cm=config.get("map_peak_label_padding_cm", 0),
            x_inverted=config.get("map_x_inverted", False),
    )

    if config.get("map_peaks", False):
        mountain_peaks = osm_api.fetch_mountain_peaks_in_projected_coordinates(bounds)

        mountain_peaks = list(filter(lambda x : x["elevation"], mountain_peaks))
        mountain_peaks = list(filter(lambda x : x["name"], mountain_peaks))
        mountain_peaks.sort(key = lambda x : x["elevation"])

        map_instance.mountain_peaks = mountain_peaks

        map_instance.draw_mountain_peaks(
            color=config.get("map_peak_color", "black"),
            fontweight=config.get("map_peak_fontweight", "bold"),
            italic=config.get("map_peak_label_italic", False)
        )
    
    if config.get("map_mountain_huts", False):
        mountain_huts = osm_api.fetch_mountain_huts_in_projected_coordinates(bounds)
        map_instance.mountain_huts = mountain_huts
        map_instance.draw_mountain_huts(
            color=config.get("map_mountain_hut_color", "black"),
            fontweight=config.get("map_mountain_hut_fontweight", "normal"),
            italic=config.get("map_hut_label_italic", False),
        )
    
    if config.get("map_settlements", False):
        settlements = osm_api.fetch_settlements_in_projected_coordinates(
            bounds,
            city=config.get("map_city", True),
            town=config.get("map_town", True),
            suburb=config.get("map_suburb", True),
            village=config.get("map_village", True),
            neighbourhood=config.get("map_neighbourhood", True),
            hamlet=config.get("map_hamlet", False),
            isolated_dwelling=config.get("map_isolated_dwelling", False),
        )
        map_instance.settlements = settlements
        map_instance.draw_settlements(
            color=config.get("map_settlement_color", "black"),
            fontweight=config.get("map_settlement_fontweight", "bold"),
            italic=config.get("map_settlement_label_italic", False),
        )

    if config.get("map_railways", False):
        railways = osm_api.fetch_railways_in_projected_coordinates(bounds)
        map_instance.railways = railways
        map_instance.draw_railways()
    
    if config.get("map_streets", False):
        streets = osm_api.fetch_streets_in_projected_coordinates(
            bounds,
            motorway=config.get("map_motorway", True),
            trunk=config.get("map_trunk", True),
            primary=config.get("map_primary", True),
            secondary=config.get("map_secondary", True),
            tertiary=config.get("map_tertiary", True),
            residential=config.get("map_residential", False),
            service=config.get("map_service", False),
            path=config.get("map_path", False),
            footway=config.get("map_footway", False),
            track=config.get("map_track", False),
        )
        map_instance.streets = streets
        map_instance.draw_streets()
    
    if config.get("map_waterways", False):
        waterways = osm_api.fetch_waterways_in_projected_coordinates(
            bounds,
            river=config.get("map_waterway_river", True),
            stream=config.get("map_waterway_stream", True),
            canal=config.get("map_waterway_canal", True),
            ditch=config.get("map_waterway_ditch", False),
            drain=config.get("map_waterway_drain", False),
        )
        map_instance.waterways = waterways
        map_instance.draw_waterways(
            color=config.get("map_waterway_color", "0.75")
        )
    
    if config.get("map_water", False):
        water = osm_api.fetch_water_in_projected_coordinates(
            bounds,
            lake=config.get("map_water_lake", True),
            reservoir=config.get("map_water_reservoir", True),
            river=config.get("map_water_river", True),
            canal=config.get("map_water_canal", False),
            lock=config.get("map_water_lock", False),
        )
        map_instance.water = water
        map_instance.draw_water(
            color=config.get("map_water_color", "0.75"),
            draw_inners=True,
        )

    if gps_segments:
        map_instance.draw_gps_tracks(gps_segments, line_thickness=gpx_width)

    if config.get("map_bounding_shape", False):
        map_instance.draw_bounding_shape()

    if config.get("map_logo", False):
        # use a reliable logo path relative to this script
        logo_path = os.path.join(os.path.dirname(__file__), "logo.png")
        logo_height_cm = config.get("map_logo_height_cm", 0.5)
        logo_width_cm = config.get("map_logo_width_cm", 3.0)
        map_instance.draw_image(logo_path, position=(map_instance.width / 2, logo_height_cm), width=logo_width_cm)

    print("Resolving overlaps...")
    map_instance.resolve_overlaps()

    # make output path absolute and ensure output folder exists
    output_image_path = os.path.abspath(os.path.join(config["output_folder"], config.get("aoi_name", ""), config.get("map_filename", "map.png")))
    os.makedirs(os.path.dirname(output_image_path), exist_ok=True)

    map_instance.save(output_image_path)

    print(f"Map image saved to {output_image_path}")

    return output_image_path

def load_config(config_file):
    with open(config_file, 'r') as file:
        config = yaml.safe_load(file)
    return config

def parse_arguments():
    parser = argparse.ArgumentParser(description='Generate map image.')
    parser.add_argument('--config', type=str, required=True, help='Path to the configuration file.')
    return parser.parse_args()

def main(config_file):
    config = load_config(config_file)

    if config.get("generate_map", False):
        generate_map(config)
    else:
        print("Map generation is disabled in the configuration.")

if __name__ == "__main__":
    args = parse_arguments()
    main(args.config)