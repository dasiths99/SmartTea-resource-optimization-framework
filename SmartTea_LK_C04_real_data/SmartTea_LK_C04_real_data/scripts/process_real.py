import pandas as pd, numpy as np, json, io
U='/mnt/user-data/uploads/Downloads/'
EST=pd.DataFrame([["E01","Nuwara Eliya","up",6.97,80.78],["E02","Hatton / Dimbula","up",6.89,80.60],["E03","Kandy","mid",7.25,80.65],
                  ["E04","Ratnapura","low",6.68,80.40],["E05","Deniyaya / Matara","low",6.34,80.56]],
                 columns=['estate_id','region','agro_zone','query_lat','query_lon'])
# ---- hourly ERA5 ----
h=pd.read_csv(U+'smarttea_openmeteo_era5_hourly_2021_2025.csv',parse_dates=['datetime_local'])
for c in ['soil_moisture_0_to_7cm','soil_moisture_7_to_28cm','soil_moisture_28_to_100cm']:
    h[c]=(h[c]*100).round(1)
ren={'temperature_2m':'temp_c','relative_humidity_2m':'humidity_pct','dew_point_2m':'dew_point_c','precipitation':'precip_mm','rain':'rain_mm',
     'cloud_cover':'cloud_cover_pct','wind_speed_10m':'wind_speed_10m_ms','wind_gusts_10m':'wind_gust_10m_ms','shortwave_radiation':'solar_radiation_wm2',
     'sunshine_duration':'sunshine_s','et0_fao_evapotranspiration':'et0_mm','vapour_pressure_deficit':'vpd_kpa','soil_temperature_0_to_7cm':'soil_temp_0_7cm_c',
     'soil_moisture_0_to_7cm':'soil_moisture_0_7cm_pct','soil_moisture_7_to_28cm':'soil_moisture_7_28cm_pct','soil_moisture_28_to_100cm':'soil_moisture_28_100cm_pct'}
h=h.rename(columns=ren)
est_meta=h.groupby('estate_id')[['grid_lat','grid_lon','grid_elevation_m']].first().reset_index()
h=h.drop(columns=['region','grid_lat','grid_lon','grid_elevation_m'])
h.to_csv('out/01_weather_hourly_era5_2021_2025.csv',index=False)
# ---- daily ----
h['date']=h.datetime_local.dt.date
g=h.groupby(['estate_id','date'])
d=pd.DataFrame({
 'rain_mm':g.precip_mm.sum().round(1),'rain_hours':g.precip_mm.apply(lambda s:(s>=0.1).sum()),
 'temp_min_c':g.temp_c.min(),'temp_mean_c':g.temp_c.mean().round(1),'temp_max_c':g.temp_c.max(),
 'humidity_mean_pct':g.humidity_pct.mean().round(1),'humidity_min_pct':g.humidity_pct.min(),
 'cloud_cover_mean_pct':g.cloud_cover_pct.mean().round(1),
 'wind_mean_ms':g.wind_speed_10m_ms.mean().round(2),'wind_max_ms':g.wind_speed_10m_ms.max(),'gust_max_ms':g.wind_gust_10m_ms.max(),
 'solar_radiation_mj_m2':(g.solar_radiation_wm2.sum()*3600/1e6).round(2),'sunshine_hours':(g.sunshine_s.sum()/3600).round(2),
 'et0_mm':g.et0_mm.sum().round(2),'vpd_mean_kpa':g.vpd_kpa.mean().round(3),
 'soil_temp_0_7cm_c':g.soil_temp_0_7cm_c.mean().round(1),
 'soil_moisture_0_7cm_pct':g.soil_moisture_0_7cm_pct.mean().round(1),'soil_moisture_7_28cm_pct':g.soil_moisture_7_28cm_pct.mean().round(1),
 'soil_moisture_28_100cm_pct':g.soil_moisture_28_100cm_pct.mean().round(1),
}).reset_index()
d.to_csv('out/02_weather_daily_era5_2021_2025.csv',index=False)
print('daily',d.shape); print(d.assign(year=pd.to_datetime(d.date).dt.year).groupby(['estate_id','year']).rain_mm.sum().unstack().round(0))
print(d.groupby('estate_id')[['temp_mean_c','humidity_mean_pct','solar_radiation_mj_m2','sunshine_hours','et0_mm','soil_moisture_7_28cm_pct']].mean().round(2))
# ---- forecast vs actual ----
fc=pd.read_csv(U+'smarttea_openmeteo_forecast_leadtimes_2024_2025.csv',parse_dates=['datetime_local'])
fc=fc.merge(h[['estate_id','datetime_local','precip_mm','temp_c']].rename(columns={'precip_mm':'precip_era5_actual_mm','temp_c':'temp_era5_actual_c'}),on=['estate_id','datetime_local'],how='left')
fc.to_csv('out/03_forecast_vs_actual_hourly_2024_2025.csv',index=False)
fc['date']=fc.datetime_local.dt.date
fd=fc.groupby(['estate_id','date']).agg(hours=('precip_era5_actual_mm','size'),
     rain_actual_era5_mm=('precip_era5_actual_mm','sum'),rain_fc_0day_mm=('precip_forecast_0day_mm','sum'),
     rain_fc_1day_ahead_mm=('precip_forecast_1day_ahead_mm','sum'),rain_fc_2day_ahead_mm=('precip_forecast_2day_ahead_mm','sum'),
     rain_fc_3day_ahead_mm=('precip_forecast_3day_ahead_mm','sum'),rain_fc_4day_ahead_mm=('precip_forecast_4day_ahead_mm','sum')).reset_index()
fd=fd[fd.hours==24].drop(columns='hours').round(1)
fd.to_csv('out/04_forecast_vs_actual_daily_2024_2025.csv',index=False)
print('forecast daily rows',len(fd))
for k in ['0day','1day_ahead','2day_ahead','3day_ahead','4day_ahead']:
    e=fd['rain_fc_'+k+'_mm']-fd.rain_actual_era5_mm
    hit=((fd['rain_fc_'+k+'_mm']>5)==(fd.rain_actual_era5_mm>5)).mean()
    print(f"  lead {k:11s} MAE {e.abs().mean():.1f} mm/day  bias {e.mean():+.1f}  rain>5mm agreement {hit:.2%}  corr {fd['rain_fc_'+k+'_mm'].corr(fd.rain_actual_era5_mm):.2f}")
# ---- NASA POWER ----
npj=json.load(open(U+'smarttea_nasa_power_daily_2021_2025.json'))
parts=[]
for eid,t in npj.items():
    body=t.split('-END HEADER-')[1].strip()
    df=pd.read_csv(io.StringIO(body)); df.insert(0,'estate_id',eid)
    parts.append(df)
npw=pd.concat(parts).replace(-999,np.nan)
npw.insert(1,'date',pd.to_datetime(npw.YEAR.astype(str),format='%Y')+pd.to_timedelta(npw.DOY-1,unit='D'))
npw['date']=npw.date.dt.date
npw=npw.drop(columns=['YEAR','DOY']).rename(columns=str.lower)
npw.to_csv('out/05_nasa_power_daily_2021_2025.csv',index=False)
cmp=npw.merge(d[['estate_id','date','rain_mm']],on=['estate_id','date'])
print('NASA vs ERA5 daily rain corr by estate:',cmp.groupby('estate_id').apply(lambda x:round(x.prectotcorr.corr(x.rain_mm),2),include_groups=False).to_dict())
print('NASA annual rain:',cmp.assign(y=pd.to_datetime(cmp.date).dt.year).groupby(['estate_id','y']).prectotcorr.sum().unstack().round(0).to_dict('index'))
est=EST.merge(est_meta,on='estate_id')
est.to_csv('out/00_estate_locations.csv',index=False); print(est)
