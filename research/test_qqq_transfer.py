"""Portable symbol-mapping and execution-equivalence checks without private data."""
import sys
import unittest

import numpy as np
import pandas as pd

from qqq_transfer import transfer_source, simulate, INITIAL, core, cs, portfolio
sys.path.insert(0,str(core.ROOT))
from test_moomoo import synthetic


class TransferTests(unittest.TestCase):
    def test_transfer_preserves_every_rule_and_target(self):
        data=synthetic()
        frames={'QQQ':data['QQQ'],'SMH':data['QQQ'].copy(),'SOXL':data['TQQQ'].copy()}
        code=cs.template(core.default_strategy(),core.baseline,'SMH')
        original=cs.evaluate(code,frames,audit=True)
        transferred=cs.evaluate(transfer_source(code),data,audit=True)
        expected=original.copy();expected['symbol']=expected.symbol.replace({'SMH':'QQQ','SOXL':'TQQQ'})
        pd.testing.assert_frame_equal(expected,transferred[expected.columns])
        self.assertFalse(transferred.rebalance_on_state_change.any())
        ledger=simulate(data,transferred)
        nav,_=portfolio.simulate(data,transferred,start=str(transferred.index[1].date()),initial=INITIAL)
        np.testing.assert_allclose(ledger[['equity','cash','fees']],nav[['equity','cash','fees']],rtol=1e-10,atol=1e-7)

    def test_rejects_wrong_source_market(self):
        code=cs.template(core.default_strategy(),core.baseline,'XSD')
        with self.assertRaises(ValueError):transfer_source(code)


if __name__=='__main__':unittest.main()
