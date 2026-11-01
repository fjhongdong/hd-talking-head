import { seg, ss } from '/core/lib.js';
const canvas=document.getElementById('c'),ctx=canvas.getContext('2d'); window.DUR=6; window.READY=false;
const ink='#111',paper='#f2f0ea',signal='#ff5a00',line='#c9c7c0';
function L(){const w=innerWidth,h=innerHeight;return{w,h,m:w*.09,top:h*.1,row:h*.14,col:(w*.82)/3}}
function f(n,b=false){ctx.font=`${b?'700':'500'} ${n}px SourceHanLocal,sans-serif`;ctx.textBaseline='alphabetic'}
function tx(s,x,y,n,b=false,c=ink){f(n,b);ctx.fillStyle=c;ctx.fillText(s,x,y)} function rr(x,y,w,h,c){ctx.fillStyle=c;ctx.fillRect(x,y,w,h)}
function q(t,a,b){return ss(seg(t,a,b))} function draw(t){const a=L();canvas.width=a.w*devicePixelRatio;canvas.height=a.h*devicePixelRatio;ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);rr(0,0,a.w,a.h,paper);
 for(let i=0;i<4;i++)rr(a.m+i*a.col,a.top,2,a.h*.78,line); for(let i=0;i<4;i++)rr(a.m,a.top+i*a.row,a.w-2*a.m,2,line);
 const p=q(t,0,.5);ctx.save();ctx.beginPath();ctx.rect(a.m,a.top-a.h*.08,a.w*.8,a.h*.14);ctx.clip();tx('先按语义',a.m,a.top+a.h*.02*p,Math.max(72,a.w*.09),true);ctx.restore();
 const words=[['数字','数据模板'],['比较','对照模板'],['流程','步骤模板']]; words.forEach((r,i)=>{const y=a.top+a.row*(i+1),u=q(t,.45+i*.3,.95+i*.3);const x=a.m-(1-u)*a.w*.35;tx(r[0],x,y,Math.max(64,a.w*.07),true);tx(r[1],x+a.col*.95,y,Math.max(64,a.w*.055),true);rr(x+a.col*.82,y+12,a.col*.08,4,signal)});
 const ch=['官方','本地','生成']; ch.forEach((s,i)=>{const y=a.top+a.row*3.55,x=a.m+i*a.col,u=q(t,1.7+i*.2,2.25+i*.2);rr(x,y,a.col*.75*u,a.row*.42,i===1?signal:'#fff');if(u>.01)tx(s,x+16,y+a.row*.29,Math.max(64,a.w*.06),true,i===1?'#fff':ink)});
 const u=q(t,2.2,2.5); if(u>.01){tx('多渠道',a.m,a.top+a.row*4.45,Math.max(70,a.w*.075),true);tx('多模板',a.m+a.col*1.5,a.top+a.row*4.45,Math.max(70,a.w*.075),true);rr(a.m,a.top+a.row*4.58,a.w*.68*u,4,signal)} }
window.render=t=>draw(Math.max(0,Math.min(window.DUR,t)));
window.TEXTS=t=>{const a=L(),v=Math.max(0,Math.min(window.DUR,t)),o=[];const add=(id,text,x0,y0,x1,y1,at)=>{if(v>=at)o.push({id,text,x0,y0,x1,y1})};add('title','先按语义',a.m,a.top-a.h*.08,a.m+a.w*.65,a.top+a.h*.07,0);[['数字','数据模板'],['比较','对照模板'],['流程','步骤模板']].forEach((r,i)=>{const y=a.top+a.row*(i+1);add('sem'+i,r[0],a.m,y-a.h*.08,a.m+a.col*.65,y+.02*a.h,.45+i*.3);add('tpl'+i,r[1],a.m+a.col*.95,y-a.h*.08,a.m+a.col*1.8,y+.02*a.h,.45+i*.3)});['官方','本地','生成'].forEach((s,i)=>add('ch'+i,s,a.m+i*a.col,a.top+a.row*3.5,a.m+i*a.col+a.col*.75,a.top+a.row*4.05,1.7+i*.2));add('channels','多渠道',a.m,a.top+a.row*4.32,a.m+a.col,a.top+a.row*4.58,2.2);add('templates','多模板',a.m+a.col*1.5,a.top+a.row*4.32,a.m+a.col*2.5,a.top+a.row*4.58,2.2);return o};
Promise.all([document.fonts.load('700 96px SourceHanLocal'),document.fonts.load('500 64px SourceHanLocal')]).then(()=>document.fonts.ready).then(()=>{window.READY=true;draw(0)});
