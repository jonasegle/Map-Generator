import shapefile
from shapely.geometry import Point, box, Polygon
from shapely.ops import transform
import pyproj
from pyproj import CRS, Transformer
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

def create_shapefile_window():
    """Create the standalone Qt window without coupling geometry imports to Qt."""
    import math
    from pathlib import Path
    from PySide6.QtWidgets import (
        QCheckBox, QComboBox, QFileDialog, QFormLayout, QLabel, QLineEdit,
        QMessageBox, QPushButton, QWidget,
    )

    class ShapefileWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('Generate Shapefile')
            self.form = QFormLayout(self)
            self.shape = QComboBox()
            self.shape.addItems(['circle', 'square', 'rectangle', 'hexagon'])
            self.coords = QLineEdit()
            self.crs = QLineEdit('25832')
            self.dimension1 = QLineEdit()
            self.dimension2 = QLineEdit()
            self.scale = QLineEdit('100000')
            self.dimension1_label = QLabel()
            self.dimension2_label = QLabel('Side Length Y (mm):')
            self.geojson = QCheckBox('Also save as GeoJSON (WGS84)')
            self.form.addRow('Shape Type:', self.shape)
            self.form.addRow('Coordinates (lat, lon):', self.coords)
            self.form.addRow('Output CRS EPSG:', self.crs)
            self.form.addRow(self.dimension1_label, self.dimension1)
            self.form.addRow(self.dimension2_label, self.dimension2)
            self.form.addRow('Scale:', self.scale)
            self.form.addRow(self.geojson)
            self.generate_button = QPushButton('Generate Shapefile')
            self.form.addRow(self.generate_button)
            self.shape.currentTextChanged.connect(self.update_fields)
            self.generate_button.clicked.connect(self.submit)
            self.update_fields()

        def update_fields(self, *_):
            shape = self.shape.currentText()
            self.dimension1_label.setText({
                'circle': 'Radius (mm):', 'square': 'Side Length (mm):',
                'rectangle': 'Side Length X (mm):', 'hexagon': 'Inner Circle Radius (mm):',
            }[shape])
            self.form.setRowVisible(self.dimension2, shape == 'rectangle')

        def submit(self):
            try:
                lat, lon = [float(v.strip()) for v in self.coords.text().split(',')]
                epsg = int(self.crs.text())
                shape = self.shape.currentText()
                dimension1 = float(self.dimension1.text())
                dimension2 = float(self.dimension2.text()) if shape == 'rectangle' else None
                scale = float(self.scale.text())
                if not all(math.isfinite(v) for v in (lat, lon, dimension1, scale)):
                    raise ValueError('Values must be finite.')
                if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ValueError('Coordinates are outside latitude/longitude bounds.')
                if dimension1 <= 0 or scale <= 0 or (dimension2 is not None and (not math.isfinite(dimension2) or dimension2 <= 0)):
                    raise ValueError('Dimensions and scale must be positive.')
            except ValueError as exc:
                QMessageBox.critical(self, 'Invalid parameters', str(exc))
                return
            filename, _ = QFileDialog.getSaveFileName(self, 'Save Shapefile', '', 'Shapefiles (*.shp)')
            if not filename:
                return
            if not filename.lower().endswith('.shp'):
                filename += '.shp'
            try:
                generate_shapefile(lon, lat, epsg, dimension1, dimension2, scale,
                                   filename, shape, self.geojson.isChecked())
            except Exception as exc:
                QMessageBox.critical(self, 'Generation failed', str(exc))
                return
            QMessageBox.information(self, 'Success', f'Shapefile saved to:\n{Path(filename).resolve()}')
            self.close()

    return ShapefileWindow()


def create_ui():
    import sys
    from PySide6.QtWidgets import QApplication
    existing_app = QApplication.instance()
    app = existing_app or QApplication(sys.argv)
    window = create_shapefile_window()
    window.show()
    if existing_app is None:
        app.exec()
    return window


if __name__ == '__main__':
    create_ui()
