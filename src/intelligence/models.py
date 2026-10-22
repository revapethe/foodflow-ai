"""Leakage-safe daily forecasts. Model selection never observes the final test block."""
import math
from datetime import date,timedelta

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CANDIDATES = ('seasonal_naive','trailing_mean','ridge_autoregression')
LABELS = {'seasonal_naive':'Weekly seasonal naive','trailing_mean':'28-day trailing mean','ridge_autoregression':'Ridge autoregression'}
FEATURES = ['lag_1','lag_7','lag_14','lag_28','mean_7','mean_28','std_28','trend_years','weekday_sin','weekday_cos']
HORIZON, TEST_DAYS, CALIBRATION_DAYS, FOLD_DAYS, FOLDS = 14,28,28,14,3


def features(history, day, index):
    y=np.asarray(history,dtype=float)
    return [y[-1],y[-7],y[-14],y[-28],float(y[-7:].mean()),float(y[-28:].mean()),float(y[-28:].std()),index/365,
            math.sin(2*math.pi*day.weekday()/7),math.cos(2*math.pi*day.weekday()/7)]


def fit_state(name, history, days):
    if name=='trailing_mean':
        return {'name':name,'level':float(np.mean(history[-28:]))}
    if name=='seasonal_naive':
        return {'name':name}
    x=[features(history[:i],days[i],i) for i in range(28,len(history))]
    model=make_pipeline(StandardScaler(),Ridge(alpha=10,solver='svd'))
    model.fit(x,np.asarray(history[28:],dtype=float))
    scaler,regression=model.steps[0][1],model.steps[1][1]
    return {'name':name,'features':FEATURES,'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),
            'coef':regression.coef_.tolist(),'intercept':float(regression.intercept_),'alpha':10}


def predict_state(state, history, days, horizon):
    values=list(map(float,history));result=[]
    for offset in range(1,horizon+1):
        day=days[-1]+timedelta(days=offset)
        if state['name']=='seasonal_naive':
            predicted=values[-7]
        elif state['name']=='trailing_mean':
            predicted=state['level']
        else:
            x=np.asarray(features(values,day,len(values)))
            predicted=float(np.dot((x-np.asarray(state['mean']))/np.asarray(state['scale']),state['coef'])+state['intercept'])
        predicted=max(0.,predicted)
        if not math.isfinite(predicted):
            raise ValueError('Non-finite model prediction')
        values.append(predicted);result.append(predicted)
    return result


def predict(name, history, days, horizon):
    return predict_state(fit_state(name,history,days),history,days,horizon)


def metrics(actual, predictions):
    actual,predictions=np.asarray(actual,dtype=float),np.asarray(predictions,dtype=float)
    errors=actual-predictions
    return {'mae':round(float(np.abs(errors).mean()),6),'rmse':round(float(np.sqrt(np.mean(errors**2))),6),
            'wape_percent':round(float(np.abs(errors).sum()/actual.sum()*100),6) if actual.sum()>0 else None}


def evaluate(history, days):
    y=list(map(float,history));n=len(y)
    if len(days)!=n or any(not math.isfinite(v) or v<0 for v in y):
        raise ValueError('Daily demand must be finite and nonnegative with matching dates')
    if any(b-a!=timedelta(days=1) for a,b in zip(days,days[1:])):
        raise ValueError('Daily demand calendar must be contiguous')
    if n<180 or sum(v>0 for v in y)<28:
        return {'status':'insufficient_history','reason':'At least 180 calendar days and 28 days with orders are required.'}
    validation_start=n-TEST_DAYS-CALIBRATION_DAYS-FOLDS*FOLD_DAYS
    calibration_start=n-TEST_DAYS-CALIBRATION_DAYS
    test_start=n-TEST_DAYS
    scores={};folds=[]
    for name in CANDIDATES:
        actual,predicted=[],[]
        for cutoff in range(validation_start,calibration_start,FOLD_DAYS):
            predicted.extend(predict(name,y[:cutoff],days[:cutoff],FOLD_DAYS))
            actual.extend(y[cutoff:cutoff+FOLD_DAYS])
            if name==CANDIDATES[0]:
                folds.append({'train_end':days[cutoff-1].isoformat(),'validation_start':days[cutoff].isoformat(),'validation_end':days[cutoff+FOLD_DAYS-1].isoformat()})
        scores[name]={'label':LABELS[name],'validation':metrics(actual,predicted)}
    selected=min(CANDIDATES,key=lambda name:scores[name]['validation']['mae'])
    calibration=predict(selected,y[:calibration_start],days[:calibration_start],CALIBRATION_DAYS)
    residuals=np.sort(np.abs(np.asarray(y[calibration_start:test_start])-calibration))
    # Finite-sample empirical 80% absolute-error quantile; temporal dependence means
    # this is an error band, not a guaranteed calibrated probability interval.
    index=min(len(residuals)-1,math.ceil((len(residuals)+1)*.8)-1)
    width=float(residuals[index])
    test_predictions={name:predict(name,y[:test_start],days[:test_start],TEST_DAYS) for name in CANDIDATES}
    for name in CANDIDATES:
        scores[name]['test']=metrics(y[test_start:],test_predictions[name])
    heldout=[]
    for day,actual,p in zip(days[test_start:],y[test_start:],test_predictions[selected]):
        heldout.append({'date':day.isoformat(),'actual':actual,'prediction':float(p),'lower':max(0.,p-width),'upper':p+width})
    coverage=sum(max(0,p-width)<=actual<=p+width for actual,p in zip(y[test_start:],test_predictions[selected]))/TEST_DAYS*100
    state=fit_state(selected,y,days)
    future=predict_state(state,y,days,HORIZON)
    return {'status':'ready','selected_model':selected,'selected_label':LABELS[selected],
        'as_of':days[-1].isoformat(),'horizon_days':HORIZON,'training_days':n,'active_days':sum(v>0 for v in y),
        'selection_rule':'Lowest mean absolute error across three expanding-window 14-day validation folds; final test excluded.',
        'evaluation':{'candidates':scores,'folds':folds,'calibration_start':days[calibration_start].isoformat(),
            'calibration_end':days[test_start-1].isoformat(),'test_start':days[test_start].isoformat(),'test_end':days[-1].isoformat(),
            'test_days':TEST_DAYS,'error_band_nominal_percent':80,'error_band_width':round(width,6),
            'test_band_coverage_percent':round(coverage,6),'heldout':heldout},
        'model_state':state,
        'predictions':[{'date':(days[-1]+timedelta(days=i+1)).isoformat(),'prediction':round(p,6),
            'lower':round(max(0,p-width),6),'upper':round(p+width,6)} for i,p in enumerate(future)],
        'history':[{'date':d.isoformat(),'orders':int(v)} for d,v in zip(days[-28:],y[-28:])],
        'limitations':['Synthetic source data; evaluation does not establish real-world predictive value.',
            'Calendar gaps within warehouse coverage are treated as zero orders; upstream completeness is assumed.',
            'Forecast origin follows the dataset, not today. No observations exist beyond as_of.',
            'Error bands use 28 historical calibration errors; temporal dependence and small samples limit coverage guarantees.',
            'Market-level order forecasts do not measure stock, supplier lead times or inventory requirements.']}
