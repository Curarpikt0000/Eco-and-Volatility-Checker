import re,sys
from bs4 import BeautifulSoup
html=open(sys.argv[1],encoding='utf-8').read()
soup=BeautifulSoup(html,'lxml')
bad=[];n=0
for i,s in enumerate(soup.find_all('svg')):
    vb=(s.get('viewBox') or s.get('viewbox') or '') ; w=s.get('width','')
    try:
        W=float(vb.split()[2]) if vb else float(re.sub('[^0-9.]','',w) or 0)
    except: W=0
    datael=s.find_all(['polyline','rect','circle','path','line'])
    if W<100 or len(datael)<4: continue
    n+=1
    tips=len(s.find_all(attrs={'data-tip':True}))
    if tips==0:
        # 找标题
        t='';el=s
        for _ in range(8):
            el=el.parent
            if el is None:break
            h=el.find(['h2','h3','h4'])
            if h: t=h.get_text(' ',strip=True)[:50];break
        pl=len(s.find_all('polyline'));rc=len(s.find_all('rect'));pa=len(s.find_all('path'))
        anc=s.find_parent(attrs={'id':True})
        bad.append((i,anc.get('id') if anc else '',t,f'pl={pl} rect={rc} path={pa} W={W}'))
print('charts',n,'no-tip',len(bad))
for b in bad: print(b)
