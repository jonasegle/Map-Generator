"""Synthetic GPX fixtures and offline map rendering checks."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'map-generator-mpl'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import numpy as np
import yaml
from PySide6.QtWidgets import QApplication
from pyproj import Transformer

from gpx_track import read_gpx_segments, project_gpx_segments, validate_line_thickness
from map_class import Map
from generate_map import generate_map
from generation_worker import run_generation
from generate_shapefile import generate_shapefile
from ui import ConfigEditor

ROOT = Path(__file__).resolve().parents[1]


class GpxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'track.gpx'

    def tearDown(self):
        self.temp.cleanup()

    def test_namespaces_and_segments(self):
        for namespace in ('', 'http://www.topografix.com/GPX/1/0', 'http://www.topografix.com/GPX/1/1'):
            self.path.write_text(f'''<gpx xmlns="{namespace}"><wpt lat="0" lon="0"/><trk>
            <trkseg><trkpt lat="46.1" lon="10.9"/><trkpt lat="46.2" lon="11"/></trkseg>
            <trkseg><trkpt lat="46.3" lon="11.1"/><trkpt lat="46.4" lon="11.2"/></trkseg>
            </trk></gpx>''')
            segments = read_gpx_segments(self.path)
            self.assertEqual(len(segments), 2)
            self.assertEqual(segments[0], [(10.9, 46.1), (11.0, 46.2)])
            projected = project_gpx_segments(segments, 'EPSG:25832')
            expected = Transformer.from_crs(4326, 25832, always_xy=True).transform(10.9, 46.1)
            self.assertEqual(projected[0][0], expected)

    def test_invalid_files_and_coordinates(self):
        for content in ('<gpx>', '<other/>', '<gpx/>',
                        '<gpx><rte><rtept lat="46" lon="11"/></rte></gpx>',
                        '<gpx><trk><trkseg><trkpt lat="46" lon="11"/></trkseg></trk></gpx>',
                        '<gpx><trk><trkseg><trkpt lat="nan" lon="11"/></trkseg></trk></gpx>',
                        '<gpx><trk><trkseg><trkpt lat="91" lon="11"/></trkseg></trk></gpx>',
                        '<gpx><trk><trkseg><trkpt lon="11"/></trkseg></trk></gpx>'):
            self.path.write_text(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                read_gpx_segments(self.path)
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, 'Cannot read GPX'):
            read_gpx_segments(self.path)

    def test_width_validation(self):
        for value in (0, -1, float('inf'), float('nan'), 'bad', None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_line_thickness(value)
        self.assertEqual(validate_line_thickness('2.5'), 2.5)

    def test_clipping_segment_separation_and_inversion(self):
        for inverted in (False, True):
            m = Map(scale=100, bounds=(0, 0, 10, 10),
                    bounding_shape=[(1, 1), (9, 1), (5, 9)], dpi=40, x_inverted=inverted)
            lines = m.draw_gps_tracks([[(-2, 5), (12, 5)], [(3, 2), (4, 2)]], 3.25)
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0].get_linewidth(), 3.25)
            self.assertEqual(lines[0].get_zorder(), 2.5)
            self.assertEqual(lines[0].get_color(), 'black')
            self.assertIsNotNone(lines[0].get_clip_path())
            self.assertEqual(list(lines[0].get_xdata()), [12, -2] if inverted else [-2, 12])
            m.canvas.draw()
            pixels = np.asarray(m.canvas.buffer_rgba())
            # The complete line crosses the polygon despite both endpoints being outside.
            self.assertLess(pixels[pixels.shape[0] // 2, pixels.shape[1] // 2, :3].mean(), 100)
            self.assertGreater(pixels[pixels.shape[0] // 2, 3, :3].mean(), 240)
            self.assertEqual(m.ax.get_xlim(), (0, 10))

    def test_bulk_keeps_the_same_gpx_overlay_settings(self):
        folder = Path(self.temp.name)
        (folder / 'a.shp').touch()
        (folder / 'b.shp').touch()
        config = {'use_bulk': True, 'input_folder': str(folder),
                  'gpx_file': 'inputs/track.gpx', 'gpx_line_thickness': 2.5,
                  'generate_map': True, 'output_folder': 'outputs'}
        snapshots = []
        def run(args, **kwargs):
            snapshots.append(yaml.safe_load(Path(args[-1]).read_text()))
            return Mock(returncode=0)
        with patch('generation_worker.subprocess.run', side_effect=run):
            result = run_generation(config, lambda _: None, root=folder)
        self.assertFalse(result['failures'])
        self.assertEqual(len(snapshots), 2)
        for snapshot in snapshots:
            self.assertEqual(snapshot['gpx_file'], 'inputs/track.gpx')
            self.assertEqual(snapshot['gpx_line_thickness'], 2.5)

    def test_offline_render_alias_and_empty_precedence(self):
        shp = Path(self.temp.name) / 'area.shp'
        generate_shapefile(11, 46.2, 25832, 100, None, 100000, str(shp), 'square')
        self.path.write_text('<gpx><trk><trkseg><trkpt lat="46.19" lon="10.99"/><trkpt lat="46.21" lon="11.01"/></trkseg></trk></gpx>')
        config = yaml.safe_load((ROOT / 'src/config/default_config.yaml').read_text())
        for key, value in config.items():
            if key.startswith('map_') and isinstance(value, bool):
                config[key] = False
        config.update(input_file=str(shp), output_folder=self.temp.name, aoi_name='Test', map_dpi=40)
        config.pop('gpx_file')
        config['gpxfile'] = str(self.path)
        with patch('generate_map.OpenStreetMapAPI') as api, patch.object(Map, 'draw_gps_tracks', autospec=True, wraps=Map.draw_gps_tracks) as draw:
            output = generate_map(config)
            self.assertTrue(Path(output).exists())
            draw.assert_called_once()
            self.assertEqual(len(draw.call_args.args[1][0]), 2)
            self.assertEqual(draw.call_args.kwargs['line_thickness'], 1.5)
            api.return_value.fetch_mountain_peaks_in_projected_coordinates.assert_not_called()
        config['gpx_file'] = ''
        with patch('generate_map.OpenStreetMapAPI'), patch.object(Map, 'draw_gps_tracks') as draw:
            generate_map(config)
            draw.assert_not_called()
        config['gpx_file'] = str(self.path.with_name('missing.gpx'))
        with patch('generate_map.OpenStreetMapAPI') as api, self.assertRaises(ValueError):
            generate_map(config)
        api.assert_not_called()


class GpxUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_loading_picker_save_and_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.yaml'
            path.write_text('gpxfile: old.gpx\ngenerate_map: true\n')
            window = ConfigEditor(folder)
            window.show_error = Mock()
            window.show_info = Mock()
            try:
                window.config_dropdown.setCurrentText('legacy.yaml')
                window.load_config()
                self.assertEqual(window.widgets['gpx_file'].text(), 'old.gpx')
                self.assertEqual(window.widgets['gpx_line_thickness'].text(), '1.5')
                with patch('ui.QFileDialog.getOpenFileName', return_value=(str(ROOT / 'inputs/new.gpx'), '')) as dialog:
                    window.browse_path('gpx_file')
                self.assertIn('*.gpx', dialog.call_args.args[3])
                window.widgets['gpx_line_thickness'].setText('2.75')
                window.save_config()
                config = yaml.safe_load(path.read_text())
                self.assertEqual(config['gpx_file'], 'inputs/new.gpx')
                self.assertEqual(config['gpx_line_thickness'], 2.75)
                for value in ('0', '-1', 'nan', 'inf', 'bad'):
                    window.widgets['gpx_line_thickness'].setText(value)
                    self.assertFalse(window.commit_fields())
                path.write_text("gpxfile: old.gpx\ngpx_file: ''\n")
                window.load_config()
                self.assertEqual(window.widgets['gpx_file'].text(), '')
                path.write_text('gpx_line_thickness: true\n')
                window.load_config()
                self.assertFalse(window.commit_fields())
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
