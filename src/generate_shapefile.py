import shapefile
from shapely.geometry import Point, box, Polygon
from shapely.ops import transform
import pyproj
from pyproj import CRS, Transformer
import tkinter as tk
from tkinter import filedialog
import math
import json

def generate_shapefile(center_lon, center_lat, output_crs_epsg, dimension1_mm, dimension2_mm, scale, output_filepath, shape_type, save_geojson=False):
    # Define the coordinate transformation from WGS84 to the desired output CRS
    crs_wgs84 = CRS.from_epsg(4326)
    crs_output = CRS.from_epsg(output_crs_epsg)
    transformer = Transformer.from_crs(crs_wgs84, crs_output, always_xy=True)

    # Transform the center coordinates to the output CRS
    x, y = transformer.transform(center_lon, center_lat)

    # Calculate the radius or side lengths in meters
    dimension1_meters = (dimension1_mm / 1000) * scale
    dimension2_meters = (dimension2_mm / 1000) * scale if dimension2_mm else dimension1_meters
    print('dimension1_meters:', dimension1_meters)
    print('dimension2_meters:', dimension2_meters)

    # Create a shapefile writer for polygons
    shp_writer_poly = shapefile.Writer(output_filepath, shapeType=shapefile.POLYGON)
    shp_writer_poly.field('Name', 'C')

    # Create the shape based on the shape_type
    point = Point(x, y)
    if shape_type == 'circle':
        shape = point.buffer(dimension1_meters)  # Buffer in meters
    elif shape_type == 'square':
        shape = box(x - dimension1_meters / 2, y - dimension1_meters / 2, x + dimension1_meters / 2, y + dimension1_meters / 2)
    elif shape_type == 'rectangle':
        shape = box(x - dimension1_meters / 2, y - dimension2_meters / 2, x + dimension1_meters / 2, y + dimension2_meters / 2)
    elif shape_type == 'hexagon':
        # Create a regular hexagon with given inner circle radius (apothem)
        # For a regular hexagon: apothem = side_length * sqrt(3) / 2
        # Therefore: side_length = apothem * 2 / sqrt(3)
        # Circumradius (center to vertex) = side_length
        apothem = dimension1_meters
        side_length = apothem * 2 / math.sqrt(3)
        circumradius = side_length  # For regular hexagon, circumradius = side_length
        
        # Calculate the 6 vertices of the hexagon (flat-topped orientation, flat side at bottom)
        # Starting from the right vertex and going counter-clockwise
        vertices = []
        for i in range(6):
            angle = math.pi / 3 * i  # Start at 0° (pointing right), then add 60° for each vertex
            vertex_x = x + circumradius * math.cos(angle)
            vertex_y = y + circumradius * math.sin(angle)
            vertices.append((vertex_x, vertex_y))
        
        shape = Polygon(vertices)
    else:
        raise ValueError("Unsupported shape type")

    # Add shape to the polygon shapefile
    shp_writer_poly.poly([list(shape.exterior.coords)])
    shp_writer_poly.record(shape_type.capitalize())

    # Save the shapefile
    shp_writer_poly.close()
    
    # Write .prj file with CRS information in WKT1 format for compatibility
    prj_path = output_filepath.replace('.shp', '.prj')
    with open(prj_path, 'w') as prj_file:
        # Use WKT1 (ESRI) format for better compatibility with shapefile readers
        prj_file.write(crs_output.to_wkt(version='WKT1_ESRI'))
    print(f'Created projection file: {prj_path}')
    
    # Optionally save as GeoJSON in WGS84
    if save_geojson:
        # Transform shape back to WGS84
        transformer_to_wgs84 = Transformer.from_crs(crs_output, crs_wgs84, always_xy=True)
        
        # Transform the shape coordinates
        def transform_coords(coords):
            """Transform a list of coordinate tuples from output CRS to WGS84"""
            transformed = []
            for coord in coords:
                lon, lat = transformer_to_wgs84.transform(coord[0], coord[1])
                transformed.append([lon, lat])
            return transformed
        
        # Get the exterior coordinates and transform them
        exterior_coords = list(shape.exterior.coords)
        wgs84_coords = transform_coords(exterior_coords)
        
        # Create GeoJSON structure
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "Name": shape_type.capitalize(),
                    "center_lat": center_lat,
                    "center_lon": center_lon,
                    "dimension1_mm": dimension1_mm,
                    "dimension2_mm": dimension2_mm if dimension2_mm else dimension1_mm,
                    "scale": scale,
                    "shape_type": shape_type,
                    "output_crs_epsg": output_crs_epsg
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [wgs84_coords]
                }
            }]
        }
        
        # Save GeoJSON file
        geojson_path = output_filepath.replace('.shp', '.geojson')
        with open(geojson_path, 'w') as f:
            json.dump(geojson, f, indent=2)
        print(f'Created GeoJSON file (WGS84): {geojson_path}')

def create_ui():
    def update_fields(*args):
        shape_type = shape_var.get()
        if shape_type == 'circle':
            label_radius.config(text="Radius (mm):")
            label_radius.grid(row=3, column=0)
            entry_radius.grid(row=3, column=1)
            label_side_length.grid_remove()
            entry_side_length.grid_remove()
            label_side_length_x.grid_remove()
            entry_side_length_x.grid_remove()
            label_side_length_y.grid_remove()
            entry_side_length_y.grid_remove()
        elif shape_type == 'square':
            label_side_length.config(text="Side Length (mm):")
            label_side_length.grid(row=3, column=0)
            entry_side_length.grid(row=3, column=1)
            label_radius.grid_remove()
            entry_radius.grid_remove()
            label_side_length_x.grid_remove()
            entry_side_length_x.grid_remove()
            label_side_length_y.grid_remove()
            entry_side_length_y.grid_remove()
        elif shape_type == 'rectangle':
            label_side_length_x.config(text="Side Length X (mm):")
            label_side_length_y.config(text="Side Length Y (mm):")
            label_side_length_x.grid(row=3, column=0)
            entry_side_length_x.grid(row=3, column=1)
            label_side_length_y.grid(row=4, column=0)
            entry_side_length_y.grid(row=4, column=1)
            label_radius.grid_remove()
            entry_radius.grid_remove()
            label_side_length.grid_remove()
            entry_side_length.grid_remove()
        elif shape_type == 'hexagon':
            label_radius.config(text="Inner Circle Radius (mm):")
            label_radius.grid(row=3, column=0)
            entry_radius.grid(row=3, column=1)
            label_side_length.grid_remove()
            entry_side_length.grid_remove()
            label_side_length_x.grid_remove()
            entry_side_length_x.grid_remove()
            label_side_length_y.grid_remove()
            entry_side_length_y.grid_remove()

    def submit():
        coords = entry_coords.get().split(',')
        center_lon = float(coords[1].strip())
        center_lat = float(coords[0].strip())
        output_crs_epsg = int(entry_crs.get())
        shape_type = shape_var.get()
        output_filepath = filedialog.asksaveasfilename(defaultextension=".shp", filetypes=[("Shapefiles", "*.shp")])
        if shape_type == 'circle' or shape_type == 'hexagon':
            dimension1_mm = float(entry_radius.get())
            dimension2_mm = None
        elif shape_type == 'square':
            dimension1_mm = float(entry_side_length.get())
            dimension2_mm = None
        elif shape_type == 'rectangle':
            dimension1_mm = float(entry_side_length_x.get())
            dimension2_mm = float(entry_side_length_y.get())
        scale = float(entry_scale.get())
        save_geojson = geojson_var.get()
        generate_shapefile(center_lon, center_lat, output_crs_epsg, dimension1_mm, dimension2_mm, scale, output_filepath, shape_type, save_geojson)
        root.destroy()

    root = tk.Tk()
    root.title("Generate Shapefile")

    tk.Label(root, text="Shape Type:").grid(row=0)
    shape_var = tk.StringVar(value='circle')
    shape_menu = tk.OptionMenu(root, shape_var, 'circle', 'square', 'rectangle', 'hexagon')
    shape_menu.grid(row=0, column=1)

    tk.Label(root, text="Coordinates (lat, lon):").grid(row=1)
    tk.Label(root, text="Output CRS EPSG:").grid(row=2)
    label_radius = tk.Label(root, text="Radius (mm):")
    label_side_length = tk.Label(root, text="Side Length (mm):")
    label_side_length_x = tk.Label(root, text="Side Length X (mm):")
    label_side_length_y = tk.Label(root, text="Side Length Y (mm):")
    tk.Label(root, text="Scale:").grid(row=5)

    entry_coords = tk.Entry(root)
    entry_crs = tk.Entry(root)
    entry_crs.insert(0, "25832")
    entry_radius = tk.Entry(root)
    entry_side_length = tk.Entry(root)
    entry_side_length_x = tk.Entry(root)
    entry_side_length_y = tk.Entry(root)
    entry_scale = tk.Entry(root)
    entry_scale.insert(0, "100000")

    entry_coords.grid(row=1, column=1)
    entry_crs.grid(row=2, column=1)
    entry_radius.grid(row=3, column=1)
    entry_scale.grid(row=5, column=1)
    
    # Add checkbox for GeoJSON export
    geojson_var = tk.BooleanVar(value=False)
    tk.Checkbutton(root, text="Also save as GeoJSON (WGS84)", variable=geojson_var).grid(row=6, column=0, columnspan=2)

    shape_var.trace('w', update_fields)

    # Initialize the fields based on the default shape type
    update_fields()

    tk.Button(root, text="Generate Shapefile", command=submit).grid(row=7, column=0, columnspan=2)

    root.mainloop()

# Example usage
if __name__ == "__main__":
    create_ui()
