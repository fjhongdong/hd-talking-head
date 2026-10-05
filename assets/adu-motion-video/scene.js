/* Structural layout adaptation of classic-performance@1.0.0/units/decompose-and-consolidate.js.
 * Source commit: 4d9777d799c73e4ed212b2ecb6ec6cece33f98a7.
 * Object algorithms and authored time constants are retained; text, coordinates,
 * typography and card geometry are rebound. No presenter, brand, rail or subtitle.
 */
(() => {
const F="-apple-system,'PingFang SC',sans-serif",B='#2462EA',L='#6d9bff',K='#0A0A0A';
const T=window.ADU_TEXTS;
if(!T)throw Error('Missing frozen Adu text bindings');
const e=(t,a,b)=>EZ.inout(pr(t,a,b));
const tx=(p,s,x,y,size=70,c=K,w=700,width=940)=>mk(p,`<div style="font:${w} ${size}px/1.13 ${F};letter-spacing:-1px;color:${c};width:${width}px;white-space:normal;overflow-wrap:break-word">${s}</div>`,x,y);
const cbox=(p,w,h,html='',bg='white',border='#ddd',r=25)=>mk(p,`<div style="width:${w}px;height:${h}px;position:relative;box-sizing:border-box;overflow:hidden;border-radius:${r}px;border:1.5px solid ${border};background:${bg};box-shadow:0 18px 46px rgba(0,0,0,.13)">${html}</div>`,0,0,{ax:.5,ay:.5});
const focus=(t,a,b)=>e(t,a,a+.34)*(1-e(t,b,b+.30));
const titleAt=(el,t,a,b)=>show(el,t,a,{k:'up',d:.4,dist:28,out:b,od:.2,ob:5});
const A=84.3,Z=101.666,sc=new Scene(A,Z,K,{grid:'gridD',trans:'flash',td:.24,fa:.3});
const lead=tx(sc.el,T['text-02'],70,220,70,'white');
const word=tx(sc.el,T['text-03'],260,530,176,L,800,680);
const echo=tx(sc.el,T['text-04'],70,980,42,'#aaa',550);
const behind=tx(sc.el,T['text-03'],90,425,280,'#151c28',800);
behind.style.zIndex='1';word.style.zIndex='3';lead.style.zIndex='3';echo.style.zIndex='3';
const galleryH=tx(sc.el,T['text-05'],70,210,70,'white');
const packedH=tx(sc.el,T['text-06'],70,210,70,'white');
const gallery=mk(sc.el,'<div style="position:relative;width:940px;height:900px"></div>',70,400);
const recipes=[
 [T['text-07'],'<div class="demo" style="position:absolute;inset:24px 30px 84px"><div class="big" style="font:800 52px '+F+';color:white">'+T['text-08']+'</div><div class="rule" style="height:8px;width:190px;background:#6d9bff;transform-origin:left;margin-top:10px"></div><div style="height:6px;width:235px;background:#555;margin-top:10px"></div></div>'],
 [T['text-09'],'<div class="demo" style="position:absolute;inset:24px 30px 84px;display:flex;align-items:center;justify-content:center;gap:15px">'+[0,1,2].map(i=>`<div class="block" style="width:67px;height:67px;background:${i===1?L:'#fff'};border-radius:13px"></div>`).join('')+'</div>'],
 [T['text-10'],'<div class="demo" style="position:absolute;left:30px;right:30px;top:24px;height:108px;border-radius:14px;overflow:hidden;background:#333"><div class="shot" style="position:absolute;inset:12px;border:3px solid #6d9bff;border-radius:8px"></div><div class="sweep" style="position:absolute;top:0;bottom:0;width:20px;background:#fff"></div></div>']
].map(([name,html])=>cbox(gallery,800,230,html+`<div style="position:absolute;left:30px;bottom:24px;font:650 42px ${F};color:white">${name}</div>`,'#171717','#383838'));
const file=cbox(sc.el,850,390,`<div style="position:absolute;left:33px;top:35px;font:500 30px ${F};color:#b6ceff">${T['text-11']}</div><div style="position:absolute;left:32px;top:105px;font:700 86px ${F};color:white">${T['text-12']}</div><div style="position:absolute;left:33px;right:33px;bottom:38px;font:500 34px/1.25 ${F};color:#dfebff;white-space:normal">${T['text-13']}</div>`,B,'#638fee');
const papers=[0,1,2].map(i=>cbox(sc.el,650,260,`<div style="position:absolute;left:34px;top:35px;font:600 35px ${F};color:#888">${T[['text-14','text-15','text-16'][i]]}</div><div style="position:absolute;left:34px;right:34px;top:112px;height:5px;background:#555;box-shadow:0 32px 0 #444,0 64px 0 #333"></div>`,'#1d1d1d','#3b3b3b'));
file.style.zIndex='20';
const saved=tx(sc.el,T['text-17'],70,1280,40,L,650);
sc.update=t=>{
 titleAt(lead,t,84.43,89.8);show(behind,t,86.55,{k:'zoom',out:89.8,o:.8,s:1+.015*e(t,86.55,89.7)});
 show(word,t,86.533,{k:'slam',d:.34,out:89.8});const hit=focus(t,87.933,88.1);word.style.transform+=` scale(${1+.035*hit})`;
 titleAt(echo,t,87.933,89.8);titleAt(galleryH,t,89.966,94.55);titleAt(packedH,t,94.7,Z+.2);
 place(gallery,{x:70-26*e(t,91.3,93.6),y:400,s:1+.018*e(t,90.4,94.2)});
 recipes.forEach((el,i)=>{
  const a=90.1+i*.35,selected=focus(t,90.4+i*1.28,91.48+i*1.28),any=focus(t,90.4,94.13),pack=e(t,95.0+i*.5,96.2+i*.5),inE=EZ.spring(pr(t,a,a+.65));
  el.style.zIndex=String(selected>.1?12:3+i);
  place(el,{x:lerp(470,470,pack),y:lerp(140+i*290,590,pack)-145*Math.sin(pack*Math.PI)-26*selected+70*(1-inE),s:(.94+.06*inE)*lerp(1+.15*selected-.06*any,.25,pack),o:pr(t,a,a+.2)*(1-pack)*(1-.43*(any-selected)),r:lerp([-4,2,5][i],0,selected)+pack*[-8,5,12][i]});
  el.firstChild.style.borderColor=selected>.1?L:'#383838';
 });
 recipes[0].querySelector('.rule').style.transform=`scaleX(${.25+.75*e(t,90.4,91.45)})`;
 recipes[0].querySelector('.big').style.transform=`translateY(${8*(1-e(t,90.2,91.2))}px)`;
 recipes[1].querySelectorAll('.block').forEach((q,i)=>q.style.transform=`translateY(${-23*Math.sin(clamp((t-91.6-i*.12)/.9)*Math.PI)}px) rotate(${12*Math.sin(clamp((t-91.6-i*.12)/.9)*Math.PI)}deg)`);
 recipes[2].querySelector('.shot').style.transform=`scale(${1+.16*e(t,92.95,93.65)})`;
 recipes[2].querySelector('.sweep').style.left=(-30+375*e(t,93.15,93.8))+'px';
 papers.forEach((p,i)=>show(p,t,96.2+i*.5,{k:'up',x:540+i*22-40*e(t,98.5,99.7),y:980-i*16,s:.82,r:-10+i*6,out:100.0,dist:85}));
 show(file,t,98.5,{k:'pop',x:540-20*e(t,98.5,99.7),y:980,s:.9+.035*e(t,99.0,101.5),d:.6});titleAt(saved,t,99.4,Z+.2);
};
sc.cam=t=>{const a=shake(t,86.533,.26,9),b=shake(t,87.933,.2,5);return{x:960,y:540,sx:a[0]+b[0],sy:a[1]+b[1],z:1+.008*e(t,90.2,94.3)};};
})();
