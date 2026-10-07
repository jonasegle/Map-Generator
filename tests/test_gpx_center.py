"""GPX bounds centering and the manual copy workflow."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication, QFormLayout
from pyproj import Transformer
import gpx_track
import ui


def write_track(path, segments):
    body = ''.join('<trkseg>' + ''.join(f'<trkpt lat="{lat}" lon="{lon}"/>' for lon, lat in points) + '</trkseg>' for points in segments)
    path.write_text(f'<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk>{body}</trk></gpx>')


class CenterCalculationTests(unittest.TestCase):
    def test_projected_center_includes_all_segments(self):
        segments = [[(10.8, 46.1), (10.9, 46.2)], [(11.0, 46.3), (11.2, 46.4)]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'track.gpx'
            write_track(path, segments)
            lat, lon = gpx_track.compute_gpx_center(path, 25832)
        projected = gpx_track.project_gpx_segments(segments, 25832)
        coords = [p for segment in projected for p in segment]
        expected_x = (min(p[0] for p in coords) + max(p[0] for p in coords)) / 2
        expected_y = (min(p[1] for p in coords) + max(p[1] for p in coords)) / 2
        x, y = Transformer.from_crs(4326, 25832, always_xy=True).transform(lon, lat)
        self.assertAlmostEqual(x, expected_x, places=5)
        self.assertAlmostEqual(y, expected_y, places=5)

    def test_automatic_utm_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'track.gpx'
            for lat, lon, etrs, expected in [(46, 11, True, 25832), (60, 5, False, 32632),
                                             (75, 15, False, 32633), (-30, 15, False, 32733)]:
                write_track(path, [[(lon-.01, lat-.01), (lon+.01, lat+.01)]])
                with patch.object(gpx_track, 'project_gpx_segments', wraps=gpx_track.project_gpx_segments) as project:
                    result = gpx_track.compute_gpx_center(path, prefer_etrs89=etrs)
                self.assertEqual(project.call_args.args[1], expected)
                self.assertAlmostEqual(result[0], lat, places=3)
                self.assertAlmostEqual(result[1], lon, places=3)


class CenterUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'track.gpx'
        write_track(self.path, [[(10.8, 46.1), (11.0, 46.2)]])
        (self.root / 'config.yaml').write_text("gpx_file: track.gpx\naoi_center_coords: '0, 0'\naoi_crs_epsg: ''\nscale: 50000\naoi_dimension1_mm: 100\n")
        self.window = ui.ConfigEditor(self.root)
        self.window.show_error = Mock()
        self.window.show_info = Mock()
        self.window.config_dropdown.setCurrentText('config.yaml')
        self.window.load_config()
        self.window.show()
        self.app.processEvents()
        self.root_patch = patch.object(ui, 'PROJECT_ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_button_layout_unsaved_edits_and_copy_without_configuration_changes(self):
        before = deepcopy(self.window.config_data)
        file_before = (self.root / 'config.yaml').read_text()
        self.window.widgets['aoi_crs_epsg'].setText('25832')
        self.window.widgets['scale'].setText('bad unsaved edit')
        self.window.gpx_center_button.click()
        expected = gpx_track.compute_gpx_center(self.path, 25832)
        result = self.window.gpx_center_result
        self.assertEqual(result.text(), f'{expected[0]:.8f}, {expected[1]:.8f}')
        self.assertTrue(result.isReadOnly())
        self.assertEqual(result.selectedText(), result.text())
        result.copy()
        self.assertEqual(self.app.clipboard().text(), result.text())
        self.assertEqual(self.window.config_data, before)
        self.assertEqual(self.window.widgets['aoi_center_coords'].text(), '0, 0')
        self.assertEqual((self.root / 'config.yaml').read_text(), file_before)
        self.assertNotIn('gpx_center_result', self.window.widgets)
        form = result.parentWidget().layout()
        self.assertIsInstance(form, QFormLayout)
        row = form.getWidgetPosition(self.window.widgets['gpx_file'].parentWidget())[0]
        self.assertEqual(form.getWidgetPosition(self.window.gpx_center_button)[0], row + 1)
        self.assertEqual(form.getWidgetPosition(result)[0], row + 2)

    def test_result_clearing_and_generation_disabling(self):
        self.window.gpx_center_button.click()
        self.assertTrue(self.window.gpx_center_result.text())
        self.window.widgets['aoi_crs_epsg'].setText('25832')
        self.assertFalse(self.window.gpx_center_result.text())
        self.window.gpx_center_button.click()
        self.window.widgets['gpx_file'].setText(str(self.path))
        self.assertFalse(self.window.gpx_center_result.text())
        self.window.gpx_center_button.click()
        self.window.load_config()
        self.assertFalse(self.window.gpx_center_result.text())
        self.window.set_running(True)
        self.assertFalse(self.window.gpx_center_button.isEnabled())
        self.assertFalse(self.window.gpx_center_result.isEnabled())
        self.window.set_running(False)

    def test_errors_clear_result_and_preserve_config(self):
        before = deepcopy(self.window.config_data)
        for filename, epsg in [('', ''), ('missing.gpx', ''), ('track.gpx', 'bad'), ('track.gpx', '-1')]:
            self.window.widgets['gpx_file'].setText(filename)
            self.window.widgets['aoi_crs_epsg'].setText(epsg)
            self.window.gpx_center_result.setText('stale result')
            self.window.gpx_center_button.click()
            self.assertFalse(self.window.gpx_center_result.text())
            self.window.show_error.assert_called()
            self.assertEqual(self.window.config_data, before)
        self.path.write_text('malformed XML')
        self.window.widgets['gpx_file'].setText('track.gpx')
        self.window.widgets['aoi_crs_epsg'].setText('')
        self.window.gpx_center_button.click()
        self.assertFalse(self.window.gpx_center_result.text())


if __name__ == '__main__':
    unittest.main()
