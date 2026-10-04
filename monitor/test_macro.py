"""Portable tests for source failures, risk semantics and dashboard display."""
from pathlib import Path
import copy
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import core
import macro_sources as sources
import macro_ui


class MacroTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=patch.object(core,'DB',self.root/'monitor.db');self.runtime=patch.object(core,'RUNTIME',self.root)
        self.db.start();self.runtime.start();core.init_db()

    def tearDown(self):
        self.db.stop();self.runtime.stop();self.temp.cleanup()

    def fixture(self):
        index=core.calendar(2026).sessions_in_range('2025-08-01','2026-10-02');n=len(index)
        q=pd.Series(np.linspace(600,300,n),index=index)
        t=pd.DataFrame({'yield2':4.,'yield10':np.linspace(2,10,n),'real10':np.linspace(0,7,n)},index=index)
        o=pd.DataFrame({'wti':50*np.exp(np.arange(n)*.008)},index=index)
        p=pd.DataFrame({'target_upper':np.linspace(1,6,n)},index=index)
        ix=pd.DatetimeIndex(pd.Series(index,index=index).groupby(index.to_period('M')).first().iloc[-7:])
        c=pd.DataFrame({'headline':[2.,2.2,2.5,2.8,3.,3.3,3.6],'core':[2.,2.2,2.4,2.7,3.,3.2,3.4]},index=ix)
        at=pd.Timestamp('2026-10-04T04:00:00Z');cache={}
        for name,frame in [('rates',t),('oil',o),('policy',p)]:
            rows=frame.copy();rows['date']=rows.index.strftime('%Y-%m-%d')
            cache[name]={'observations':rows.to_dict('records'),'fetched':at.isoformat(),'last_error':None}
        cache['cpi']={'observations':[{'month':str((date.to_period('M')-1)),**row.to_dict()} for date,row in c.iterrows()],
            'release_dates':{str(date.to_period('M')-1):str(date.date()) for date in c.index},'fetched':at.isoformat(),'last_error':None}
        return at,q,t,o,p,c,cache

    def test_matches_predeclared_research_flags(self):
        at,q,t,o,p,c,cache=self.fixture()
        spec=importlib.util.spec_from_file_location('research_macro_rules',core.ROOT.parent/'research'/'macro_rules.py')
        rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)
        expected=rules.features(q.index,q,t,o,p,c).iloc[-1]
        actual=macro_ui.build_panel(cache,q.tail(180),at)
        for name in macro_ui.GROUP_NAMES:self.assertEqual(actual['groups'][name],bool(expected[name]))
        self.assertEqual(actual['lower'],int(expected['score']));self.assertEqual(actual['upper'],int(expected['score']))
        for row,key in zip(actual['rows'],['rate_jump','real_jump','curve_stress','oil_spike','oil_crash','tightening','emergency_cut','cpi_heat','cpi_jump']):
            self.assertEqual(row['触发'],'触发' if bool(expected[key]) else '未触发')

    def test_unknown_release_and_stale_sources_are_not_zero_risk(self):
        at,q,t,o,p,c,cache=self.fixture();cache['cpi']['release_dates']={}
        cache['rates']['fetched']='2026-09-01T00:00:00Z'
        panel=macro_ui.build_panel(cache,q,at)
        self.assertIsNone(panel['groups']['cpi']);self.assertIsNone(panel['groups']['rates'])
        self.assertEqual(panel['upper']-panel['lower'],2);self.assertTrue(panel['notes'])
        self.assertIn('缓存过期',[r['状态'] for r in panel['sources']])

    def test_cpi_after_confirmed_close_does_not_enter_earlier_risk(self):
        at,q,t,o,p,c,cache=self.fixture();latest=cache['cpi']['observations'][-1]['month']
        cache['cpi']['release_dates'][latest]='2026-10-05'
        panel=macro_ui.build_panel(cache,q,at)
        self.assertLess(panel['values']['cpi']['month'],latest);self.assertTrue(panel['notes'])

    def test_negative_oil_never_signals_artificial_spike(self):
        at,q,t,o,p,c,cache=self.fixture()
        for row in cache['oil']['observations'][-10:]:row['wti']=-36.98
        panel=macro_ui.build_panel(cache,q,at)
        self.assertEqual(panel['rows'][3]['触发'],'未触发');self.assertEqual(panel['rows'][4]['触发'],'触发')

    def test_refresh_preserves_failed_source_and_strategy(self):
        at,q,t,o,p,c,cache=self.fixture()
        old=copy.deepcopy(cache);core.put('macro_sources',cache);before=core.active_strategy()['fingerprint']
        fetchers={name:(lambda at,previous,name=name:copy.deepcopy(old[name])) for name in sources.SOURCES}
        def fail(at,previous):raise ConnectionError('sensitive proxy address')
        fetchers['oil']=fail
        with patch.dict(sources.FETCHERS,fetchers):new=sources.refresh(force=True,at=at+pd.Timedelta(minutes=2))
        self.assertEqual(new['oil']['observations'],old['oil']['observations'])
        self.assertEqual(new['oil']['fetched'],old['oil']['fetched']);self.assertIn('ConnectionError',new['oil']['last_error']['message'])
        self.assertNotIn('sensitive',json.dumps(new));self.assertIsNone(new['rates']['last_error'])
        self.assertEqual(before,core.active_strategy()['fingerprint']);self.assertIsNone(core.get('snapshot'))
        # Repeated clicks within a minute do not spend additional BLS quota.
        with patch.dict(sources.FETCHERS,{name:lambda *args:(_ for _ in ()).throw(AssertionError('unexpected fetch')) for name in sources.SOURCES}):
            sources.refresh(force=True,at=at+pd.Timedelta(minutes=2,seconds=20))

    def test_validation_and_calendar_parser(self):
        text='<table><tr><td>August 2026</td><td>Sep. 11, 2026</td><td>08:30 AM</td></tr></table>'
        self.assertEqual(sources.release_calendar(text),{'2026-08':'2026-09-11'})
        with self.assertRaises(ValueError):sources.release_calendar('<p>Access denied</p>')
        rows=[{'date':f'2026-09-{day:02d}','wti':50.} for day in range(1,5)]
        rows[-1]['wti']=float('nan')
        with self.assertRaises(ValueError):sources.validate('oil',{'observations':rows},pd.Timestamp('2026-10-04T00:00:00Z'))

    def test_verified_date_only_updates_metadata_and_rejects_future(self):
        at,q,t,o,p,c,cache=self.fixture();core.put('macro_sources',cache)
        month=cache['cpi']['observations'][-1]['month'];before=core.active_strategy()['fingerprint']
        with self.assertRaises(ValueError):sources.save_release_date(month,'2026-10-05',at)
        sources.save_release_date(month,'2026-10-01',at)
        self.assertEqual(core.get('macro_sources')['cpi']['observations'],cache['cpi']['observations'])
        self.assertEqual(core.get('macro_sources')['cpi']['release_dates'][month],'2026-10-01')
        self.assertEqual(before,core.active_strategy()['fingerprint'])

    def test_service_updates_macro_even_when_etf_refresh_fails(self):
        import service
        core.put('snapshot',{'last':{'date':'2026-10-02'},'source':'Yahoo 公开日线'})
        with patch('sys.argv',['service','--once']),patch.object(core,'bootstrap'),patch.object(core,'record_failure'),patch.object(core,'refresh_full',side_effect=RuntimeError('ETF unavailable')),patch.object(sources,'refresh',return_value={}) as macro:
            service.main()
        macro.assert_called_once_with(force=True)

    def test_streamlit_panel_is_read_only_and_renders_failures(self):
        from streamlit.testing.v1 import AppTest
        at,q,t,o,p,c,cache=self.fixture();cache['oil']['last_error']={'message':'WTI更新失败：ConnectionError'}
        core.put('macro_sources',cache);core.put('snapshot',{'last':{'date':'2026-10-02'}});before=core.active_strategy()['fingerprint']
        app="import macro_ui\nmacro_ui.render()"
        with patch.object(macro_ui,'qqq_prices',return_value=q),patch.object(core,'now_utc',return_value=at.to_pydatetime()):
            page=AppTest.from_string(app).run()
        self.assertEqual(len(page.exception),0);self.assertEqual(len(page.metric),4);self.assertEqual(len(page.dataframe),2)
        self.assertTrue(any('WTI更新失败' in row.value for row in page.warning));self.assertEqual(before,core.active_strategy()['fingerprint'])
        cache['cpi']['release_dates']={};core.put('macro_sources',cache)
        with patch.object(macro_ui,'qqq_prices',return_value=q),patch.object(core,'now_utc',return_value=at.to_pydatetime()):
            page=AppTest.from_string(app).run();self.assertEqual(len(page.date_input),1)
            save=next(b for b in page.button if b.label=='保存已核对的公告日期')
            save.click().run();self.assertTrue(any('请先填写' in r.value for r in page.error))
            page.date_input[0].set_value(pd.Timestamp('2026-10-01').date())
            next(b for b in page.button if b.label=='保存已核对的公告日期').click().run()
            self.assertEqual(len(page.exception),0)
            month=cache['cpi']['observations'][-1]['month']
            self.assertEqual(core.get('macro_sources')['cpi']['release_dates'].get(month),'2026-10-01',[r.value for r in page.error])
            self.assertEqual(len(page.date_input),0)
        self.assertEqual(before,core.active_strategy()['fingerprint'])


if __name__=='__main__':unittest.main()
