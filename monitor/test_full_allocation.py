"""Target-only edits, atomic local version migration and fee-safe full exposure."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import core
import full_allocation as full
import performance
import portfolio


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=patch.object(core,'DB',self.root/'monitor.db');self.runtime=patch.object(core,'RUNTIME',self.root)
        self.db.start();self.runtime.start();core.init_db()

    def tearDown(self):
        self.db.stop();self.runtime.stop();self.temp.cleanup()

    def test_target_edits_leave_price_and_threshold_literals_unchanged(self):
        source="""import pandas as pd
PARAMETERS = {'attack': .99, 'high_zone': .99}
STATE_LABELS = {'ATTACK': '进攻'}
STATE_NOTES = {'ATTACK': '目标TQQQ99%、现金1%。'}
BASE_SYMBOL = 'QQQ'
def generate_signals(frames, start='2017-01-02'):
    price = frames['QQQ'].close * .99
    wt = .99
    return price
"""
        updated=full.upgrade_source(source)
        self.assertIn("'attack': 1.0",updated);self.assertIn("'high_zone': .99",updated)
        self.assertIn('close * .99',updated);self.assertIn('wt = 1.0',updated)
        self.assertIn('TQQQ100%、现金0%',updated);self.assertEqual(full.upgrade_source(updated),updated)

    def seed_old_default(self):
        old=core.default_strategy();old['revision']=1;old['parameters']['attack']=.99
        old['fingerprint']=core.strategy_fingerprint(old)
        with core.connect() as db:
            db.execute('DELETE FROM strategy_versions')
            db.execute('INSERT INTO strategy_versions VALUES (?,?,?)',('default',1,core.json_dump(old)))
            db.execute('UPDATE strategy_profiles SET revision=1,payload=? WHERE id=?',(core.json_dump(old),'default'))
        core.put('active_strategy',old);core.put('snapshot',{'last':{'date':'2026-10-02'},'source':'fixture'})
        core.put('confirmed_bundle',{})
        return old

    def replay(self,frames,profile,**kwargs):
        return pd.DataFrame({'state':['NORMAL_ATTACK'],'symbol':['SOXL'],'regime':['BULL'],
            'weight':[profile['parameters']['attack']]},index=pd.to_datetime(['2026-10-02']))

    def test_versions_active_snapshot_and_repeat_run(self):
        old=self.seed_old_default()
        with patch.object(core,'ensure_strategy_bundle',return_value={}),patch.object(core,'load_bundle',return_value={}),patch.object(core,'replay',side_effect=self.replay),patch.object(core,'pack',side_effect=lambda f,s,src,*args:{'last':{'date':'2026-10-02','weight':float(s.weight.iloc[-1])},'source':src}):
            result=full.upgrade_existing();self.assertEqual(len(result),1)
            self.assertEqual(core.strategy_version('default',1),old)
            self.assertEqual(core.active_strategy()['revision'],2)
            self.assertEqual(core.get('snapshot')['last']['weight'],1.)
            self.assertEqual(full.upgrade_existing(),[])
        self.assertEqual(len(core.strategy_history('default')),2)

    def test_validation_failure_leaves_versions_and_active_untouched(self):
        old=self.seed_old_default();before=core.get('snapshot')
        def bad(frames,profile,**kwargs):
            result=self.replay(frames,profile)
            if profile['parameters']['attack']==1.:result['state']='CHANGED_RULE'
            return result
        with patch.object(core,'ensure_strategy_bundle',return_value={}),patch.object(core,'load_bundle',return_value={}),patch.object(core,'replay',side_effect=bad):
            with self.assertRaises(AssertionError):full.upgrade_existing()
        self.assertEqual(core.active_strategy(),old);self.assertEqual(core.get('snapshot'),before)
        self.assertEqual(len(core.strategy_history('default')),1)

    def test_full_allocation_deducts_fees_without_negative_cash(self):
        after,holding,fee,_=performance.engine.rebalance(10000.,0.,False,1.,.001)
        self.assertAlmostEqual(holding,10000./1.001);self.assertEqual(after-holding,0.)
        self.assertAlmostEqual(after+fee,10000.)
        index=pd.to_datetime(['2017-01-02','2017-01-03','2017-01-04'])
        frame=pd.DataFrame({'adj_open':100.,'adj_close':100.},index=index)
        sig=pd.DataFrame({'symbol':'TQQQ','weight':1.,'weight_QQQ':0.,'weight_TQQQ':1.,
            'state':'ATTACK','rebalance_band':0.},index=index)
        nav,orders=portfolio.simulate({'QQQ':frame,'TQQQ':frame},sig,start='2017-01-03',initial=10000.,cost_bps=10.)
        self.assertTrue((nav.cash>=-1e-8).all());self.assertAlmostEqual(nav.equity.iloc[-1]+orders.fee.sum(),10000.)


if __name__=='__main__':unittest.main()
