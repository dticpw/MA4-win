"""One-time equivalence check against the committed implementation; no RPC/state writes."""
import copy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from controllers import Controllers

old_source = subprocess.check_output(['git', 'show', '5b79fe6:controllers.py'], cwd=ROOT).decode('utf-8')
old_ns = {'__name__': 'before_policy_split', '__file__': str(ROOT / 'controllers.py')}
exec(compile(old_source, '5b79fe6:controllers.py', 'exec'), old_ns)
old = old_ns['Controllers'].__new__(old_ns['Controllers'])
new = Controllers.__new__(Controllers)
rng = random.Random(41807)
methods = ['usage', 'cost', 'exhausted', 'confirm_blocker', 'handoff_blocker', 'report_delivery', 'diagnosis']
codes = set()
for case in range(2000):
    t = {'host':'host', 'hostBusy':rng.choice([False,True]),
         'status':rng.choice(['draft','running','waiting','review','closing','paused','budget','attention','completed','stopped']),
         'target':'目标', 'goalConfirmed':rng.choice([False,True]),
         'budget':{'deadline':rng.choice([900,1000,1100])}, 'usage':{},
         'workers':{'w':{'name':'执行者','state':rng.choice(['idle','running','sending','queued','unknown'])}},
         'pending':rng.choice([[],[{'id':'w:t','threadId':'w','turnId':'t'}]]),
         'closing':{'needsReview':rng.choice([False,True]),'reviewStarted':rng.choice([False,True])}}
    if rng.random()<.3:t['host']=None
    for key in ['handoff','handoffPending','outbox','draft','costUncertain']:
        if rng.random()<.15:t[key]='present'
    if rng.random()<.3:
        t['usage']={'host':{'totalTokens':1000,'inputTokens':900,'cachedInputTokens':600,'outputTokens':100}}
        t['budget'].update(tokenLimit=rng.choice([500,2000]),moneyLimit=.001,rates={'input':2,'cached':1,'output':4})
    if rng.random()<.3:
        t['metrics']={'host':{'turns':{'a':{'id':'a','startedAt':800,'status':rng.choice(['failed','completed'])}}}}
    connected=rng.random()>.15; recovering=rng.random()<.15; error='error' if rng.random()<.1 else None
    for c in [old,new]:
        c.hub=SimpleNamespace(daemon={'connected':connected});c.clock=lambda:1000;c.error=error;c.recovering=recovering
    original=copy.deepcopy(t)
    assert old.control_blocker()==new.control_blocker(),case
    for method in methods:
        expected=getattr(old,method)(t)
        actual=getattr(new,method)(t)
        assert actual==expected,(case,method,expected,actual)
        assert t==original,(case,method,'mutated task')
        if method=='diagnosis':codes.add(actual['code'])
result={'result':'passed','baselineCommit':'5b79fe6','baselineSourceSha256':hashlib.sha256(old_source.encode()).hexdigest(),
        'seed':41807,'scenarios':2000,'comparisons':16000,'methods':['control_blocker',*methods],
        'observedDiagnosisCodes':sorted(codes),'inputMutation':False,'modelCalls':0,
        'limits':'Generated combinations compare existing semantics; they do not prove every possible state or real transport recovery.'}
print(json.dumps(result,ensure_ascii=False))
