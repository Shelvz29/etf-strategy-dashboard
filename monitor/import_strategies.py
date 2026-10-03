"""Register distributed strategy sources locally; never activate or overwrite."""
import argparse
import json
from pathlib import Path

import core
import code_strategy

CATALOG = ('SMH和SOXL组合策略','SOXX和SOXL组合策略','MACD＋4%急跌避险策略',
           'QQQ和TQQQ双核策略 V22.1','纳指四季 V22.3')


def import_profiles(names=CATALOG):
    core.bootstrap()
    active = core.active_strategy()['fingerprint']
    existing = {p['name']:p for p in core.list_strategies()}
    imported = []
    for name in names:
        code = (Path(__file__).parent/'strategies'/(name+'.py')).read_text(encoding='utf-8')
        if name in existing:
            if existing[name].get('code_hash') != code_strategy.code_hash(code):
                # User-edited saved strategies are valuable; never silently replace them.
                print(json.dumps({'name':name,'status':'kept_user_version'},ensure_ascii=True))
            imported.append(existing[name])
            continue
        profile = core.save_strategy(name,code=code,description='发行策略源文件的本地导入；具体规则及原作者署名见编辑代码。导入不会启用。')
        imported.append(profile)
        print(json.dumps({'name':name,'revision':profile['revision'],'status':'imported'},ensure_ascii=True))
    assert core.active_strategy()['fingerprint'] == active
    return imported


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--moomoo-only',action='store_true')
    args=parser.parse_args()
    import_profiles(CATALOG[-2:] if args.moomoo_only else CATALOG)
