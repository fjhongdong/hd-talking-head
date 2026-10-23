import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./line-by-line-slide.contract.json";
import type {CandidateScene, CardContext, CardRenderProps, CardSfxCue, PreparedCard} from "../production-card-root";

export const cardMeta = {card_id:"line-by-line-slide",api_version:1} as const;
export const candidateScene = contract.scene as CandidateScene;
export const sceneInputSlots = contract.scene_input_slots as ReadonlyArray<string>;
export const sfxCues = contract.sfx_cues as ReadonlyArray<CardSfxCue>;
export const animationFrames = {enterStarts: [7, 10, 14], enterTravelEnds: [18, 22, 25], enterOpacityEnds: [29, 32, 35], exitStarts: [69, 70, 72], exitTravelStarts: [75, 77, 80], exitEnds: [83, 85, 86]} as const;
export const layoutRects = {presenter:contract.geometry.presenter_rect,text:contract.geometry.text_rect} as const;

type LineSlidePrepared = PreparedCard & {lines:string[];ink:string};
const COLOR=/^#[0-9a-fA-F]{6}$/;
const exactObject=(value:unknown,keys:string[])=>value!==null&&typeof value==="object"&&!Array.isArray(value)&&Object.keys(value).sort().join(",")===[...keys].sort().join(",");
const textLength=(value:unknown)=>typeof value==="string"?Array.from(value.trim()).length:0;
const clamp01=(value:number)=>Math.max(0,Math.min(1,value));
const lerp=(from:number,to:number,p:number)=>from+(to-from)*p;
function cubicBezier(x1:number,y1:number,x2:number,y2:number){const cx=3*x1,bx=3*(x2-x1)-cx,ax=1-cx-bx;const cy=3*y1,by=3*(y2-y1)-cy,ay=1-cy-by;return (p:number)=>{let u=clamp01(p);for(let i=0;i<8;i++){const e=((ax*u+bx)*u+cx)*u-p;if(Math.abs(e)<1e-6)break;const d=(3*ax*u+2*bx)*u+cx;if(Math.abs(d)<1e-6)break;u-=e/d;}u=clamp01(u);return((ay*u+by)*u+cy)*u;};}
const ENTER_EASE=cubicBezier(0.22,1,0.36,1);
const EXIT_EASE=cubicBezier(0.64,0,0.78,0);
const progress=(frame:number,start:number,end:number,ease:(value:number)=>number)=>ease(clamp01((frame-start)/(end-start)));

export const prepareCard=(raw:unknown,context:CardContext):LineSlidePrepared=>{
  if(!exactObject(raw,["ink","lines"]))throw new Error("line-by-line-slide input is invalid");
  const input=raw as Record<string,unknown>;const lines=input.lines;const presenter=context.sceneInputMetadata?.presenter;
  if(!Array.isArray(lines)||lines.length!==3||lines.some((line)=>textLength(line)<4||textLength(line)>12)||typeof input.ink!=="string"||!COLOR.test(input.ink)||presenter?.width!==540||presenter.height!==600||context.width!==1080||context.height!==1920||context.fps!==24||context.durationInFrames!==87)throw new Error("line-by-line-slide content exceeds its approved capacity");
  return{lines:lines.map((line)=>(line as string).trim()),ink:input.ink};
};

export default function LineByLineSlide({prepared,animationLocalFrame,namespace,sceneInputs}:CardRenderProps<LineSlidePrepared>){
  const presenter=sceneInputs.presenter;if(!presenter)throw new Error("line-by-line-slide presenter is missing");
  return <AbsoluteFill data-talkcraft-card={cardMeta.card_id} data-talkcraft-scope={namespace} style={{background:"#ffffff",overflow:"hidden",fontFamily:'"PingFang SC", "Hiragino Sans GB", sans-serif'}}>
    <div data-track="text-zone" style={{position:"absolute",zIndex:3,left:layoutRects.text.x,top:layoutRects.text.y,width:layoutRects.text.width,height:layoutRects.text.height,display:"flex",alignItems:"center",justifyContent:"center"}}>
      <div style={{display:"inline-block",textAlign:"left",fontSize:78,fontWeight:620,lineHeight:1.35,letterSpacing:"-0.03em",color:prepared.ink}}>
        {prepared.lines.map((line,index)=>{const enterP=progress(animationLocalFrame,animationFrames.enterStarts[index],animationFrames.enterOpacityEnds[index],ENTER_EASE);const enterTravelP=progress(animationLocalFrame,animationFrames.enterStarts[index],animationFrames.enterTravelEnds[index],ENTER_EASE);const exitP=progress(animationLocalFrame,animationFrames.exitStarts[index],animationFrames.exitEnds[index],EXIT_EASE);const exitTravelP=progress(animationLocalFrame,animationFrames.exitTravelStarts[index],animationFrames.exitEnds[index],EXIT_EASE);const opacity = enterP * (1 - exitP);const xEnter=lerp(-61,0,enterTravelP);const xExit=lerp(0,61,exitTravelP);return <span key={index} data-track={`line-${index}`} style={{display:"block",whiteSpace:"nowrap",opacity,transformOrigin:"0% 50%",transform:`translateX(${xEnter + xExit}px)`}}>{line}</span>;})}
      </div>
    </div>
    <div data-track="presenter" data-alpha-source="libvpx-vp9" style={{position:"absolute",zIndex:2,left:layoutRects.presenter.x,top:layoutRects.presenter.y,width:layoutRects.presenter.width,height:layoutRects.presenter.height,overflow:"hidden"}}>{presenter}</div>
  </AbsoluteFill>;
}
