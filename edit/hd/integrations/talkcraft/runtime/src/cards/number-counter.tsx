import React from "react";
import {AbsoluteFill} from "remotion";
import contract from "./number-counter.contract.json";
import type {CandidateScene,CardContext,CardRenderProps,CardSfxCue,PreparedCard} from "../production-card-root";
export const cardMeta={card_id:"number-counter",api_version:1} as const;
export const candidateScene=contract.scene as CandidateScene;
export const sceneInputSlots=contract.scene_input_slots as string[];
export const sfxCues=contract.sfx_cues as CardSfxCue[];
type P=PreparedCard&{title:string;items:string[];accent:string};
export const prepareCard=(raw:unknown,c:CardContext):P=>{if(!raw||typeof raw!=="object"||Array.isArray(raw))throw Error("invalid raw");const r=raw as Record<string,unknown>,p=c.sceneInputMetadata?.presenter;if(typeof r.title!=="string"||!Array.isArray(r.items)||r.items.length<2||r.items.length>6||r.items.some(x=>typeof x!=="string")||typeof r.accent!=="string"||!/^#[0-9a-f]{6}$/i.test(r.accent)||c.width!==1080||c.height!==1920||c.fps!==24||c.durationInFrames!==96||p?.width!==540||p.height!==600)throw Error("capacity");return{title:r.title.trim(),items:(r.items as string[]).map(x=>x.trim()),accent:r.accent};};
export default function Card({prepared:p,animationLocalFrame:f,sceneInputs}:CardRenderProps<P>){return <AbsoluteFill style={{background:"#f7f7f5",fontFamily:"sans-serif",color:"#1d1d1f",overflow:"hidden"}}><div style={{position:"absolute",left:70,top:220,width:940}}><h1>{p.title}</h1><div style={{fontSize:104,fontWeight:800}}>{Math.floor(3000000000*Math.min(1,Math.max(0,(f-8)/42))).toLocaleString()}</div><div style={{fontSize:36,color:p.accent}}>↑ 45%　万元 / 天</div><div style={{display:"flex",marginTop:55}}>{["8","2","1","9"].map((d,i)=><div key={i} style={{width:110,height:130,margin:8,overflow:"hidden",border:"2px solid #ddd",borderRadius:16,fontSize:92,textAlign:"center",lineHeight:"130px",transform:"translateY("+Math.max(0,1-(f-25-i*4)/18)*130+"px)"}}>{d}</div>)}</div></div><div style={{position:"absolute",left:210,top:1000,width:660,height:730}}>{sceneInputs.presenter}</div></AbsoluteFill>}

