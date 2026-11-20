"""Reproduce reviewer-requested analyses from the frozen benchmark outputs.

Usage: python reproduce/review_revision_analysis.py [repository_root]
Requires NumPy and pandas. No model inference or test-label tuning is used.
"""
import ast
import hashlib
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

COSTS = (1, 2, 3, 5, 10, 20)
ACTIONS = ('ANSWER', 'ASK_CLARIFICATION', 'ABSTAIN', 'ESCALATE')
WEIGHTS = tuple(itertools.product((0., .25, .5, .75, 1.), repeat=4))[1:]
THRESHOLDS = tuple(itertools.combinations(tuple(round(.2+.15*i, 2) for i in range(9)), 2))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counts(actions, required):
    esc = np.asarray(actions) == 'ESCALATE'
    req = np.asarray(required, bool)
    return {'tp':int((esc & req).sum()),'tn':int((~esc & ~req).sum()),
            'fn':int((~esc & req).sum()),'fp':int((esc & ~req).sum()),'n':len(req)}


def utility(c, cost):
    return (c['tp']+c['tn']-cost*c['fn']-c['fp'])/c['n']


def candidate_grid(dev):
    features = np.stack([1-dev.confidence.to_numpy(float)] +
                        [dev[f].to_numpy(float) for f in ('C','M','H')], axis=0)
    risks = np.asarray(WEIGHTS) @ features
    risks = np.repeat(risks, len(THRESHOLDS), axis=0)
    taus = np.tile(np.asarray(THRESHOLDS), (len(WEIGHTS),1))
    base = np.asarray([ACTIONS.index(a) for a in dev.action], dtype=np.int8)
    actions = np.broadcast_to(base, risks.shape).copy()
    mid = (risks>=taus[:,0,None]) & (risks<taus[:,1,None])
    actions[mid & (actions==0)] = 1
    actions[risks>=taus[:,1,None]] = 3
    acceptable = np.asarray([[a in acc for a in ACTIONS] for acc in dev.acceptable])
    accuracy = acceptable[np.arange(len(dev))[None,:],actions].mean(axis=1)
    req = dev.esc_required.to_numpy(bool)[None,:]
    esc = actions==3
    return {
        'tp':(esc & req).sum(axis=1),'tn':(~esc & ~req).sum(axis=1),
        'fn':(~esc & req).sum(axis=1),'fp':(esc & ~req).sum(axis=1),
        'accuracy':accuracy,'n':len(dev),'taus':taus,
    }


def apply_params(d, w, low, high):
    risk = w[0]*(1-d.confidence.to_numpy(float))
    for weight, f in zip(w[1:],('C','M','H')):
        risk += weight*d[f].to_numpy(float)
    actions = d.action.to_numpy(object).copy()
    mid = (risk>=low)&(risk<high)
    actions[mid&(actions=='ANSWER')] = 'ASK_CLARIFICATION'
    actions[risk>=high] = 'ESCALATE'
    return actions


def main(root):
    root = Path(root)
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from _paths import DATA_DIR, resolve
    from detectors import strip_headers, RISK_RE, CONFLICT_RE, MISSING_RE
    run = root/'results/run_combined_5models'
    out = run/'metrics/reviewer_revision'
    out.mkdir(parents=True,exist_ok=True)
    episodes = [json.loads(l) for l in (DATA_DIR/'episodes.jsonl').read_text().splitlines()]
    eframe = pd.DataFrame(episodes)
    frame = pd.read_csv(run/'metrics/predictions_long.csv',
                        converters={'acceptable':lambda v:tuple(ast.literal_eval(v))})
    assert not frame.duplicated(['episode_id','model','condition']).any()
    saved = json.loads((run/'metrics/controller_params.json').read_text())
    label_rows=[]
    for split in ('all','dev','test'):
        d=eframe if split=='all' else eframe[eframe.split==split]
        multi=d.acceptable_actions.map(len)>1
        assert d.apply(lambda r:r.reference_action in r.acceptable_actions,axis=1).all()
        label_rows.append({'split':split,'n':len(d),'multi_action':int(multi.sum()),
            'fraction':float(multi.mean()),'seeds':int(d[multi].seed_id.nunique()),
            'optional_escalation':int(d.apply(lambda r:'ESCALATE' in r.acceptable_actions and r.reference_action!='ESCALATE',axis=1).sum()),
            'reference_escalation_with_accepted_alternative':int(d.apply(lambda r:r.reference_action=='ESCALATE' and len(r.acceptable_actions)>1,axis=1).sum())})
    strict=[]
    for (model,condition),d in frame[frame.split=='test'].groupby(['model','condition']):
        set_ok=np.asarray([a in acc for a,acc in zip(d.action,d.acceptable)])
        strict_ok=(d.action==d.reference_action).to_numpy()
        gain=int((set_ok&~strict_ok).sum())
        strict.append({'model':model,'condition':condition,'n':len(d),
            'set_accuracy':float(set_ok.mean()),'single_reference_accuracy':float(strict_ok.mean()),
            'extra_accepted':gain,'accuracy_difference_pp':100*gain/len(d)})
    exclusive=[]
    for (model,condition),d in frame[(frame.split=='test')&frame.acceptable.map(lambda a:len(a)==1)].groupby(['model','condition']):
        c=counts(d.action,d.esc_required)
        exclusive.append({'model':model,'condition':condition,**c,
            'decision_accuracy':float((d.action==d.reference_action).mean()),
            'sensitivity':c['tp']/(c['tp']+c['fn']),
            'specificity':c['tn']/(c['tn']+c['fp']),
            'utility_5:1':utility(c,5)})
    fp_rows=[]
    fp_detail=[]
    fixed=[]
    retuned=[]
    paired=[]
    for model,base in frame[frame.condition=='uncertainty'].groupby('model'):
        dev=base[base.split=='dev'].copy()
        test=base[base.split=='test'].copy().sort_values('episode_id')
        ctrl=frame[(frame.condition=='controller')&(frame.split=='test')&(frame.model==model)].set_index('episode_id').loc[test.episode_id]
        p=saved[model]
        assert np.array_equal(apply_params(test,p['w'],p['tau_low'],p['tau_high']),ctrl.action.to_numpy())
        test['controlled_action']=ctrl.action.to_numpy()
        test['fp']=(test.controlled_action=='ESCALATE')&~test.esc_required
        test['base_fp']=(test.action=='ESCALATE')&~test.esc_required
        test['optional_escalation']=test.acceptable.map(lambda a:'ESCALATE' in a)&~test.esc_required
        assert (test.base_fp<=test.fp).all(), 'Policy can only add escalations'
        for scope,columns in [('task',['task']),('variant',['perturbation']),('task_variant',['task','perturbation'])]:
            for key,d in test.groupby(columns):
                key=key if isinstance(key,tuple) else (key,)
                fp_rows.append({'model':model,'scope':scope,**dict(zip(columns,key)),
                    'non_escalation_episodes':int((~d.esc_required).sum()),
                    'false_escalations':int(d.fp.sum()),'base_false_escalations':int(d.base_fp.sum()),
                    'new_false_escalations':int((d.fp&~d.base_fp).sum()),
                    'optional_escalations':int((d.fp&d.optional_escalation).sum()),
                    'unaccepted_escalations':int((d.fp&~d.optional_escalation).sum())})
        for row in test[test.fp].itertuples():
            episode=episodes[next(i for i,e in enumerate(episodes) if e['episode_id']==row.episode_id)]
            matches={}
            for feature,pattern in [('H',RISK_RE),('C',CONFLICT_RE),('M',MISSING_RE)]:
                match=pattern.search(strip_headers(episode['transcript']))
                matches[feature+'_matched_span']=match.group() if match else None
            fp_detail.append({'model':model,'episode_id':row.episode_id,'task':row.task,
                'variant':row.perturbation,'seed_id':row.seed_id,'scenario':episode['scenario'],
                'reference_action':row.reference_action,'base_action':row.action,
                'escalation_in_acceptable_set':bool(row.optional_escalation),
                'new_false_escalation':not row.base_fp,'confidence':row.confidence,
                'H':row.H,'C':row.C,'M':row.M,**matches,'rationale':episode['rationale']})
        grid=candidate_grid(dev)
        base_counts=counts(test.action,test.esc_required)
        ctl_counts=counts(test.controlled_action,test.esc_required)
        for cost in COSTS:
            bu=utility(base_counts,cost)
            cu=utility(ctl_counts,cost)
            fixed.append({'model':model,'c_fn':cost,'c_fp':1,'policy_tuned_at':5,
                'base_utility':bu,'controller_utility':cu,'delta_utility':cu-bu,
                **{'controller_'+k:v for k,v in ctl_counts.items()},
                **{'base_'+k:v for k,v in base_counts.items()}})
            # Paired differences, resampling all surface/variant rows of each seed.
            diffs=[]
            for _,d in test.groupby('seed_id'):
                diffs.append(utility(counts(d.controlled_action,d.esc_required),cost)-
                             utility(counts(d.action,d.esc_required),cost))
            rng=np.random.default_rng(1701)
            diffs=np.asarray(diffs)
            boot=diffs[rng.integers(0,len(diffs),size=(5000,len(diffs)))].mean(axis=1)
            paired.append({'model':model,'c_fn':cost,'delta':cu-bu,
                'n_seeds':len(diffs),'ci_low':float(np.percentile(boot,2.5)),
                'ci_high':float(np.percentile(boot,97.5))})
            us=(grid['tp']+grid['tn']-cost*grid['fn']-grid['fp'])/grid['n']
            options=np.flatnonzero(us==us.max())
            best=options[np.argmax(grid['accuracy'][options])]
            w=WEIGHTS[best//len(THRESHOLDS)]
            low,high=grid['taus'][best]
            if cost==5:
                assert tuple(p['w'])==w and p['tau_low']==low and p['tau_high']==high
            acts=apply_params(test,w,low,high)
            c=counts(acts,test.esc_required)
            retuned.append({'model':model,'c_fn':cost,'c_fp':1,'weights':w,
                'tau_low':float(low),'tau_high':float(high),'dev_utility':float(us[best]),
                'test_utility':utility(c,cost),'sensitivity':c['tp']/(c['tp']+c['fn']),
                'specificity':c['tn']/(c['tn']+c['fp']),**c})
    result={'analysis_date':'2026-10-21','analysis_type':'post-review, post-hoc extension',
        'input_sha256':{rel:digest(resolve(root,rel)) for rel in ['data/episodes.jsonl','data/detector_stress.jsonl',
            'results/run_combined_5models/metrics/predictions_long.csv',
            'results/run_combined_5models/metrics/controller_params.json']},
        'cost_ratios':COSTS,'fixed_policy':'original 5:1 development-selected controller; no retuning',
        'retuned_policy':'separate development-only selection at each ratio; frozen test outputs',
        'acceptable_action_counts':label_rows,'accuracy_sensitivity':strict,
        'single_action_subset_sensitivity':exclusive,
        'false_escalation_summary':fp_rows,'false_escalation_details':fp_detail,
        'fixed_cost_sweep':fixed,'paired_delta_seed_bootstrap':paired,'dev_retuned_cost_sweep':retuned}
    (out/'reviewer_analysis.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    for name,rows in [('acceptable_action_counts',label_rows),('accuracy_sensitivity',strict),
        ('single_action_subset_sensitivity',exclusive),
        ('false_escalation_summary',fp_rows),('false_escalation_details',fp_detail),
        ('fixed_cost_sweep',fixed),('paired_delta_seed_bootstrap',paired),('dev_retuned_cost_sweep',retuned)]:
        pd.DataFrame(rows).to_csv(out/(name+'.csv'),index=False,lineterminator='\n')
    print(json.dumps({'acceptable_action_counts':label_rows,
        'accuracy_sensitivity':strict,'fixed_cost_sweep':fixed,'dev_retuned_cost_sweep':retuned},indent=2))


if __name__=='__main__':
    main(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parent.parent)
