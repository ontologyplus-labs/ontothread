"""Manifest-driven paired condition metrics with document-cluster uncertainty."""
from collections import Counter
from hashlib import sha256
import json
import random
from math import comb
from pathlib import Path


def _safe_ratio(numerator,denominator):return numerator/denominator if denominator else None

def wilson_interval(successes,total,z=1.959963984540054):
    if not total:return [None,None]
    p=successes/total;denominator=1+z*z/total;center=(p+z*z/(2*total))/denominator
    margin=z*((p*(1-p)/total+z*z/(4*total*total))**.5)/denominator
    return [max(0,center-margin),min(1,center+margin)]


def condition_metrics(items,condition):
    counts=Counter()
    for item in items:
        gold=bool(item["gold_supported"]);prediction=bool(item["conditions"][condition]["supported"])
        counts["tp" if gold and prediction else "fp" if prediction else "fn" if gold else "tn"]+=1
    precision=_safe_ratio(counts["tp"],counts["tp"]+counts["fp"])
    recall=_safe_ratio(counts["tp"],counts["tp"]+counts["fn"])
    denominator=2*counts["tp"]+counts["fp"]+counts["fn"]
    return {**{key:counts[key] for key in ("tp","fp","fn","tn")},"n":len(items),"precision":precision,"recall":recall,
            "precision_wilson95":wilson_interval(counts["tp"],counts["tp"]+counts["fp"]),
            "recall_wilson95":wilson_interval(counts["tp"],counts["tp"]+counts["fn"]),"f1":2*counts["tp"]/denominator if denominator else None}

def paired_correctness(items,baseline,treatment):
    transitions=Counter();errors=[]
    for item in items:
        gold=bool(item["gold_supported"]);left=bool(item["conditions"][baseline]["supported"]);right=bool(item["conditions"][treatment]["supported"])
        left_correct=left==gold;right_correct=right==gold
        transition="both_correct" if left_correct and right_correct else "recovered" if not left_correct and right_correct else "regressed" if left_correct and not right_correct else "both_wrong"
        transitions[transition]+=1
        if not right_correct:errors.append({"item_id":item["id"],"error_type":"false_positive" if right else "false_negative"})
    discordant=transitions["recovered"]+transitions["regressed"]
    if discordant:
        tail=sum(comb(discordant,k) for k in range(0,min(transitions["recovered"],transitions["regressed"])+1))/(2**discordant)
        p=min(1,2*tail)
    else:p=None
    return {**{key:transitions[key] for key in ("both_correct","recovered","regressed","both_wrong")},"discordant":discordant,"mcnemar_exact_two_sided_p":p,"treatment_errors":errors}


def _quantile(values,q):
    if not values:return None
    ordered=sorted(values);position=(len(ordered)-1)*q;lower=int(position);upper=min(lower+1,len(ordered)-1);fraction=position-lower
    return ordered[lower]*(1-fraction)+ordered[upper]*fraction


def paired_cluster_bootstrap(items,baseline,treatment,*,iterations=2000,seed=1729):
    clusters={}
    for item in items:clusters.setdefault(item["document_id"],[]).append(item)
    names=sorted(clusters);rng=random.Random(seed);deltas=[]
    if not names:return {"iterations":0,"cluster_count":0,"recall_delta_ci95":[None,None],"seed":seed}
    for _ in range(iterations):
        sample=[]
        for name in rng.choices(names,k=len(names)):sample.extend(clusters[name])
        left=condition_metrics(sample,baseline)["recall"];right=condition_metrics(sample,treatment)["recall"]
        if left is not None and right is not None:deltas.append(right-left)
    return {"iterations":iterations,"cluster_count":len(names),"successful_iterations":len(deltas),"seed":seed,
            "recall_delta_ci95":[_quantile(deltas,.025),_quantile(deltas,.975)],
            "warning":"A one-cluster interval measures no cross-document uncertainty." if len(names)<2 else None}


def run_experiment(spec,*,iterations=2000,seed=1729):
    required={"version","items","baseline","treatment","independent_human_review","partition"}
    missing=required-set(spec)
    if missing:raise ValueError("experiment specification missing: "+", ".join(sorted(missing)))
    items=spec["items"]
    if not items:raise ValueError("experiment requires at least one item")
    ids=[item["id"] for item in items]
    if len(ids)!=len(set(ids)):raise ValueError("experiment item IDs must be unique")
    baseline=spec["baseline"];treatment=spec["treatment"]
    for item in items:
        if not item.get("document_id") or baseline not in item["conditions"] or treatment not in item["conditions"]:
            raise ValueError("every item requires a document cluster and both paired conditions")
    left=condition_metrics(items,baseline);right=condition_metrics(items,treatment)
    recall_delta=None if left["recall"] is None or right["recall"] is None else right["recall"]-left["recall"]
    precision_delta=None if left["precision"] is None or right["precision"] is None else right["precision"]-left["precision"]
    digest=sha256(json.dumps(spec,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"experiment_version":spec["version"],"spec_sha256":digest,"partition":spec["partition"],
            "independent_human_review":bool(spec["independent_human_review"]),
            "publication_ready":bool(spec["independent_human_review"]) and spec["partition"] in {"test","prospective_test"},
            "baseline":baseline,"treatment":treatment,"condition_metrics":{baseline:left,treatment:right},
            "paired_effects":{"recall_delta":recall_delta,"precision_delta":precision_delta,
                "precision_noninferiority_margin":-.05,"precision_guardrail_pass":precision_delta is not None and precision_delta>=-.05},
            "paired_correctness":paired_correctness(items,baseline,treatment),
            "uncertainty":paired_cluster_bootstrap(items,baseline,treatment,iterations=iterations,seed=seed),
            "raw_denominators":{"items":len(items),"positive_items":sum(bool(item["gold_supported"]) for item in items),
                "negative_items":sum(not bool(item["gold_supported"]) for item in items),"documents":len({item["document_id"] for item in items})},
            "limitations":spec.get("limitations",[])+([] if spec["independent_human_review"] else ["Labels are not independently human reviewed; results are development evidence only."])}


def write_experiment(spec_path,report_path,*,iterations=2000,seed=1729):
    spec=json.loads(Path(spec_path).read_text());report=run_experiment(spec,iterations=iterations,seed=seed)
    path=Path(report_path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+"\n")
    return report
