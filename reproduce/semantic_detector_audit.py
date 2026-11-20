"""Frozen MPNet nearest-prototype diagnostic, leaving out each full concept.

Usage: python reproduce/semantic_detector_audit.py [--root REPOSITORY] [--model-path LOCAL_SNAPSHOT]
No OOV text is a prototype; the paired trigger is also excluded for each query.
This is a three-class positive-cue diagnostic, not a deployed multilabel detector.
"""
import argparse
import sys
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

MODEL = 'sentence-transformers/all-mpnet-base-v2'
REVISION = 'e8c3b32edf5434bc2275fc9bab85f82640a19130'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    ap.add_argument('--model-path',type=Path)
    args=ap.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(17)
    torch.use_deterministic_algorithms(True)
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from _paths import DATA_DIR
    source=DATA_DIR/'detector_stress.jsonl'
    items=[json.loads(l) for l in source.read_text().splitlines()]
    location=str(args.model_path) if args.model_path else MODEL
    options={'local_files_only':True} if args.model_path else {'revision':REVISION}
    tokenizer=AutoTokenizer.from_pretrained(location,**options)
    model=AutoModel.from_pretrained(location,**options).eval()
    texts=[i['in_domain'] for i in items]+[i['oov'] for i in items]
    vectors=[]
    with torch.inference_mode():
        for first in range(0,len(texts),8):
            tokens=tokenizer(texts[first:first+8],padding=True,truncation=True,max_length=384,return_tensors='pt')
            out=model(**tokens).last_hidden_state
            mask=tokens['attention_mask'].unsqueeze(-1).expand(out.size()).float()
            pooled=(out*mask).sum(dim=1)/mask.sum(dim=1).clamp(min=1e-9)
            vectors.append(torch.nn.functional.normalize(pooled,p=2,dim=1).numpy())
    vectors=np.concatenate(vectors)
    n=len(items)
    assert vectors.shape==(2*n,768)
    similarity=vectors@vectors[:n].T
    rows=[]
    for i,item in enumerate(items):
        row={**item}
        for name,index in [('in_domain',i),('oov',n+i)]:
            scores=similarity[index].copy()
            scores[i]=-np.inf
            nearest=int(np.argmax(scores))
            predicted=items[nearest]['detector']
            row[name+'_prediction']=predicted
            row[name+'_target_detected']=int(predicted==item['detector'])
            row[name+'_nearest_concept']=items[nearest]['concept']
            row[name+'_cosine']=float(scores[nearest])
        rows.append(row)
    summary=[]
    for detector in ('H','C','M'):
        d=[r for r in rows if r['detector']==detector]
        summary.append({'detector':detector,'n_concepts':len(d),
            'trigger_recall':sum(r['in_domain_target_detected'] for r in d)/len(d),
            'paraphrase_recall':sum(r['oov_target_detected'] for r in d)/len(d)})
    report={'analysis_date':'2026-10-21','model':MODEL,'revision':REVISION,
        'dataset_sha256':sha(source),'model_sha256':sha(args.model_path/'model.safetensors') if args.model_path else None,
        'protocol':'leave-one-concept-out cosine nearest neighbor among the other 29 trigger texts; no OOV prototypes, tuning, or threshold selection',
        'pooling':'attention-mask mean pooling, L2 normalization, max length 384',
        'limits':'positive-cue, three-class diagnostic; no negative/no-cue examples; no end-to-end agent rerun or clinical validation',
        'environment':{'python':platform.python_version(),'platform':platform.platform(),
            **{p:importlib.metadata.version(p) for p in ('torch','transformers','numpy')}},
        'summary':summary,'details':rows}
    target=args.root/'results/run_combined_5models/metrics/reviewer_revision'
    target.mkdir(parents=True,exist_ok=True)
    (target/'semantic_detector_audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    np.savez_compressed(target/'semantic_detector_embeddings.npz',embeddings=vectors)
    print(json.dumps({'model':MODEL,'revision':REVISION,'summary':summary},indent=2))


if __name__=='__main__':
    main()
