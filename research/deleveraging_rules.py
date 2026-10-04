"""Causal SOXL risk overlays. Base strategy and its cash locks stay independent."""
import numpy as np
import pandas as pd


def risk_features(frames, vol_days=20, trend_days=50, recovery_days=3):
    if vol_days not in (10,20,40) or trend_days not in (20,50,100) or recovery_days not in (1,3,5):
        raise ValueError('Unsupported fixed research period')
    smh=frames['SMH'].close
    qqq=frames['QQQ'].close.reindex(smh.index)
    rv=frames['SOXL'].adj_close.pct_change().rolling(vol_days).std(ddof=1)*np.sqrt(252)
    rv_smh=frames['SMH'].adj_close.pct_change().rolling(20).std(ddof=1)*np.sqrt(252)
    slow=frames['SMH'].adj_close.pct_change().rolling(60).std(ddof=1)*np.sqrt(252)
    ma=smh.rolling(trend_days).mean()
    qm=qqq.rolling(trend_days).mean()
    ema=smh.ewm(span=20,adjust=False).mean()
    dif=smh.ewm(span=12,adjust=False).mean()-smh.ewm(span=26,adjust=False).mean()
    hist=dif-dif.ewm(span=9,adjust=False).mean()
    above=smh.ge(ema)
    streak=above.astype(int).groupby((~above).cumsum()).cumsum()
    healthy=(above & ema.gt(ema.shift(3)) & hist.ge(0) & streak.ge(recovery_days) & rv_smh.le(slow*1.1))
    trend_bad=(smh.lt(ma)&ma.lt(ma.shift(5))) | (smh.lt(ma)&qqq.lt(qm)&qm.lt(qm.shift(5)))
    return pd.DataFrame({'risk_soxl_vol':rv,'risk_smh_vol_ratio':rv_smh/slow,
                         'risk_trend_bad':trend_bad,'risk_healthy':healthy,'risk_macd_hist':hist,
                         'risk_above_ema_streak':streak},index=smh.index)


def apply_deleveraging(signals, features, rules):
    """Never changes a SMH/CASH base target or releases the MACD cash lock.

    Weight caps apply when the next-open order executes. Five-point rounding
    avoids changing targets for every tiny fluctuation; actual weights may drift.
    Re-entry gate also blocks increases to an existing reduced SOXL target until
    recovery is confirmed. Base signals keep evolving underneath the overlay.
    """
    out=signals.copy(deep=True)
    f=features.reindex(signals.index)
    if not np.isfinite(f[['risk_soxl_vol','risk_smh_vol_ratio','risk_macd_hist']].to_numpy()).all():
        raise ValueError('Insufficient feature warm-up')
    out['underlying_state']=signals.state
    out['underlying_weight']=signals.weight
    for c in f:out[c]=f[c]
    prior_symbol='CASH';prior_weight=0.
    step=rules.get('weight_step',.05)
    for i,date in enumerate(signals.index):
        symbol=str(signals.symbol.iloc[i]);weight=float(signals.weight.iloc[i])
        state=str(signals.state.iloc[i]);reasons=[]
        if symbol=='SOXL':
            healthy=bool(f.risk_healthy.iloc[i])
            if rules.get('gate_deep') and state=='DEEP_ATTACK' and not healthy:
                weight=0.;reasons.append('DELEV_DEEP_WAIT')
            if rules.get('static_cap') is not None:
                weight=min(weight,float(rules['static_cap']))
                if weight<float(signals.weight.iloc[i]):reasons.append('DELEV_STATIC_CAP')
            if rules.get('vol_target') is not None:
                cap=min(1.,float(rules['vol_target'])/max(float(f.risk_soxl_vol.iloc[i]),1e-8))
                if weight>cap:weight=cap;reasons.append('DELEV_VOL_CAP')
            if rules.get('trend_cap') is not None and bool(f.risk_trend_bad.iloc[i]):
                if weight>float(rules['trend_cap']):
                    weight=float(rules['trend_cap']);reasons.append('DELEV_TREND_CAP')
            if rules.get('gate_reentry') and not healthy and weight>0:
                cap=prior_weight if prior_symbol=='SOXL' else 0.
                if weight>cap:weight=cap;reasons.append('DELEV_RECOVERY_WAIT')
            # Retain .99 baseline targets when no active cap changed the weight.
            if weight<float(signals.weight.iloc[i])-1e-10 and weight>0 and step:
                weight=np.floor((weight+1e-10)/step)*step
            if reasons:
                new_symbol='SOXL' if weight>0 else 'CASH'
                priority=('DELEV_DEEP_WAIT','DELEV_TREND_CAP','DELEV_RECOVERY_WAIT','DELEV_VOL_CAP','DELEV_STATIC_CAP')
                code=next(s for s in priority if s in reasons)
                out.loc[date,['symbol','weight','state','reason']]=[new_symbol,weight,code,
                    f"基础状态={state}；SOXL波动率={f.risk_soxl_vol.iloc[i]:.2%}；趋势恶化={bool(f.risk_trend_bad.iloc[i])}；恢复确认={healthy}；目标SOXL={weight:.0%}；剩余现金。收盘确认，次日开盘执行。"]
                symbol=new_symbol
        prior_symbol=symbol;prior_weight=weight
    return out


def generate_risk_signals(frames, signals, rules):
    return apply_deleveraging(signals,risk_features(frames,rules.get('vol_days',20),
        rules.get('trend_days',50),rules.get('recovery_days',3)),rules)


RISK_LABELS={'DELEV_VOL_CAP':'波动率减仓','DELEV_TREND_CAP':'趋势恶化减仓',
             'DELEV_DEEP_WAIT':'深跌等待恢复','DELEV_RECOVERY_WAIT':'等待恢复加仓','DELEV_STATIC_CAP':'固定仓位限制'}
