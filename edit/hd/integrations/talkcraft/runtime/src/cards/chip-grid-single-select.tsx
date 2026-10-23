import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./chip-grid-single-select.contract.json";
import type {CandidateScene,CardContext,CardRenderProps,CardSfxCue,PreparedCard} from "../production-card-root";
export const cardMeta={card_id:"chip-grid-single-select",api_version:1} as const;
export const candidateScene=contract.scene as CandidateScene; export const sceneInputSlots=contract.scene_input_slots as string[]; export const sfxCues=contract.sfx_cues as CardSfxCue[];
type P=PreparedCard&{title:string;items:string[];accent:string};
export const prepareCard=(raw:unknown,c:CardContext):P=>{const r=raw as Record<string,unknown>,p=c.sceneInputMetadata?.presenter;if(!r||typeof r.title!=="string"||!Array.isArray(r.items)||r.items.length<2||r.items.length>6||typeof r.accent!=="string"||!/^#[0-9a-f]{6}$/i.test(r.accent)||c.width!==1080||c.height!==1920||c.fps!==24||c.durationInFrames!==96||p?.width!==540||p.height!==600)throw Error("capacity");return{title:r.title.trim(),items:(r.items as string[]).map(x=>String(x).trim()),accent:r.accent};};
export default function Card({prepared:p,animationLocalFrame:f,sceneInputs}:CardRenderProps<P>){return <AbsoluteFill style={{background:"#f7f7f5",fontFamily:"sans-serif",color:"#1d1d1f",overflow:"hidden"}}><div style={{position:"absolute",left:70,top:190,width:940}}><h1>{p.title}</h1><div style={{display:"flex",flexWrap:"wrap",gap:22,marginTop:60}}>{p.items.map((x,i)=><div key={x} style={{padding:"28px 42px",borderRadius:50,border:"3px solid "+(i===2?p.accent:"#c9cbd1"),background:i===2&&f>28?p.accent:"#fff",color:i===2&&f>28?"#fff":"#1d1d1f",fontSize:38}}>{x}</div>)}</div></div><div style={{position:"absolute",left:210,top:1000,width:660,height:730}}>{sceneInputs.presenter}</div></AbsoluteFill>}
