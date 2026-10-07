"""Background orchestration for the configuration editor.

Only the worker uses Qt; processing never reads or changes GUI state.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml
from PySide6.QtCore import QObject, Signal, Slot

from generate_shapefile import generate_shapefile
from utm_finder import (
    get_utm_zone_from_lon, is_in_norway_special_zone,
    is_in_svalbard_special_zone, _get_epsg_from_zone,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def project_path(value, root=PROJECT_ROOT):
    path = Path(value)
    return path if path.is_absolute() else root / path


def prepare_aoi(config, scratch, root):
    """Prepare an AOI in scratch or inputs, returning its path and saved update."""
    lat, lon = [float(v.strip()) for v in config.get('aoi_center_coords', '47.2692, 11.4041').split(',')]
    epsg = config.get('aoi_crs_epsg')
    if epsg is None or str(epsg).strip().lower() in ('', 'none'):
        zone = (is_in_svalbard_special_zone(lat, lon)
                or is_in_norway_special_zone(lat, lon)
                or get_utm_zone_from_lon(lon))
        epsg = _get_epsg_from_zone(zone, 'north' if lat >= 0 else 'south',
                                   config.get('prefer_etrs89_in_europe', False), lat, lon)
    else:
        epsg = int(epsg)
    name = config.get('aoi_name', 'generated_aoi')
    if not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('AOI name must be a filename without directories.')
    shape = config.get('aoi_shape_type', 'circle')
    permanent = config.get('save_generated_shapefile', False)
    # Export GeoJSON from scratch rather than overwriting/deleting permanent shapefiles.
    source = Path(scratch) / f'{name}.shp'
    generate_shapefile(lon, lat, epsg, config.get('aoi_dimension1_mm', 100),
                       config.get('aoi_dimension2_mm') if shape == 'rectangle' else None,
                       config.get('scale', 50000), str(source), shape,
                       save_geojson=config.get('save_geojson', False))
    saved_input = None
    if permanent:
        destination = root / 'inputs'
        destination.mkdir(parents=True, exist_ok=True)
        for ext in ('.shp', '.shx', '.dbf', '.prj'):
            shutil.copy2(source.with_suffix(ext), destination / f'{name}{ext}')
        saved_input = str(Path('inputs') / source.name)
    if config.get('save_geojson', False):
        destination = project_path(config.get('output_folder', 'outputs'), root) / name
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.with_suffix('.geojson'), destination / f'{name}.geojson')
    return str(root / saved_input) if saved_input else str(source), saved_input


def run_generation(config, status=print, root=PROJECT_ROOT, force_refresh=False):
    """Run immutable per-item snapshots and always clean temporary resources."""
    config = deepcopy(config)
    root = Path(root)
    outputs, failures = [], []
    saved_input = None
    with tempfile.TemporaryDirectory(prefix='map-generator-') as scratch:
        if config.get('use_bulk', False):
            folder = project_path(config.get('input_folder', ''), root)
            if not config.get('input_folder') or not folder.is_dir():
                raise ValueError('Select an existing input folder for bulk generation.')
            inputs = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.shp', '.geojson'))
            if not inputs:
                raise ValueError('No shapefiles or GeoJSON files found in the input folder.')
        elif not str(config.get('input_file') or '').strip() and config.get('generate_aoi', False):
            status('Preparing AOI…')
            source, saved_input = prepare_aoi(config, scratch, root)
            inputs = [Path(source)]
        else:
            if not config.get('input_file'):
                raise ValueError('Select an input file or enable AOI generation.')
            inputs = [project_path(config['input_file'], root)]
        for index, source in enumerate(inputs, 1):
            status(f'Generating map {index}/{len(inputs)}: {source.name}')
            item = deepcopy(config)
            item['input_file'] = str(source)
            item['use_bulk'] = False
            if config.get('use_bulk', False):
                item['map_filename'] = f'{source.stem}_map.png'
            temp_config = Path(scratch) / 'processing.yaml'
            try:
                temp_config.write_text(yaml.safe_dump(item), encoding='utf-8')
                command = [sys.executable, str(root / 'src' / 'generate_map.py'), '--config', str(temp_config)]
                if force_refresh:
                    command.append('--refresh-osm')
                result = subprocess.run(
                    command,
                    cwd=str(root), check=False,
                )
                if result.returncode:
                    failures.append(f'{source.name}: generation exited with code {result.returncode}. See terminal output.')
                else:
                    output = project_path(item.get('output_folder', 'outputs'), root) / item.get('aoi_name', '') / item.get('map_filename', 'map.png')
                    outputs.append(str(output.resolve()))
            except Exception as exc:
                failures.append(f'{source.name}: {exc}')
            finally:
                temp_config.unlink(missing_ok=True)
    return {'outputs': outputs, 'failures': failures, 'saved_input': saved_input}


class GenerationWorker(QObject):
    status = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, config, force_refresh=False):
        super().__init__()
        self.config = deepcopy(config)
        self.force_refresh = force_refresh

    @Slot()
    def run(self):
        try:
            if self.force_refresh:
                result = run_generation(self.config, self.status.emit, force_refresh=True)
            else:
                result = run_generation(self.config, self.status.emit)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.finished.emit()
