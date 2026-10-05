# Map Generator

A Python-based tool for generating simple maps. Intended for grayscale laser engraving. Create customizable maps featuring mountain peaks, settlements, streets, railways, water bodies, and more using OpenStreetMap data.

![Map example Zugspitze](assets/Zugspitze.png)

## Features

- **Area of Interest (AOI) Generation**: Create custom map boundaries in various shapes (circle, square, rectangle, hexagon)
- **OpenStreetMap Integration**: Automatically fetch geographic features including:
  - Mountain peaks and huts
  - Settlements (cities, towns, villages, hamlets)
  - Streets and roads (motorways, primary, secondary, residential)
  - Railways (standard, narrow gauge, light rail)
  - Water bodies (lakes, rivers, canals, reservoirs)
- **Coordinate System Support**: Automatic UTM zone detection with ETRS89 support for European coordinates
- **Configurable Output**: Customize map scale, DPI, fonts, colors, and which features to display
- **Bulk Processing**: Process multiple geometry files at once

## User Interface

![User Interface](assets/UserInterface.png)

## Getting Started

### Prerequisites

- Python 3.9+
- Required Python packages:
  - `PySide6` (Qt GUI)
  - `matplotlib` (map rendering)
  - `shapely` (geometry operations)
  - `pyproj` (coordinate transformations)
  - `pyshp` (shapefile handling)
  - `PyYAML` (configuration)
  - `requests` (OpenStreetMap API)

### Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/map-generator.git
   cd map-generator
   ```

2. Install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```

### Usage

#### Basics
1. Launch the graphical user interface:
   ```bash
   python3 src/ui.py
   ```

   Map generation runs in the background. The window stays responsive and reports
   progress and any failures; configuration controls are disabled until it finishes.

2. Configure your map:
   - Set the center coordinates (latitude, longitude) and choose the AOI shape and dimensions
   - Alternatively provide a custom shapefile
   - Select which map features to include
   - Configure styling options (fonts, colors, scale)

3. Generate your map and find the output in the `outputs/` folder

#### Standalone shapefile generator

```bash
python3 src/generate_shapefile.py
```

Choose a shape, coordinates, EPSG code, and dimensions; optionally export GeoJSON.

#### Command-line map generation

```bash
python3 src/generate_map.py --config src/config/default_config.yaml
```

Launch the GUI scripts from any directory using their absolute paths. Relative
paths in GUI configurations are resolved from the repository root. The map CLI
continues to resolve relative paths from the current working directory.

#### Bulk generation

- Provide a folder with all desired shapefiles
- Set use_bulk parameter to true

### Configuration

Default settings can be modified in `src/config/default_config.yaml` and saved as custom config files. Key parameters include:

| Parameter | Description |
|-----------|-------------|
| `scale` | Map scale (e.g., 100000 = 1:100,000) |
| `aoi_shape_type` | Shape of the area of interest (circle, square, rectangle, hexagon) |
| `map_dpi` | Output resolution in dots per inch |
| `map_peaks` | Include mountain peaks |
| `map_settlements` | Include cities, towns, villages |
| `map_streets` | Include road network |
| `map_water` | Include water bodies |

## Project Structure

```
Map Generator/
├── src/
│   ├── ui.py                 # Graphical user interface
│   ├── generate_map.py       # Main map generation logic
│   ├── generate_shapefile.py # AOI geometry creation
│   ├── map_class.py          # Map rendering class
│   ├── openstreetmap_api.py  # OSM data fetching
│   ├── utm_finder.py         # UTM zone detection
│   └── config/
│       └── default_config.yaml
├── inputs/                   # Input geometry files
├── outputs/                  # Generated maps and data
└── assets/                   # Documentation images
```

## Tests

Run the UI and worker tests without a display or network access:

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
```
