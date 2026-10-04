"""Explicit, versioned 99% target upgrade. Never auto-run or place orders."""
import argparse
import ast
import json

import pandas as pd

import core
import code_strategy


def upgrade_source(source):
    """Edit allocation literals only; leave prices, thresholds and dates intact."""
    tree=ast.parse(source);nodes=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Dict):
            nodes.extend(value for key,value in zip(node.keys,node.values)
                if isinstance(key,ast.Constant) and key.value=='attack')
        if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) and node.target.id=='attack':
            nodes.append(node.value)
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in ('wt','wq','weight','attack') for t in node.targets):
            nodes.append(node.value)
    raw=source.encode('utf-8');lines=raw.splitlines(keepends=True);edits=[]
    for node in nodes:
        if isinstance(node,ast.Constant) and type(node.value) is float and node.value==.99:
            start=sum(map(len,lines[:node.lineno-1]))+node.col_offset
            end=sum(map(len,lines[:node.end_lineno-1]))+node.end_col_offset
            edits.append((start,end))
    for start,end in sorted(set(edits),reverse=True):raw=raw[:start]+b'1.0'+raw[end:]
    result=raw.decode('utf-8')
    metadata=code_strategy.check_source(result)
    notes=metadata.get('STATE_NOTES',{})
    revised={key:(text.replace('99%','100%').replace('现金1%','现金0%') if '99%' in text else text) for key,text in notes.items()}
    if notes!=revised:
        import strategy_states
        result=strategy_states.replace_metadata(result,metadata.get('STATE_LABELS',{}),revised)
    result=result.replace('Retain .99 baseline targets','Retain 1.0 baseline targets')
    if result!=source and 'CC BY-NC 4.0' in result:
        result=result.replace('保留每日状态条件和目标权重。','保留每日状态条件；按用户要求将99%目标改为100%。')
    return result


def prepare_updates(profiles,inputs):
    updates=[]
    cutoff=inputs['snapshot']['last']['date'];bundle=inputs['confirmed_bundle']
    for old in profiles:
        parameters=dict(old['parameters'])
        if parameters['attack']==.99:parameters['attack']=1.
        source=upgrade_source(old['code']) if old.get('kind')=='python' else None
        if parameters==old['parameters'] and source==old.get('code'):continue
        new=core.make_strategy(old['name'],parameters,old['description'],old['id'],old['revision']+1,code=source)
        new['created']=old['created']
        resolved=core.ensure_strategy_bundle(bundle,cutoff,new)
        frames=core.load_bundle(resolved,cutoff)
        before=core.replay(frames,old,audit_code=True);after=core.replay(frames,new,audit_code=True)
        # Each changed target must be precisely 99 -> 100; rule states and all
        # other allocations remain unchanged. This also audits private overlays.
        for column in ('state','symbol','regime'):
            pd.testing.assert_series_equal(before[column],after[column],check_names=False)
        for column in ('weight','weight_QQQ','weight_TQQQ'):
            if column in before:
                expected=before[column].mask(before[column].eq(.99),1.)
                pd.testing.assert_series_equal(expected,after[column],check_names=False,atol=1e-12,rtol=0)
        updates.append((old,new,frames,after,resolved))
    return updates


def upgrade_existing():
    """Validate everything first, then atomically version and update active view."""
    profiles=core.list_strategies();inputs,raw=core.captured_inputs()
    updates=prepare_updates(profiles,inputs)
    active=inputs['active_strategy'];active_update=next((item for item in updates if item[0]['fingerprint']==active['fingerprint']),None)
    snap=None
    if active_update:
        old,new,frames,signals,bundle=active_update;previous=inputs['snapshot']
        snap=core.pack(frames,signals,previous['source'],previous.get('fetched'),previous.get('quotes'),new)
    with core.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        live=dict(db.execute("SELECT key,value FROM kv WHERE key IN ('snapshot','confirmed_bundle','active_strategy')").fetchall())
        if live!=raw:raise core.StrategyChanged('行情或启用版本正在变化，本次未保存，请稍后重试。')
        for old,new,*_ in updates:
            current=json.loads(db.execute('SELECT payload FROM strategy_profiles WHERE id=?',(old['id'],)).fetchone()[0])
            if current['fingerprint']!=old['fingerprint']:raise core.StrategyChanged('策略已被其他操作修改，本次未保存。')
            db.execute('INSERT INTO strategy_versions VALUES (?,?,?)',(new['id'],new['revision'],core.json_dump(new)))
            db.execute('UPDATE strategy_profiles SET revision=?,payload=? WHERE id=?',(new['revision'],core.json_dump(new),new['id']))
        if snap:
            for key,value in [('active_strategy',active_update[1]),('snapshot',snap),('confirmed_bundle',active_update[4]),('preview',None)]:
                db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)',(key,core.json_dump(value)))
    if updates:
        core.event('策略更新','99%目标仓位已改为100%',f'已更新{len(updates)}套策略；旧版本保留，可恢复。当前启用策略沿用原名称与规则。未执行交易。','full-allocation:'+core.iso_now())
    return [{'name':new['name'],'from_revision':old['revision'],'revision':new['revision']} for old,new,*_ in updates]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true',help='明确授权更新本机已保存版本及当前启用策略')
    args=parser.parse_args()
    if not args.apply:parser.error('这是显式策略修改工具，运行时需指定 --apply；不会在启动时自动更新。')
    core.init_db()
    print(json.dumps(upgrade_existing(),ensure_ascii=True))
