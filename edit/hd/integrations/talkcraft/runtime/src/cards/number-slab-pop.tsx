import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./number-slab-pop.contract.json";
import type {CandidateScene,CardContext,CardRenderProps,CardSfxCue,PreparedCard} from "../production-card-root";
export const cardMeta={card_id:"number-slab-pop",api_version:1} as const;
export const candidateScene=contract.scene as CandidateScene;
export const sceneInputSlots=contract.scene_input_slots as string[];
export const sfxCues=contract.sfx_cues as CardSfxCue[];
type P=PreparedCard&{title:string;items:string[];accent:string};
export const prepareCard=(raw:unknown,c:CardContext):P=>{if(!raw||typeof raw!=="object"||Array.isArray(raw))throw Error("invalid raw");const r=raw as Record<string,unknown>,p=c.sceneInputMetadata?.presenter;if(typeof r.title!=="string"||!Array.isArray(r.items)||r.items.length<2||r.items.length>6||r.items.some(x=>typeof x!=="string")||typeof r.accent!=="string"||!/^#[0-9a-f]{6}$/i.test(r.accent)||c.width!==1080||c.height!==1920||c.fps!==24||c.durationInFrames!==96||p?.width!==540||p.height!==600)throw Error("capacity");return{title:r.title.trim(),items:(r.items as string[]).map(x=>x.trim()),accent:r.accent};};
export default function Card({prepared:p,animationLocalFrame:f,sceneInputs}:CardRenderProps<P>){return <AbsoluteFill style={{background:"#f7f7f5",fontFamily:"sans-serif",color:"#1d1d1f",overflow:"hidden"}}><div style={{position:"absolute",left:70,top:230,width:940,textAlign:"center"}}><h1>{p.title}</h1><div style={{margin:40,padding:35,background:p.accent,color:"white",borderRadius:25,fontSize:140,fontWeight:850,transform:"scale("+Math.min(1.08,.7+(f-8)/35)+")"}}>67%</div><div style={{fontSize:42}}>较去年增长</div></div><div style={{position:"absolute",left:210,top:1000,width:660,height:730}}>{sceneInputs.presenter}</div></AbsoluteFill>}

