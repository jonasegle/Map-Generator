"""Overpass request counts, parsing, caching, retries, and refresh integration."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'map-generator-mpl'))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import requests
import yaml
from PySide6.QtWidgets import QApplication
from pyproj import Transformer
import osm_download as download
from openstreetmap_api import OpenStreetMapAPI
import generate_map as renderer
import generation_worker as worker
from generate_shapefile import generate_shapefile
from ui import ConfigEditor


def response(status=200, payload=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload or {'elements': []}).encode()
    result.headers.update(headers or {})
    return result


def fixture():
    def geometry(coords):
        return [dict(lon=x, lat=y) for x, y in coords]
    ring = geometry([(10.99,46.19),(11.01,46.19),(11.01,46.21),(10.99,46.21),(10.99,46.19)])
    hole = geometry([(10.995,46.195),(11.005,46.195),(11.005,46.205),(10.995,46.205),(10.995,46.195)])
    return {'elements': [
        {'type':'node','id':1,'lat':46.22,'lon':11.01,'tags':{'natural':'peak','name':'Peak','ele':'2500','place':'village'}},
        {'type':'way','id':2,'center':{'lat':46.18,'lon':10.98},'tags':{'tourism':'alpine_hut','name':'Hut','ele':'2000'}},
        {'type':'way','id':2,'geometry':ring,'tags':{'natural':'water','tourism':'alpine_hut','water':'lake','name':'Hut'}},
        {'type':'way','id':3,'geometry':ring[:3],'tags':{'highway':'path','name':'Path'}},
        {'type':'way','id':4,'geometry':ring[:3],'tags':{'railway':'rail'}},
        {'type':'way','id':5,'geometry':ring[:3],'tags':{'railway':'light_rail'}},
        {'type':'way','id':6,'geometry':ring[:3],'tags':{'waterway':'stream'}},
        {'type':'way','id':7,'geometry':ring,'tags':{'natural':'water'}},
        {'type':'relation','id':8,'tags':{'natural':'water','type':'multipolygon','water':'lake'},
         'members':[{'type':'way','ref':20,'role':'outer','geometry':ring},
                    {'type':'way','ref':21,'role':'inner','geometry':hole}]},
    ]}


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = Path(self.temp.name) / 'cache'
        self.api = OpenStreetMapAPI('EPSG:25832')
        self.api.cache_dir = self.cache
        self.config = yaml.safe_load((ROOT / 'src/config/default_config.yaml').read_text())
        self.bounds = (46.1, 10.9, 46.3, 11.1)
        self.api.session.post = Mock(return_value=response(payload=fixture()))

    def tearDown(self):
        self.api.session.close()
        self.temp.cleanup()

    def test_combined_features_centers_holes_and_request_counts(self):
        features = self.api.fetch_map_features(self.bounds, self.config)
        self.api.session.post.assert_called_once()
        self.assertEqual(set(features), set(download.FEATURES))
        self.assertEqual(len(features['huts']), 1)
        expected = Transformer.from_crs(4326,25832,always_xy=True).transform(10.98,46.18)
        self.assertEqual(features['huts'][0]['easting'], expected[0])
        self.assertEqual(len(features['peaks']), 1)
        self.assertEqual(len(features['settlements']), 1)
        self.assertEqual(len(features['water']), 3)
        self.assertEqual(len(features['water'][-1]['inners']), 1)
        query = self.api.session.post.call_args.kwargs['data']
        self.assertIn('[timeout:45]', query)
        self.assertIn('.points out body center;', query)
        self.assertIn('.geometry out body geom;', query)
        self.assertEqual(self.api.session.post.call_args.kwargs['timeout'], (10,60))
        config = {**self.config, 'map_font_size':12, 'map_dpi':600, 'gpx_line_thickness':3}
        self.api.fetch_map_features(self.bounds, config)
        self.assertEqual(self.api.session.post.call_count, 1)
        # Cache is geographic, so a different projection can reuse it.
        other = OpenStreetMapAPI('EPSG:32632'); other.cache_dir = self.cache
        other.session.post = Mock(side_effect=AssertionError('must use disk cache'))
        other.fetch_map_features(self.bounds, config)
        other.session.close()
        self.api.fetch_map_features(self.bounds, config, force_refresh=True)
        self.assertEqual(self.api.session.post.call_count, 2)

    def test_selection_filtering_and_no_features(self):
        config = {**self.config, 'map_light_rail':False, 'map_water_lake':False, 'map_path':False}
        features = self.api.fetch_map_features(self.bounds, config)
        self.assertEqual(len(features['railways']),1)
        self.assertFalse(features['water'])
        self.assertFalse(features['streets'])
        no_features = {key:False for key in download.TOGGLES.values()}
        self.api.session.post.reset_mock()
        self.api.fetch_map_features(self.bounds, no_features)
        self.api.session.post.assert_not_called()
        query = download.build_query(self.bounds, download.selections(config))
        self.assertNotIn('light_rail',query)
        self.assertNotIn('[!"water"]',query)

    def test_expiry_corruption_changed_query_and_disabled_cache(self):
        self.api.fetch_map_features(self.bounds,self.config)
        path = next(self.cache.glob('*.json'))
        entry = json.loads(path.read_text()); entry['fetched_at'] -= download.CACHE_TTL + 1
        path.write_text(json.dumps(entry))
        self.api.fetch_map_features(self.bounds,self.config)
        path.write_text('corrupted')
        self.api.fetch_map_features(self.bounds,self.config)
        self.api.fetch_map_features((46.0,10.9,46.3,11.1),self.config)
        self.api.fetch_map_features(self.bounds,{**self.config,'map_peaks':False})
        self.api.fetch_map_features(self.bounds,{**self.config,'osm_cache_enabled':False})
        self.assertEqual(self.api.session.post.call_count,6)

    def test_failed_refresh_and_atomic_write_keep_existing_cache(self):
        self.api.fetch_map_features(self.bounds,self.config)
        path = next(self.cache.glob('*.json')); original = path.read_bytes()
        self.api.session.post.return_value = response(payload={'elements':[], 'remark':'runtime error: timeout'})
        with self.assertRaisesRegex(ValueError,'partial'):
            self.api.fetch_map_features(self.bounds,self.config,force_refresh=True)
        self.assertEqual(path.read_bytes(), original)
        self.api.session.post.return_value = response(payload=fixture())
        with patch.object(download.os,'replace',side_effect=OSError('read only')):
            features = self.api.fetch_map_features(self.bounds,self.config,force_refresh=True)
        self.assertTrue(features['peaks'])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.cache.iterdir()),[path])

    def test_unwritable_cache_and_invalid_payload(self):
        blocked = Path(self.temp.name) / 'file'; blocked.touch()
        self.api.cache_dir = blocked
        self.assertTrue(self.api.fetch_map_features(self.bounds,self.config)['peaks'])
        for payload in ({'elements':{}}, {'elements':[{'type':'way'}]}, {'elements':[],'remark':'error'},
                        {'elements':[{'type':'node','id':1,'lat':float('nan'),'lon':11}]}):
            self.api.session.post.return_value = response(payload=payload)
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                self.api.fetch_map_features(self.bounds,self.config)
        self.api.session.post.return_value = response()
        self.api.session.post.return_value._content = b'not json'
        with self.assertRaises(ValueError):
            self.api.fetch_map_features(self.bounds,self.config)

    def test_public_hut_fetch_uses_centers_and_projected_rail_switches(self):
        self.api.session.post.return_value = response(payload={'elements':[fixture()['elements'][1]]})
        self.assertEqual(len(self.api.fetch_mountain_huts_in_projected_coordinates(self.bounds)),1)
        self.assertIn('out body center;', self.api.session.post.call_args.kwargs['data'])
        self.api.session.post.return_value = response(payload={'elements':[fixture()['elements'][3]]})
        self.api.fetch_railways_in_projected_coordinates(self.bounds, light_rail=False, narrow_gauge=False)
        query = self.api.session.post.call_args.kwargs['data']
        self.assertNotIn('light_rail',query)
        self.assertIn('^(rail)$',query)

    def test_duplicate_relation_retains_center_and_member_geometry(self):
        original = fixture()['elements'][-1]
        center = {'type':'relation','id':8,'center':{'lat':46.2,'lon':11},
                  'members':[{'type':'way','ref':20,'role':'outer'}]}
        for elements in ([original,center],[center,original]):
            merged = download.merge_elements(elements)[0]
            self.assertIn('geometry',merged['members'][0])
            self.assertIn('center',merged)


class RetryTests(unittest.TestCase):
    def test_no_adapter_retries(self):
        api = OpenStreetMapAPI()
        self.assertEqual(api.session.get_adapter(download.ENDPOINT).max_retries.total,0)
        api.session.close()

    @patch.object(download.time,'sleep')
    @patch.object(download.random,'random',return_value=0)
    def test_retry_counts_and_backoff(self,jitter,sleep):
        session = Mock()
        session.post.side_effect = [requests.ReadTimeout('read'),response(503),response()]
        self.assertEqual(download.post_overpass(session,'query').status_code,200)
        self.assertEqual(session.post.call_count,3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[2,4])
        session.post.reset_mock(); sleep.reset_mock()
        session.post.side_effect = [response(504)]*3
        with self.assertRaises(requests.HTTPError): download.post_overpass(session,'query')
        self.assertEqual(session.post.call_count,3)
        self.assertEqual(sleep.call_count,2)

    @patch.object(download.time,'sleep')
    def test_retry_after_and_permanent_failures(self,sleep):
        session = Mock()
        date = format_datetime(datetime.now(timezone.utc)+timedelta(seconds=30),usegmt=True)
        session.post.side_effect=[response(429,headers={'Retry-After':'3'}),response(503,headers={'Retry-After':date}),response()]
        download.post_overpass(session,'query')
        self.assertEqual(sleep.call_args_list[0].args[0],3)
        self.assertGreater(sleep.call_args_list[1].args[0],25)
        for status,headers in ((406,{}),(429,{'Retry-After':'120'})):
            session.post.reset_mock(); sleep.reset_mock()
            session.post.side_effect=None; session.post.return_value=response(status,headers=headers)
            with self.assertRaises(requests.HTTPError):download.post_overpass(session,'query')
            self.assertEqual(session.post.call_count,1)
            sleep.assert_not_called()


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_refresh_ui_default_snapshot_and_control_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'old.yaml';path.write_text('generate_map: true\n')
            window=ConfigEditor(folder); window.show_info=Mock();window.show_error=Mock()
            window.config_dropdown.setCurrentText('old.yaml');window.load_config()
            self.assertTrue(window.widgets['osm_cache_enabled'].isChecked())
            result={'outputs':['test.png'],'failures':[],'saved_input':None}
            with patch.object(worker,'run_generation',return_value=result) as run:
                window.refresh_osm_button.click()
                self.assertFalse(window.actions.isEnabled())
                deadline=time.monotonic()+5
                while window.running and time.monotonic()<deadline:
                    self.app.processEvents();time.sleep(.005)
                self.assertFalse(window.running)
                self.assertTrue(window.actions.isEnabled())
                self.assertTrue(run.call_args.kwargs['force_refresh'])
                self.assertNotIn('force_refresh',window.config_data)
            window.save_config()
            self.assertNotIn('force_refresh',yaml.safe_load(path.read_text()))
            window.close();window.deleteLater();self.app.processEvents()

    def test_worker_refresh_cli_flag_and_main_propagation(self):
        with tempfile.TemporaryDirectory() as folder:
            config={'input_file':'a.shp','generate_map':True}
            with patch.object(worker.subprocess,'run',return_value=Mock(returncode=0)) as run:
                worker.run_generation(config,root=Path(folder),force_refresh=True)
                self.assertIn('--refresh-osm',run.call_args.args[0])
            path=Path(folder)/'config.yaml';path.write_text(yaml.safe_dump(config))
            with patch.object(renderer,'generate_map') as render:
                renderer.main(str(path),refresh_osm=True)
                self.assertTrue(render.call_args.kwargs['force_refresh'])
            with patch.object(sys,'argv',['generate_map.py','--config',str(path),'--refresh-osm']):
                self.assertTrue(renderer.parse_arguments().refresh_osm)

    def test_offline_full_feature_map_one_request_then_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            shp=folder/'area.shp'
            generate_shapefile(11,46.2,25832,100,None,100000,str(shp),'square')
            config=yaml.safe_load((ROOT/'src/config/default_config.yaml').read_text())
            config.update(input_file=str(shp),output_folder=str(folder),map_dpi=40,map_logo=False,gpx_file='')
            api=OpenStreetMapAPI('EPSG:25832');api.cache_dir=folder/'cache'
            api.session.post=Mock(return_value=response(payload=fixture()))
            with patch.object(renderer,'OpenStreetMapAPI',return_value=api):
                output=renderer.generate_map(config)
                self.assertTrue(Path(output).is_file())
                renderer.generate_map(config)
                self.assertEqual(api.session.post.call_count,1)
                renderer.generate_map(config,force_refresh=True)
                self.assertEqual(api.session.post.call_count,2)


if __name__=='__main__':unittest.main()
