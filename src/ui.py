"""PySide6 map generation configuration editor."""
from copy import deepcopy
import math
from pathlib import Path
import sys

import yaml
from PySide6.QtCore import QThread, Qt, Slot
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

from generation_worker import GenerationWorker, PROJECT_ROOT
from gpx_track import DEFAULT_LINE_THICKNESS, validate_line_thickness


PARAMETER_DESCRIPTIONS = {
    "input_file": "Input geometry file (.shp or .geojson) containing the geometry to process. Leave empty to generate from AOI parameters.",
    "input_folder": "Folder containing multiple geometry files for bulk processing (only when use_bulk is enabled)",
    "use_bulk": "Enable to process multiple files from input_folder instead of a single input_file",
    "rasterfile": "Digital Terrain Model (.tif) file providing elevation data. Leave empty to download from OpenTopography.",
    "auto_download_dem": "Automatically download DEM from OpenTopography if rasterfile is not specified",
    "dem_type": "DEM source: COP30 (Copernicus 30m), NASADEM (NASA 30m), or SRTMGL1 (SRTM 30m)",
    "opentopo_api_key": "Your OpenTopography API key (get from https://portal.opentopography.org)",
    "prefer_etrs89_in_europe": "Use ETRS89 (EPSG:258xx) for European coordinates instead of WGS84 UTM",
    "output_folder": "Output folder where generated map images will be saved",
    "gpx_file": "Optional GPX track file (.gpx) rendered as a black line on the map",
    "gpx_line_thickness": "GPS track line width in points (1 point = 1/72 inch). Must be positive.",
    "scale": "Map scale factor (e.g., 50000 = 1:50,000). Higher values = smaller physical output",
    "add_base_height": "Base thickness added to the bottom of the model (in mm)",
    "variable_base_height": "When true, adjusts base height dynamically based on terrain variation",
    "height_scale": "Height scaling factor when variable_base_height is enabled (higher = more compressed)",
    "z_scale": "Vertical exaggeration factor for terrain height (1.0 = real scale, 2.0 = double height, 0.5 = half height)",
    "offset_mm": "Buffer distance around geometry boundaries (in mm)",
    "window_size": "Size of the filter window for outlier detection (larger = more smoothing)",
    "threshold": "Threshold value for outlier detection (higher = less sensitive)",
    "lower_water_surface": "Enable automatic water surface detection and adjustment",
    "water_offset_mm": "Amount to lower detected water surfaces (in mm)",
    "water_min_region_size": "Minimum number of pixels for a flat region to be considered water (higher = fewer small areas detected)",
    "water_variance_threshold": "Maximum local variance for a region to be considered flat/water (lower = stricter detection)",
    "water_closing_iterations": "Number of morphological closing iterations to fill holes in water mask (higher = more smoothing)",
    "generate_ngc": "Generate G-code files (.ngc) for CNC machining",
    "generate_laser_gcode": "Generate laser engraving G-code following GPS tracks",
    "rotate_90": "Rotate the model 90 degrees for machining orientation",
    "ngc_grid_resolution": "Grid resolution for G-code generation [X, Y] (in mm)",
    "bit_radius": "Radius of the cutting bit for G-code toolpath compensation (in mm)",
    "start_from_back": "Start machining from the back of the workpiece",
    "generate_stl": "Generate 3D printable STL files",
    "stl_grid_resolution": "Grid resolution for STL generation [X, Y] (in mm)",
    "alternate_spacing": "Use alternating Y-spacing for toolpath optimization",
    "spacing_y": "Y-axis spacing values [spacing1, spacing2] when alternate_spacing is enabled",
    "generate_aoi": "Generate AOI shapefile from parameters below (only if input_file is empty)",
    "aoi_name": "Name for the generated AOI (used in output folder and shapefile naming)",
    "aoi_shape_type": "Shape type for generated AOI: circle, square, rectangle, or hexagon",
    "aoi_center_coords": "Center coordinates as 'latitude, longitude' (can paste directly from Google Maps)",
    "aoi_crs_epsg": "Output CRS EPSG code for generated AOI shapefile (leave empty to automatically select optimal UTM zone)",
    "aoi_dimension1_mm": "Dimension in mm - Circle: radius | Square: side length | Rectangle: width (X) | Hexagon: inner radius",
    "aoi_dimension2_mm": "Rectangle height (Y) in mm - only used when shape is rectangle, ignored for other shapes",
    "save_generated_shapefile": "Save the generated AOI shapefile to disk (otherwise it's created temporarily)",
    "save_geojson": "Also save the generated AOI as GeoJSON in WGS84 format"
}

PARAM_GROUPS = {
            "Input/Output Settings": ["input_file", "input_folder", "use_bulk", "rasterfile", "output_folder", "gpx_file"],
            "AOI Generation": ["generate_aoi", "aoi_name", "aoi_shape_type", "aoi_center_coords", "aoi_crs_epsg", "aoi_dimension1_mm", "aoi_dimension2_mm", "save_generated_shapefile", "save_geojson"],
            "Map Generation": [
                "generate_map", "gpx_line_thickness",
                "map_filename", "map_dpi", "map_font_family",
                "map_font_size", "map_fontweight", "map_x_inverted", "map_keep_markers",
                "map_attempt_label_repositioning",
                "map_logo", "map_logo_width_cm", "map_logo_height_cm",
                "map_peaks", "map_peak_label_padding_cm",
                "map_peak_color", "map_peak_fontweight", "map_peak_label_italic",
                "map_mountain_huts", "map_mountain_hut_color", "map_mountain_hut_fontweight", "map_mountain_hut_label_italic",
                "map_settlements", "map_settlement_label_padding_cm",
                "map_settlement_color", "map_settlement_fontweight", "map_settlement_label_italic",
                "map_city", "map_town", "map_suburb", "map_village", "map_neighbourhood", "map_hamlet", "map_isolated_dwelling",
                "map_streets",
                "map_motorway", "map_trunk", "map_primary", "map_secondary", "map_tertiary", "map_residential", "map_service",
                "map_path", "map_footway", "map_track",
                "map_railways", "map_rail", "map_light_rail", "map_narrow_gauge",
                "map_waterways", "map_waterway_color",
                "map_waterway_river", "map_waterway_stream", "map_waterway_canal", "map_waterway_ditch", "map_waterway_drain",
                "map_water", "map_water_color",
                "map_water_lake", "map_water_reservoir", "map_water_river", "map_water_canal", "map_water_lock",
            ],
        }


class ConfigEditor(QMainWindow):
    def __init__(self, config_folder=None):
        super().__init__()
        self.setWindowTitle("Map Generation Configuration Editor")
        self.resize(950, 700)
        self.setMinimumSize(930, 500)
        self.config_folder = Path(config_folder) if config_folder else PROJECT_ROOT / 'src' / 'config'
        self.config_data = {}
        self.value_types = {}
        self.widgets = {}
        self.dimension_labels = {}
        self.thread = None
        self.worker = None
        self.running = False
        self.create_widgets()

    def create_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        self.header = QWidget()
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(QLabel('Select Config File:'))
        row = QHBoxLayout()
        self.config_dropdown = QComboBox()
        self.config_dropdown.setMinimumWidth(320)
        self.config_dropdown.activated.connect(self.load_config)
        row.addWidget(self.config_dropdown)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.clicked.connect(self.load_config_files)
        row.addWidget(self.refresh_button)
        row.addStretch()
        header_layout.addLayout(row)
        layout.addWidget(self.header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)
        self.actions = QWidget()
        buttons = QHBoxLayout(self.actions)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.generate_button = QPushButton('Generate Map')
        self.generate_button.clicked.connect(self.generate_data)
        self.save_button = QPushButton('Save Config')
        self.save_button.clicked.connect(self.save_config)
        self.save_as_button = QPushButton('Save Config As...')
        self.save_as_button.clicked.connect(self.open_save_dialog)
        for button in (self.generate_button, self.save_button, self.save_as_button):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addWidget(self.actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status_label = QLabel('Select a configuration to begin.')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.load_config_files()

    def show_error(self, title, message):
        print(f'{title}: {message}', file=sys.stderr)
        QMessageBox.critical(self, title, message)

    def show_info(self, title, message):
        print(f'{title}: {message}')
        QMessageBox.information(self, title, message)

    def load_config_files(self):
        selected = self.config_dropdown.currentText()
        self.config_dropdown.blockSignals(True)
        self.config_dropdown.clear()
        self.config_dropdown.addItem('')
        try:
            self.config_dropdown.addItems(sorted(p.name for p in self.config_folder.glob('*.yaml')))
        except OSError as exc:
            self.show_error('Error', str(exc))
        self.config_dropdown.setCurrentText(selected)
        self.config_dropdown.blockSignals(False)

    def load_config(self, *_):
        filename = self.config_dropdown.currentText()
        if not filename:
            return
        try:
            data = yaml.safe_load((self.config_folder / filename).read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('Configuration must contain a YAML mapping.')
        except (OSError, ValueError, yaml.YAMLError) as exc:
            self.show_error('Cannot load configuration', str(exc))
            # Restore the selection associated with the displayed configuration.
            self.config_dropdown.setCurrentText(getattr(self, 'loaded_filename', ''))
            return
        data.setdefault('gpx_file', data.get('gpxfile', ''))
        data.setdefault('gpx_line_thickness', DEFAULT_LINE_THICKNESS)
        self.loaded_filename = filename
        self.config_data = data
        self.value_types = {key: type(value) for key, value in data.items()}
        self.display_config_params()
        self.status_label.setText(f'Loaded {filename}')

    def display_config_params(self):
        self.widgets = {}
        self.dimension_labels = {}
        container = QWidget()
        layout = QHBoxLayout(container)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        for group_names in (('Input/Output Settings', 'AOI Generation'), ('Map Generation',)):
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            for group_name in group_names:
                keys = [k for k in PARAM_GROUPS[group_name] if k in self.config_data]
                if not keys:
                    continue
                group = QGroupBox(group_name)
                form = QFormLayout(group)
                for key in keys:
                    self.create_parameter_widget(form, key, self.config_data[key])
                column_layout.addWidget(group)
            column_layout.addStretch()
            splitter.addWidget(column)
        splitter.setSizes([450, 450])
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.scroll.setWidget(container)
        self.update_conditional_fields()

    def create_parameter_widget(self, form, key, value):
        label = QLabel(f'{key}:')
        tooltip = PARAMETER_DESCRIPTIONS.get(key, '')
        label.setToolTip(tooltip)
        if key.startswith('aoi_dimension'):
            self.dimension_labels[key] = label
        if key == 'gpx_line_thickness':
            widget = QLineEdit(str(value))
        elif isinstance(value, bool):
            widget = QCheckBox()
            widget.setChecked(value)
            widget.toggled.connect(self.update_conditional_fields)
        elif key in ('aoi_shape_type', 'dem_type'):
            widget = QComboBox()
            widget.addItems(['circle', 'square', 'rectangle', 'hexagon'] if key == 'aoi_shape_type'
                            else ['COP30', 'NASADEM', 'SRTMGL1'])
            if value is not None and str(value) not in [widget.itemText(i) for i in range(widget.count())]:
                widget.addItem(str(value))
            widget.setCurrentText(str(value))
            widget.currentTextChanged.connect(self.update_conditional_fields)
        else:
            widget = QLineEdit('' if value is None else str(value))
        widget.setToolTip(tooltip)
        self.widgets[key] = widget
        if key in ('input_file', 'rasterfile', 'gpx_file', 'input_folder', 'output_folder'):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(widget)
            browse = QPushButton('Browse...')
            browse.clicked.connect(lambda checked=False, k=key: self.browse_path(k))
            row_layout.addWidget(browse)
            if key == 'input_folder':
                self.input_folder_row = row
            form.addRow(label, row)
        else:
            form.addRow(label, widget)

    def update_conditional_fields(self, *_):
        bulk = self.widgets.get('use_bulk')
        if 'input_folder' in self.widgets:
            enabled = bulk.isChecked() if bulk else self.config_data.get('use_bulk', False)
            self.input_folder_row.setEnabled(enabled)
            self.input_folder_row.setToolTip('' if enabled else "Enable 'use_bulk' to edit")
        shape_widget = self.widgets.get('aoi_shape_type')
        shape = shape_widget.currentText() if shape_widget else self.config_data.get('aoi_shape_type', 'circle')
        if 'aoi_dimension1_mm' in self.dimension_labels:
            meaning = {'circle': 'radius', 'square': 'side', 'rectangle': 'width', 'hexagon': 'inner radius'}.get(shape, 'dimension')
            self.dimension_labels['aoi_dimension1_mm'].setText(f'aoi_dimension1_mm ({meaning}):')
        if 'aoi_dimension2_mm' in self.widgets:
            self.widgets['aoi_dimension2_mm'].setEnabled(shape == 'rectangle')
            self.widgets['aoi_dimension2_mm'].setToolTip('Rectangle height (mm)' if shape == 'rectangle' else 'Only for rectangle')
            self.dimension_labels['aoi_dimension2_mm'].setText('aoi_dimension2_mm (height):' if shape == 'rectangle' else 'aoi_dimension2_mm:')
        if 'height_scale' in self.widgets:
            toggle = self.widgets.get('variable_base_height')
            self.widgets['height_scale'].setEnabled(toggle.isChecked() if toggle else self.config_data.get('variable_base_height', False))

    def browse_path(self, key):
        folder = key in ('input_folder', 'output_folder')
        initial = PROJECT_ROOT / ('outputs' if key == 'output_folder' else 'inputs')
        if key == 'rasterfile' or not initial.exists():
            initial = PROJECT_ROOT
        if folder:
            selected = QFileDialog.getExistingDirectory(self, 'Select Folder', str(initial))
        else:
            filters = {'input_file': 'Geometry (*.shp *.geojson);;All files (*)',
                       'rasterfile': 'TIFF files (*.tif *.tiff);;All files (*)',
                       'gpx_file': 'GPX files (*.gpx);;All files (*)'}
            selected, _ = QFileDialog.getOpenFileName(self, 'Select File', str(initial), filters[key])
        if selected:
            path = Path(selected)
            try:
                selected = str(path.relative_to(PROJECT_ROOT))
            except ValueError:
                pass
            self.widgets[key].setText(selected)

    def commit_fields(self):
        updated = deepcopy(self.config_data)
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                updated[key] = widget.isChecked()
                continue
            text = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
            original_type = self.value_types[key]
            try:
                if key == 'gpx_line_thickness':
                    value = validate_line_thickness(text)
                elif original_type is int:
                    value = int(text)
                elif original_type is float:
                    value = float(text)
                    if not math.isfinite(value):
                        raise ValueError('must be finite')
                elif original_type is list:
                    value = yaml.safe_load(text)
                    if not isinstance(value, list):
                        raise ValueError('expected a YAML list')
                    # Preserve element types where the existing list supplies them.
                    original = self.config_data[key]
                    for index, item in enumerate(value):
                        kind = type(original[index]) if index < len(original) else None
                        if kind in (int, float):
                            if isinstance(item, bool) or not isinstance(item, (int, float)):
                                raise ValueError('expected numeric list elements')
                            if kind is int and int(item) != item:
                                raise ValueError('expected integer list elements')
                            value[index] = kind(item)
                            if not math.isfinite(value[index]):
                                raise ValueError('must be finite')
                elif original_type is type(None):
                    value = None if text.strip().lower() in ('', 'none', 'null') else yaml.safe_load(text)
                else:
                    value = text
                updated[key] = value
            except (ValueError, TypeError, yaml.YAMLError) as exc:
                self.show_error('Invalid configuration value', f'{key}: {exc}')
                widget.setFocus()
                return False
        self.config_data = updated
        return True

    def save_config(self):
        filename = getattr(self, 'loaded_filename', '')
        if not filename:
            self.show_error('Error', 'No config file selected.')
            return
        if self.commit_fields():
            self.write_config(filename)

    def write_config(self, filename):
        try:
            (self.config_folder / filename).write_text(yaml.safe_dump(self.config_data), encoding='utf-8')
        except (OSError, yaml.YAMLError) as exc:
            self.show_error('Cannot save configuration', str(exc))
            return False
        self.show_info('Success', 'Config file saved successfully.')
        return True

    def open_save_dialog(self):
        if not getattr(self, 'loaded_filename', ''):
            self.show_error('Error', 'No config file selected.')
            return
        filename, accepted = QInputDialog.getText(self, 'Save Config As', 'Enter Config File Name:')
        if not accepted:
            return
        filename = filename.strip()
        if not filename or Path(filename).name != filename or filename in ('.', '..'):
            self.show_error('Error', 'Provide a config filename without directories.')
            return
        if not filename.endswith('.yaml'):
            filename += '.yaml'
        if self.commit_fields() and self.write_config(filename):
            self.loaded_filename = filename
            self.load_config_files()
            self.config_dropdown.setCurrentText(filename)

    def generate_data(self):
        if self.running:
            return
        if not getattr(self, 'loaded_filename', ''):
            self.show_error('Error', 'No config file selected.')
            return
        if not self.commit_fields():
            return
        self.set_running(True)
        self.thread = QThread(self)
        self.worker = GenerationWorker(self.config_data)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self.status_label.setText)
        self.worker.completed.connect(self.generation_completed)
        self.worker.failed.connect(self.generation_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.generation_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def set_running(self, running):
        self.running = running
        for widget in (self.header, self.scroll, self.actions):
            widget.setEnabled(not running)
        self.progress.setVisible(running)
        if running:
            self.status_label.setText('Starting generation…')

    @Slot(object)
    def generation_completed(self, result):
        if result['saved_input']:
            self.config_data['input_file'] = result['saved_input']
            if 'input_file' in self.widgets:
                self.widgets['input_file'].setText(result['saved_input'])
        message = '\n'.join(result['outputs'])
        if result['failures']:
            self.status_label.setText('Generation finished with errors.')
            self.show_error('Generation failures', '\n'.join(result['failures']) + ('\n\nGenerated outputs:\n' + message if message else ''))
        else:
            self.status_label.setText('Generation complete.')
            self.show_info('Success', 'Generation complete. Output files:\n' + message)

    @Slot(str)
    def generation_failed(self, message):
        self.status_label.setText('Generation failed.')
        self.show_error('Generation failed', message)

    @Slot()
    def generation_finished(self):
        self.worker = None
        self.thread = None
        self.set_running(False)

    def closeEvent(self, event):
        if self.running:
            self.show_info('Generation in progress', 'Wait for generation to finish before closing the window.')
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    window = ConfigEditor()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
