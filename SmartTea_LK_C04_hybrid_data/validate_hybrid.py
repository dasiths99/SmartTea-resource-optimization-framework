import pandas as pd, numpy as np, xgboost as xgb, sys
from sklearn.linear_model import RidgeCV
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.model_selection import GroupKFold
D=sys.argv[1]; REAL=sys.argv[2] if len(sys.argv)>2 else None
res=[]
def fitall(X,y,tr,te,name):
    Xf=X.fillna(X[tr].median())
    for mname,m,XX in [("Ridge",RidgeCV(),Xf),("RandomForest",RandomForestRegressor(300,n_jobs=-1,random_state=0,min_samples_leaf=3),Xf),
                       ("XGBoost",xgb.XGBRegressor(n_estimators=600,learning_rate=0.03,max_depth=5,subsample=0.8,colsample_bytree=0.8),X)]:
        m.fit(XX[tr],y[tr]); p=m.predict(XX[te]); res.append((name,mname,round(r2_score(y[te],p),3),round(mean_absolute_error(y[te],p),2)))
yt=pd.read_csv(f'{D}/ml_yield_training.csv')
drop=['block_id','pluck_date','green_leaf_kg_per_ha','estate_id','green_leaf_kg_per_ha_per_day','aspect']
X=pd.get_dummies(yt.drop(columns=[c for c in drop if c in yt]),drop_first=True).astype(float); y=yt.green_leaf_kg_per_ha_per_day
yr=pd.to_datetime(yt.pluck_date).dt.year
fitall(X,y,yr<2025,yr==2025,"Yield: time split (test 2025)")
r2=[]
for tr,te in GroupKFold(5).split(X,y,yt.block_id):
    m=xgb.XGBRegressor(n_estimators=600,learning_rate=0.03,max_depth=5,subsample=0.8,colsample_bytree=0.8).fit(X.iloc[tr],y.iloc[tr]); r2.append(r2_score(y.iloc[te],m.predict(X.iloc[te])))
res.append(("Yield: unseen blocks (5-fold)","XGBoost",round(np.mean(r2),3),None))
rt=pd.read_csv(f'{D}/ml_runoff_training.csv'); yr=pd.to_datetime(rt.execution_datetime).dt.year
base=['intervention_id','block_id','execution_datetime','absorption_efficiency_pct','runoff_loss_est_pct','forecast_source','aspect']
act=[c for c in rt if c.startswith('rain_next')]; fcc=[c for c in rt if c.startswith('fc_rain_next')]
for label,dropcols in [("Runoff: actual rain after (hindsight)",fcc),("Runoff: forecast rain only (live-realistic)",act)]:
    if label.startswith("Runoff: forecast") and not fcc: continue
    Xr=pd.get_dummies(rt.drop(columns=[c for c in base+dropcols if c in rt]),drop_first=True).astype(float)
    fitall(Xr,rt.runoff_loss_est_pct,yr<2025,yr==2025,label)
out=pd.DataFrame(res,columns=['test','model','R2','MAE']); print(out.to_string(index=False))
if REAL:
    b=pd.read_csv(f'{D}/01_block_master.csv'); y4=pd.read_csv(f'{D}/04_yield_plucking_records.csv',parse_dates=['pluck_date'])
    y4=y4.merge(b[['block_id','agro_zone','area_ha']],on='block_id'); y4['kg']=y4.green_leaf_kg_per_ha*y4.area_ha
    y4['ym']=y4.pluck_date.dt.to_period('M')
    sim=y4.groupby(['agro_zone','ym']).kg.sum().reset_index(); sim['elevation']=sim.agro_zone.map({'up':'high','mid':'medium','low':'low'})
    nat=pd.read_csv(f'{REAL}/07_sl_tea_production_monthly_by_elevation_2021_2025.csv'); nat['ym']=pd.PeriodIndex.from_fields(year=nat.year,month=nat.month,freq='M')
    m=sim.merge(nat,on=['elevation','ym'])
    m['dim']=m.ym.dt.days_in_month; m['sim_d']=m.kg/m.dim; m['nat_d']=m.production_kg/m.dim; m['mon']=m.ym.dt.month
    print("\nSimulated vs national monthly production (per day):")
    for e,g in m.groupby('elevation'):
        g2=g[g.ym.dt.year!=2022]
        clim=g.groupby('mon')[['sim_d','nat_d']].mean()
        print(f"  {e:6s} monthly corr {g.sim_d.corr(g.nat_d):.2f} | excl. 2022 {g2.sim_d.corr(g2.nat_d):.2f} | seasonal-shape corr {clim.sim_d.corr(clim.nat_d):.2f}")
    s=pd.read_csv(f'{D}/03_sensor_readings_daily.csv'); w=pd.read_csv(f'{D}/02_weather_daily.csv')
    s=s.merge(b[['block_id','estate_id']],on='block_id').groupby(['estate_id','date']).soil_moisture_pct.mean().reset_index().merge(w[['estate_id','date','era5_soil_moisture_7_28cm_pct']],on=['estate_id','date'])
    print("Simulated soil moisture vs ERA5-Land (corr):",s.groupby('estate_id').apply(lambda x: round(x.soil_moisture_pct.corr(x.era5_soil_moisture_7_28cm_pct),2),include_groups=False).to_dict())
