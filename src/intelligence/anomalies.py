"""Past-only robust screening. No labels => no claimed precision or recall."""
import math
from statistics import median


def detect(days, values, metric, threshold=3.5):
    flags=[]
    for i,current in enumerate(values):
        if current is None:
            continue
        prior=[(days[j],float(values[j])) for j in range(max(0,i-56),i) if values[j] is not None]
        if len(prior)<28:
            continue
        seasonal=[v for d,v in prior if d.weekday()==days[i].weekday()]
        reference=seasonal if len(seasonal)>=6 else [v for _,v in prior[-28:]]
        expected=median(reference)
        mad=median(abs(v-expected) for v in reference)
        floor=math.sqrt(max(expected,1)) if metric=='orders' else max(1,abs(expected)*.1)
        pooled=[v for _,v in prior]
        pooled_median=median(pooled)
        pooled_scale=1.4826*median(abs(v-pooled_median) for v in pooled)
        scale=max(1.4826*mad,pooled_scale,floor)
        score=(float(current)-expected)/scale
        if abs(score)>=threshold:
            flags.append({'date':days[i].isoformat(),'metric':metric,'actual':round(float(current),4),
                'expected':round(expected,4),'score':round(score,4),'direction':'high' if score>0 else 'low',
                'reference_points':len(reference)})
    return flags
