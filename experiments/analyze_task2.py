#!/usr/bin/env python3
"""Task 2 evidence analyzer. Standardized CSV inputs; never infers missing tests as passes."""
import argparse, csv, json, math, statistics
from pathlib import Path

def rows(path):
    if not path.exists(): return None
    with path.open(newline='') as f: return list(csv.DictReader(f))

def fnum(v):
    try: return float(v)
    except (ValueError, TypeError): return None

def percentile(vals, p):
    if not vals: return None
    a=sorted(vals); x=(len(a)-1)*p/100; lo=math.floor(x); hi=math.ceil(x)
    return a[lo]+(a[hi]-a[lo])*(x-lo)

def metric(vals):
    return {'count':len(vals), 'p50_ms':percentile(vals,50), 'p95_ms':percentile(vals,95), 'p99_ms':percentile(vals,99), 'max_ms':max(vals) if vals else None}

def status(ok, available=True): return 'NOT MEASURED' if not available else ('PASS' if ok else 'FAIL')

def analyze(root):
    out={'schema_version':1,'run_id':root.name,'tests':{},'notes':[]}
    video=rows(root/'frames.csv')
    if video is None: out['tests']['video']={'status':'NOT MEASURED','required':'frames.csv'}
    else:
        cams={}
        for cam in ['head','left','right']:
            rr=[r for r in video if r.get('camera')==cam]
            # One row per CAPTURED frame, including missing ones.
            ids=[r.get('frame_id') for r in rr]
            good=[r for r in rr if r.get('integrity_ok','').lower() in ('1','true','yes') and fnum(r.get('latency_ms')) is not None and fnum(r['latency_ms'])<=200 and r.get('displayed','').lower() in ('1','true','yes')]
            frac=len(good)/len(rr) if rr else None
            cams[cam]={'captured':len(rr),'good':len(good),'good_fraction':frac,'good_latency':metric([float(r['latency_ms']) for r in good]),'duplicate_frame_ids':len(ids)-len(set(ids)),'status':status(frac>=.8 if frac is not None else False, bool(rr)) if cam=='head' else status(True,bool(rr))}
        # Head threshold must be evaluated during degraded interval separately.
        deg=[r for r in video if r.get('camera')=='head' and r.get('budget_phase')=='degraded']
        good_deg=[r for r in deg if r.get('integrity_ok','').lower() in ('1','true','yes') and r.get('displayed','').lower() in ('1','true','yes') and fnum(r.get('latency_ms')) is not None and float(r['latency_ms'])<=200]
        frac=len(good_deg)/len(deg) if deg else None
        out['tests']['video']={'status':status(frac>=.8 if frac is not None else False,bool(deg)),'by_camera':cams,'head_degraded':{'captured':len(deg),'good':len(good_deg),'fraction':frac},'note':'frames.csv must include one row per captured frame, including lost frames; latency must be capture-to-display.'}
    motion=rows(root/'motion.csv')
    if motion is None: out['tests']['motion']={'status':'NOT MEASURED','required':'motion.csv'}
    else:
        ages=[fnum(r.get('age_ms')) for r in motion if r.get('applied')=='1']; ages=[v for v in ages if v is not None]
        violations=sum(r.get('violation')=='1' for r in motion)
        watchdog=rows(root/'watchdog.csv')
        wd_viol=sum(fnum(r.get('stop_delay_ms')) is None or float(r['stop_delay_ms'])>300 for r in watchdog) if watchdog else None
        ok=bool(ages) and violations==0 and max(ages)<=150 and wd_viol==0
        out['tests']['motion']={'status':status(ok,bool(ages) and bool(watchdog)),'applied_age':metric(ages),'violations':violations,'watchdog_trials':len(watchdog) if watchdog else 0,'watchdog_violations':wd_viol}
    estop=rows(root/'estop.csv')
    if estop is None: out['tests']['estop']={'status':'NOT MEASURED','required':'estop.csv'}
    else:
        effects=[fnum(r.get('effect_latency_ms')) for r in estop]; effects=[v for v in effects if v is not None]
        anomalies={k:sum(r.get(k)=='1' for r in estop) for k in ['lost','duplicate_effect','reordered']}
        out['tests']['estop']={'status':status(bool(effects) and max(effects)<=200 and all(v==0 for v in anomalies.values()),bool(estop)),'effect_latency':metric(effects),'anomalies':anomalies,'trials':len(estop)}
    queries=rows(root/'queries.csv')
    if queries is None: out['tests']['queries']={'status':'NOT MEASURED','required':'queries.csv'}
    else:
        times=[fnum(r.get('latency_ms')) for r in queries if r.get('reply_count')=='1']; times=[v for v in times if v is not None]
        bad=sum(not ((r.get('reply_count')=='1' and r.get('timed_out')=='0') or (r.get('reply_count')=='0' and r.get('timed_out')=='1')) for r in queries)
        out['tests']['queries']={'status':status(bad==0,bool(queries)),'latency':metric(times),'timeouts':sum(r.get('timed_out')=='1' for r in queries),'duplicate_replies':sum(int(r.get('reply_count','0'))>1 for r in queries),'invalid_outcomes':bad,'trials':len(queries)}
    recovery=rows(root/'recovery.csv')
    if recovery is None: out['tests']['recovery']={'status':'NOT MEASURED','required':'recovery.csv'}
    else:
        by={}
        for side in ['operator','robot']:
            rr=[r for r in recovery if r.get('side')==side]
            valid=bool(rr) and all(fnum(r.get('video_recovery_ms')) is not None and fnum(r.get('motion_recovery_ms')) is not None for r in rr)
            ok=valid and all(max(float(r['video_recovery_ms']),float(r['motion_recovery_ms']))<=1000 for r in rr)
            by[side]={'status':status(ok,valid),'trials':len(rr),'max_video_ms':max((float(r['video_recovery_ms']) for r in rr),default=None) if valid else None,'max_motion_ms':max((float(r['motion_recovery_ms']) for r in rr),default=None) if valid else None}
        out['tests']['recovery']={'status':status(all(v['status']=='PASS' for v in by.values()),all(v['status']!='NOT MEASURED' for v in by.values())),'by_side':by}
    bandwidth=rows(root/'bandwidth.csv')
    if bandwidth is None: out['tests']['bandwidth']={'status':'NOT MEASURED','required':'bandwidth.csv'}
    else:
        # For strict token-bucket compliance, use packet timestamps/bytes and replay token bucket; rate averages alone are not a proof.
        out['tests']['bandwidth']={'status':'NOT MEASURED','samples':len(bandwidth),'note':'Interval rates are diagnostic only. Validate physical/interface byte counts and token-bucket bursts separately.'}
    out['overall']='PASS' if all(v['status']=='PASS' for v in out['tests'].values()) else 'INCOMPLETE OR FAIL'
    return out

def report(out):
    lines=[f"# Task 2 TCP/UDP acceptance report — {out['run_id']}",'',f"Overall: **{out['overall']}**",'', '| Test | Status |','|---|---|']
    for k,v in out['tests'].items(): lines.append(f"| {k} | {v['status']} |")
    lines += ['', '## Full results','', '```json',json.dumps(out,indent=2), '```','', 'NOT MEASURED means the required evidence is absent or insufficient.']
    return '\n'.join(lines)+'\n'

def plot(root):
    try: import matplotlib.pyplot as plt
    except ImportError: return False
    bandwidth=rows(root/'bandwidth.csv'); video=rows(root/'frames.csv'); motion=rows(root/'motion.csv')
    if not bandwidth and not video and not motion: return False
    fig,axs=plt.subplots(3,1,figsize=(12,9),sharex=True)
    if bandwidth:
        for key,label in [('budget_mbps','Budget'),('actual_tx_mbps','Actual sent')]:
            points=[(fnum(r.get('elapsed_s')),fnum(r.get(key))) for r in bandwidth]
            points=[p for p in points if None not in p]
            if points: axs[0].plot(*zip(*points),label=label)
        axs[0].legend(); axs[0].set_ylabel('Mbit/s')
    if video:
        for cam in ['head','left','right']:
            points=[(fnum(r.get('elapsed_s')),fnum(r.get('latency_ms'))) for r in video if r.get('camera')==cam]
            points=[p for p in points if None not in p]
            if points: axs[1].scatter(*zip(*points),s=3,label=cam)
        axs[1].axhline(200,linestyle='--'); axs[1].legend(); axs[1].set_ylabel('Frame latency (ms)')
    if motion:
        points=[(fnum(r.get('elapsed_s')),fnum(r.get('age_ms'))) for r in motion]
        points=[p for p in points if None not in p]
        if points: axs[2].scatter(*zip(*points),s=3)
        axs[2].axhline(150,linestyle='--'); axs[2].set_ylabel('Command age (ms)')
    axs[2].set_xlabel('Elapsed seconds'); fig.tight_layout(); fig.savefig(root/'timeline.png',dpi=160); plt.close(fig)
    return True

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('run_dir',type=Path); args=p.parse_args(); args.run_dir.mkdir(parents=True,exist_ok=True)
    result=analyze(args.run_dir)
    (args.run_dir/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (args.run_dir/'report.md').write_text(report(result))
    plot(args.run_dir)
    print(report(result).split('## Full results')[0]); print('Saved to',args.run_dir)
