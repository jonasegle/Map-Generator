"""Offscreen GUI and orchestration regression tests; no OSM requests."""
from copy import deepcopy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import yaml
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

import generate_shapefile as geometry
import generation_worker as generation
import ui


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.folder = Path(self.directory.name)
        self.config = yaml.safe_load((ROOT / 'src/config/default_config.yaml').read_text())
        self.config['custom_hidden'] = {'preserved': [1, 2]}
        (self.folder / 'default.yaml').write_text(yaml.safe_dump(self.config))
        self.window = ui.ConfigEditor(self.folder)
        self.window.show_error = Mock()
        self.window.show_info = Mock()
        self.window.config_dropdown.setCurrentText('default.yaml')
        self.window.load_config()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.window.thread is not None:
            deadline = time.monotonic() + 5
            while self.window.running and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def test_load_edit_and_save_preserve_types_and_hidden_fields(self):
        self.window.widgets['map_dpi'].setText('400')
        self.window.widgets['map_font_size'].setText('9')
        self.window.widgets['map_peak_label_padding_cm'].setText('0.25')
        self.window.widgets['map_water_color'].setText('0.75')
        self.window.widgets['map_peaks'].setChecked(False)
        # Save must read edits even when the text field still has focus.
        self.window.widgets['map_dpi'].setFocus()
        self.window.save_config()
        saved = yaml.safe_load((self.folder / 'default.yaml').read_text())
        self.assertEqual(saved['map_dpi'], 400)
        self.assertIs(type(saved['map_dpi']), int)
        self.assertIs(type(saved['map_peak_label_padding_cm']), float)
        self.assertIs(type(saved['map_water_color']), str)
        self.assertFalse(saved['map_peaks'])
        self.assertEqual(saved['custom_hidden'], self.config['custom_hidden'])

    def test_invalid_numeric_edits_do_not_save_or_generate(self):
        before = (self.folder / 'default.yaml').read_text()
        self.window.widgets['map_dpi'].setText('bad')
        self.window.save_config()
        self.window.generate_data()
        self.assertIsNone(self.window.thread)
        self.assertEqual((self.folder / 'default.yaml').read_text(), before)
        self.assertEqual(self.window.config_data['map_dpi'], self.config['map_dpi'])
        self.window.show_error.assert_called()

    def test_list_types_and_validation(self):
        with patch.dict(ui.PARAM_GROUPS, {'AOI Generation': ui.PARAM_GROUPS['AOI Generation'] + ['numbers']}):
            self.window.config_data['numbers'] = [1.0, 2.0]
            self.window.value_types['numbers'] = list
            self.window.display_config_params()
        self.window.widgets['numbers'].setText('[3, 4.5]')
        self.assertTrue(self.window.commit_fields())
        self.assertEqual(self.window.config_data['numbers'], [3.0, 4.5])
        self.assertIs(type(self.window.config_data['numbers'][0]), float)
        self.window.widgets['numbers'].setText('[bad, 4]')
        self.assertFalse(self.window.commit_fields())
        self.window.widgets['numbers'].setText('not a list')
        self.assertFalse(self.window.commit_fields())

    def test_conditional_fields(self):
        self.assertFalse(self.window.widgets['input_folder'].isEnabled())
        self.window.widgets['use_bulk'].setChecked(True)
        self.assertTrue(self.window.widgets['input_folder'].isEnabled())
        shape = self.window.widgets['aoi_shape_type']
        for name, label in [('rectangle', 'width'), ('circle', 'radius'), ('square', 'side'), ('hexagon', 'inner radius')]:
            shape.setCurrentText(name)
            self.assertEqual(self.window.widgets['aoi_dimension2_mm'].isEnabled(), name == 'rectangle')
            self.assertIn(label, self.window.dimension_labels['aoi_dimension1_mm'].text())

    def test_height_scale_conditional_for_custom_configs(self):
        with patch.dict(ui.PARAM_GROUPS, {'AOI Generation': ui.PARAM_GROUPS['AOI Generation'] + ['height_scale', 'variable_base_height']}):
            self.window.config_data.update(height_scale=2.0, variable_base_height=False)
            self.window.display_config_params()
        self.assertFalse(self.window.widgets['height_scale'].isEnabled())
        self.window.widgets['variable_base_height'].setChecked(True)
        self.assertTrue(self.window.widgets['height_scale'].isEnabled())

    def test_save_as_and_cancel(self):
        with patch.object(ui.QInputDialog, 'getText', return_value=('new', True)):
            self.window.open_save_dialog()
        self.assertTrue((self.folder / 'new.yaml').exists())
        self.assertEqual(self.window.config_dropdown.currentText(), 'new.yaml')
        with patch.object(ui.QInputDialog, 'getText', return_value=('cancelled', False)):
            self.window.open_save_dialog()
        self.assertFalse((self.folder / 'cancelled.yaml').exists())

    def test_file_dialog_paths_and_cancellation(self):
        entry = self.window.widgets['input_file']
        with patch.object(ui.QFileDialog, 'getOpenFileName', return_value=(str(ROOT / 'inputs/example.shp'), '')):
            self.window.browse_path('input_file')
        self.assertEqual(entry.text(), 'inputs/example.shp')
        with patch.object(ui.QFileDialog, 'getOpenFileName', return_value=('', '')):
            self.window.browse_path('input_file')
        self.assertEqual(entry.text(), 'inputs/example.shp')
        with patch.object(ui.QFileDialog, 'getExistingDirectory', return_value=self.directory.name):
            self.window.browse_path('output_folder')
        self.assertEqual(self.window.widgets['output_folder'].text(), self.directory.name)

    def test_malformed_yaml_keeps_loaded_configuration(self):
        (self.folder / 'bad.yaml').write_text('- invalid mapping')
        self.window.load_config_files()
        self.window.config_dropdown.setCurrentText('bad.yaml')
        self.window.load_config()
        self.assertEqual(self.window.config_dropdown.currentText(), 'default.yaml')
        self.assertEqual(self.window.config_data, self.config)

    def test_background_responsiveness_duplicate_run_and_recovery(self):
        calls = []
        def slow_run(config, status):
            calls.append(deepcopy(config))
            status('Working')
            time.sleep(.15)
            return {'outputs': ['/tmp/map.png'], 'failures': [], 'saved_input': 'inputs/saved.shp'}
        beats = []
        timer = QTimer()
        timer.timeout.connect(lambda: beats.append(True))
        timer.start(5)
        with patch.object(generation, 'run_generation', side_effect=slow_run):
            self.window.widgets['map_dpi'].setText('450')
            self.window.generate_data()
            self.window.generate_data()
            self.assertFalse(self.window.actions.isEnabled())
            close_event = QCloseEvent()
            self.window.closeEvent(close_event)
            self.assertFalse(close_event.isAccepted())
            deadline = time.monotonic() + 5
            while self.window.running and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
        timer.stop()
        self.assertFalse(self.window.running)
        self.assertTrue(self.window.actions.isEnabled())
        self.assertGreater(len(beats), 3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['map_dpi'], 450)
        self.assertEqual(self.window.widgets['input_file'].text(), 'inputs/saved.shp')

    def test_background_failure_recovers_controls(self):
        with patch.object(generation, 'run_generation', side_effect=ValueError('preparation failed')):
            self.window.generate_data()
            deadline = time.monotonic() + 5
            while self.window.running and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.005)
        self.assertFalse(self.window.running)
        self.assertTrue(self.window.header.isEnabled())
        self.window.show_error.assert_called_with('Generation failed', 'preparation failed')


class StandaloneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = geometry.create_shapefile_window()
        self.window.show()
        self.window.coords.setText('47.4, 11.0')
        self.window.dimension1.setText('100')
        self.window.dimension2.setText('50')

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_shapes_and_cancel(self):
        for shape in ('circle', 'square', 'rectangle', 'hexagon'):
            self.window.shape.setCurrentText(shape)
            self.assertEqual(self.window.dimension2.isHidden(), shape != 'rectangle')
        with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', return_value=('', '')), patch.object(geometry, 'generate_shapefile') as generate:
            self.window.submit()
        generate.assert_not_called()
        self.assertTrue(self.window.isVisible())

    def test_generate_actual_shapefile_and_geojson(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = str(Path(folder) / 'rectangle')
            self.window.shape.setCurrentText('rectangle')
            self.window.geojson.setChecked(True)
            with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', return_value=(filename, '')), patch('PySide6.QtWidgets.QMessageBox.information'):
                self.window.submit()
            for extension in ('.shp', '.shx', '.dbf', '.prj', '.geojson'):
                self.assertTrue(Path(filename + extension).exists())
            self.assertFalse(self.window.isVisible())

    def test_geometry_import_does_not_import_qt(self):
        code = "import sys; import generate_shapefile; assert not any(n.startswith('PySide6') for n in sys.modules)"
        subprocess.run([sys.executable, '-c', code], env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}, check=True)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / 'inputs').mkdir()
        self.config = {'input_file': 'inputs/source.shp', 'generate_map': True, 'output_folder': 'outputs',
                       'aoi_name': 'Area', 'map_filename': 'map.png', 'use_bulk': False}

    def tearDown(self):
        self.directory.cleanup()

    def test_single_snapshot_paths_and_cleanup(self):
        snapshots, configs = [], []
        before = deepcopy(self.config)
        def run(args, **kwargs):
            configs.append(Path(args[-1]))
            snapshots.append(yaml.safe_load(configs[-1].read_text()))
            self.assertEqual(kwargs['cwd'], str(self.root))
            self.assertEqual(args[1], str(self.root / 'src/generate_map.py'))
            return Mock(returncode=0)
        with patch.object(generation.subprocess, 'run', side_effect=run):
            result = generation.run_generation(self.config, lambda _: None, self.root)
        self.assertEqual(result['outputs'], [str((self.root / 'outputs/Area/map.png').resolve())])
        self.assertEqual(self.config, before)
        self.assertEqual(snapshots[0]['input_file'], str(self.root / 'inputs/source.shp'))
        self.assertFalse(configs[0].exists())
        self.assertFalse(configs[0].parent.exists())

    def test_bulk_continues_after_failures_without_changing_editor_config(self):
        for name in ('a.shp', 'b.geojson', 'c.shp'):
            (self.root / 'inputs' / name).touch()
        self.config.update(use_bulk=True, input_folder='inputs')
        before = deepcopy(self.config)
        snapshots, configs = [], []
        def run(args, **kwargs):
            path = Path(args[-1]); configs.append(path)
            snapshots.append(yaml.safe_load(path.read_text()))
            return Mock(returncode=1 if len(snapshots) == 1 else 0)
        with patch.object(generation.subprocess, 'run', side_effect=run):
            result = generation.run_generation(self.config, lambda _: None, self.root)
        self.assertEqual(len(result['failures']), 1)
        self.assertEqual(len(result['outputs']), 2)
        self.assertEqual([c['map_filename'] for c in snapshots], ['a_map.png', 'b_map.png', 'c_map.png'])
        self.assertTrue(all(not c['use_bulk'] for c in snapshots))
        self.assertEqual(self.config, before)
        self.assertTrue(all(not p.exists() for p in configs))

    def test_subprocess_exception_cleans_up(self):
        paths = []
        def fail(args, **kwargs):
            paths.append(Path(args[-1])); raise OSError('cannot start')
        with patch.object(generation.subprocess, 'run', side_effect=fail):
            result = generation.run_generation(self.config, lambda _: None, self.root)
        self.assertIn('cannot start', result['failures'][0])
        self.assertFalse(paths[0].parent.exists())

    def test_aoi_export_saved_and_temporary_cleanup(self):
        self.config.update(input_file='', generate_aoi=True, aoi_center_coords='47.4, 11.0',
                           aoi_dimension1_mm=20, scale=100000, aoi_shape_type='hexagon',
                           save_generated_shapefile=True, save_geojson=True)
        with patch.object(generation.subprocess, 'run', return_value=Mock(returncode=0)):
            result = generation.run_generation(self.config, lambda _: None, self.root)
        self.assertEqual(result['saved_input'], 'inputs/Area.shp')
        self.assertTrue((self.root / 'inputs/Area.shp').exists())
        self.assertTrue((self.root / 'outputs/Area/Area.geojson').exists())
        self.config['save_generated_shapefile'] = False
        paths = []
        def run(args, **kwargs):
            item = yaml.safe_load(Path(args[-1]).read_text())
            paths.append(Path(item['input_file']))
            self.assertTrue(paths[-1].exists())
            return Mock(returncode=2)
        with patch.object(generation.subprocess, 'run', side_effect=run):
            result = generation.run_generation(self.config, lambda _: None, self.root)
        self.assertIsNone(result['saved_input'])
        self.assertEqual(len(result['failures']), 1)
        self.assertFalse(paths[0].parent.exists())
        self.assertTrue((self.root / 'inputs/Area.shp').exists())

    def test_preparation_failure_cleans_partial_files(self):
        self.config.update(input_file='', generate_aoi=True)
        scratch_dirs = []
        def fail(config, scratch, root):
            scratch_dirs.append(Path(scratch))
            (Path(scratch) / 'partial.shp').touch()
            raise ValueError('bad coordinates')
        with patch.object(generation, 'prepare_aoi', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'bad coordinates'):
                generation.run_generation(self.config, lambda _: None, self.root)
        self.assertFalse(scratch_dirs[0].exists())

    def test_empty_bulk_folder_reports_error(self):
        self.config.update(use_bulk=True, input_folder='inputs')
        with self.assertRaisesRegex(ValueError, 'No shapefiles'):
            generation.run_generation(self.config, lambda _: None, self.root)


if __name__ == '__main__':
    unittest.main()
