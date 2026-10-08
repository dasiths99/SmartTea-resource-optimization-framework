import re, subprocess, glob, os, pandas as pd
MONTHS=["JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE","JULY","AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"]
rows=[]; problems=[]
for f in sorted(glob.glob('raw/forbes_pdfs/*.pdf')):
    key=os.path.basename(f)[:-4]; y,m=key.split('-'); y=int(y); mi=MONTHS.index(m)+1
    t=subprocess.run(['pdftotext','-layout',f,'-'],capture_output=True,text=True).stdout
    got={}
    for el in ["HIGH","MEDIUM","LOW","GREEN TEA","TOTAL"]:
        mt=re.search(r'^\s*'+el+r'\s+([\d,]+)\s+([\d,]+)\s+\S+\s+\S+\s+([\d,]+)',t,re.M)
        if not mt: problems.append((key,el)); continue
        cur,p1,p2=[int(x.replace(',','')) for x in mt.groups()]
        got[el]=(cur,p1,p2)
    for el,(cur,p1,p2) in got.items():
        for yy,v,lag in [(y,cur,0),(y-1,p1,1),(y-2,p2,2)]:
            rows.append(dict(year=yy,month=mi,elevation=el.lower().replace(' ','_'),production_kg=v,source_report=f"{m.title()} {y}",report_lag_years=lag))
df=pd.DataFrame(rows)
# prefer the most recent report (lag 0, then 1, then 2) = latest revised figure
df=df.sort_values('report_lag_years').drop_duplicates(['year','month','elevation'],keep='first')
df=df.sort_values(['year','month','elevation']).reset_index(drop=True)
# consistency check: high+medium+low+green == total
w=df.pivot_table(index=['year','month'],columns='elevation',values='production_kg')
w['check_diff']=w[['high','medium','low','green_tea']].sum(axis=1)-w['total']
print("problems:",problems)
print("months covered:",len(w), "years:", sorted(df.year.unique()))
print("max |sum-total| kg:", w.check_diff.abs().max())
print(w.groupby(level=0)[['high','medium','low','total']].sum().div(1e6).round(1))
print("count per year:", w.groupby(level=0).size().to_dict())
df.to_csv('sl_tea_production_monthly_by_elevation.csv',index=False)
