"""Calendar and retry checks; no network, orders or backtests."""
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import core
import close_refresh as jobs


class CloseRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.db=patch.object(core,'DB',root/'monitor.db');self.runtime=patch.object(core,'RUNTIME',root)
        self.db.start();self.runtime.start();core.init_db()
        self.at=pd.Timestamp('2026-10-05T20:20:00Z')
        self.logger=logging.getLogger('test-close-refresh');self.logger.disabled=True

    def tearDown(self):
        self.db.stop();self.runtime.stop();self.temp.cleanup()

    def test_exact_boundary_and_dst(self):
        self.assertEqual(jobs.schedule(self.at-pd.Timedelta(seconds=1))['session'],'2026-10-02')
        self.assertEqual(jobs.schedule(self.at)['session'],'2026-10-05')
        self.assertEqual(pd.Timestamp(jobs.schedule(self.at)['due_at']).tz_convert('Asia/Shanghai').hour,4)
        winter=jobs.schedule(pd.Timestamp('2026-01-06T21:20:00Z'))
        self.assertEqual(pd.Timestamp(winter['due_at']).tz_convert('Asia/Shanghai').hour,5)
        with self.assertRaises(ValueError):jobs.schedule(pd.Timestamp('2026-10-05'))

    def test_holidays_early_close_and_weekend(self):
        holiday=jobs.schedule(pd.Timestamp('2026-11-26T22:00:00Z'))
        self.assertEqual(holiday['session'],'2026-11-25')
        self.assertEqual(pd.Timestamp(holiday['next_at']),pd.Timestamp('2026-11-27T18:20:00Z'))
        weekend=jobs.schedule(pd.Timestamp('2026-11-28T22:00:00Z'))
        self.assertEqual(weekend['session'],'2026-11-27')
        self.assertEqual(pd.Timestamp(weekend['next_at']),pd.Timestamp('2026-11-30T21:20:00Z'))

    def test_persisted_completion_and_restart_catchup(self):
        plan=jobs.pending(self.at);self.assertIsNotNone(plan)
        core.put(jobs.KEY,{**plan,'status':'complete'})
        self.assertIsNone(jobs.pending(self.at+pd.Timedelta(hours=5)))
        self.assertEqual(jobs.pending(pd.Timestamp('2026-10-07T08:00:00Z'))['session'],'2026-10-06')
        # A newer strategy cannot reuse another profile's completed job.
        state=core.get(jobs.KEY);state['fingerprint']='old';core.put(jobs.KEY,state)
        self.assertIsNotNone(jobs.pending(self.at))

    def execute(self,daily_error=False,source_error=False):
        plan=jobs.schedule(self.at)
        snap={'last':{'date':plan['session']},'source':'Yahoo 公开日线','quotes':{}}
        macro={name:{'last_error':None} for name in jobs.macro_sources.SOURCES}
        factors={name:{'last_error':None} for name in ('RSP','SPY','SMH','XSD','OFR','FactSet')}
        if source_error:factors['OFR']['last_error']='temporary'
        with patch.object(core,'now_utc',return_value=self.at.to_pydatetime()),patch.object(core,'refresh_full',return_value=snap,side_effect=RuntimeError('unavailable') if daily_error else None),patch.object(jobs.macro_sources,'refresh',return_value=macro) as m,patch.object(jobs.market_factors,'refresh',return_value=factors) as f:
            result=jobs.run(plan,self.logger)
        m.assert_called_once_with(force=True);f.assert_called_once_with(force=True)
        return result

    def test_whole_panel_completion_without_strategy_change(self):
        before=core.active_strategy()['fingerprint'];core.put('snapshot',{'private':'unchanged'})
        result=self.execute();self.assertEqual(result['status'],'complete')
        self.assertEqual(len(result['parts']),3);self.assertIsNone(result['retry_at'])
        self.assertIsNone(jobs.pending(self.at+pd.Timedelta(minutes=1)))
        self.assertEqual(before,core.active_strategy()['fingerprint'])
        self.assertEqual(core.get('snapshot'),{'private':'unchanged'})

    def test_failure_still_checks_independent_sources_and_retries(self):
        result=self.execute(daily_error=True);self.assertEqual(result['status'],'retry')
        self.assertIsNone(jobs.pending(self.at+pd.Timedelta(minutes=4,seconds=59)))
        self.assertIsNotNone(jobs.pending(self.at+pd.Timedelta(minutes=5)))
        result=self.execute(source_error=True);self.assertEqual(result['attempts'],2)
        self.assertEqual(result['parts']['六项参考指标'],'部分失败')
        self.assertNotIn('completed',result)

    def test_background_dispatch_and_ui(self):
        import service
        from streamlit.testing.v1 import AppTest
        plan=jobs.schedule(self.at);snap={'last':{'date':plan['session']},'source':'Yahoo 公开日线'}
        core.put('snapshot',snap);core.put('validated_session',plan['session'])
        with patch('sys.argv',['service']),patch.object(core,'bootstrap'),patch.object(core,'market_clock',return_value={'expected_date':plan['session'],'now':self.at.isoformat(),'is_open':False}),patch.object(jobs,'pending',return_value=plan),patch.object(jobs,'run') as run,patch.object(service.time,'sleep',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):service.main()
        run.assert_called_once()
        self.execute()
        with patch.object(core,'now_utc',return_value=self.at.to_pydatetime()):
            page=AppTest.from_string('import close_refresh\nclose_refresh.render()').run()
        self.assertEqual(len(page.exception),0)
        self.assertIn('已完成',page.info[0].value)
        self.assertTrue(any('收盘20分钟后' in x.value for x in page.caption))


if __name__=='__main__':unittest.main()
