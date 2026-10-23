import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {fileURLToPath} from "node:url";

const runtime=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"..");
const integration=path.resolve(runtime,"..");
const manifest=JSON.parse(fs.readFileSync(path.join(integration,"upstream-manifest.json"),"utf8"));
const cardsDir=path.join(runtime,"src/cards");
const casesDir=path.join(runtime,"qualification-cases");
const have=new Set(fs.readdirSync(cardsDir).filter((x)=>x.endsWith(".tsx")).map((x)=>x.slice(0,-4)));
const remaining=manifest.cards.map((x)=>x.card_id).filter((x)=>!have.has(x)||fs.readFileSync(path.join(cardsDir,`${x}.tsx`),"utf8").includes("candidate-generated"));
const sha=(p)=>crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
const labels={
  "caret-wipe-transition":["问题退场","答案接管"],"chevron-lower-third":["陈知远","内容系统顾问"],"color-slam-beat-card":["关键一步","形成闭环"],
  "cursor-locked-zoom":["锁定目标","放大细节"],"danmu-bubble-praise":["真实反馈","持续增长"],"doc-park-left-pill-deal":["资料归位","结论生成"],
  "douyin-follow-card":["关注账号","持续更新"],"host-card-glass-board":["工作流程","清晰呈现"],"host-shrink-to-chip":["人物让位","信息登场"],
  "info-card-assemble":["信息组装","完整成卡"],"line-carry-transition":["上一章节","下一章节"],"long-take-world":["连续空间","一路推进"],
  "lower-third-nameplate":["林工","AI内容导演"],"orbit-drift":["环绕观察","保持焦点"],"overexpose-flip-transition":["旧画面","新画面"],
  "parallel-items-with-host":["三个重点","并列展开"],"particle-weld-transition":["粒子聚合","完成换景"],"pip-zoom-box":["局部细节","同步放大"],
  "pullback-cool-transition":["拉开视野","进入新章"],"push-through-transition":["穿过界面","抵达结果"],"rack-focus-pair":["近景主体","远景主体"],
  "slow-pull-reveal":["从细节出发","看见全局"],"slow-push-in":["缓慢靠近","聚焦关键"],"split-60-40-story":["核心故事","三项结果"],
  "split-compare-slider":["调整之前","调整之后"],"stack-fan-out":["五个方案","依次展开"],"stage-keyframe-tour":["舞台巡游","逐点讲解"],
  "still-layout-relay":["版式接力","连续呈现"],"subscribe-cta":["订阅更新","不错过下一期"],"sway-parallax":["轻微摇摆","层次视差"],
  "tilt-3d-page":["页面倾转","空间展示"],"whip-pan-transition":["快速甩动","自然接景"],"word-relay-filmstrip":["关键词接力","形成叙事"],"x-follow-card":["关注动态","建立连接"]
};
for(const id of remaining){
  const upstream=path.join(integration,"upstream/template/cards",`${id}.tsx`);
  let source=fs.readFileSync(upstream,"utf8");
  const match=source.match(/export const meta = \{ width: \d+, height: \d+, fps: 30, durationInFrames: (\d+) \}/);
  const duration=Math.round(Number(match?.[1]??180)*24/30);
  source=source.replace(/const FPS = meta\.fps;/,"const FPS = 24;");
  source=source.replace(/export default function\s+[A-Za-z0-9_]+/,"function UpstreamCard");
  if(!source.includes("function UpstreamCard")) throw new Error(`default component unavailable: ${id}`);
  const [a,b]=labels[id]??["核心内容","完成结果"];
  const wrapper=`\nimport contract from "./${id}.contract.json";\nimport type {CandidateScene,CardContext,CardRenderProps,CardSfxCue} from "../production-card-root";\ntype Prepared={title:string;subtitle:string;accent:string};\n+export const cardMeta={card_id:"${id}",api_version:1} as const;export const candidateScene=contract.scene as CandidateScene;export const sceneInputSlots=contract.scene_input_slots as string[];export const sfxCues=contract.sfx_cues as CardSfxCue[];\n+export const prepareCard=(raw:unknown,c:CardContext):Prepared=>{const v=raw as Partial<Prepared>|null;if(!v||c.width!==1080||c.height!==1920||c.fps!==24||c.durationInFrames!==${duration}||typeof v.title!=="string"||v.title.length<2||v.title.length>12||typeof v.subtitle!=="string"||v.subtitle.length<2||v.subtitle.length>18||typeof v.accent!=="string"||!/^#[0-9A-Fa-f]{6}$/.test(v.accent))throw Error("${id} invalid input");return{title:v.title,subtitle:v.subtitle,accent:v.accent}};\n+export default function Card({prepared,sceneInputs}:CardRenderProps<Prepared>){const Demo=UpstreamCard as React.ComponentType<Record<string,unknown>>;return <AbsoluteFill className="candidate-generated" style={{background:"#fff",overflow:"hidden"}}><style>{\`.candidate-generated .host-badge,.candidate-generated .host-col,.candidate-generated .host-full{display:none!important}\`}</style><div style={{position:"absolute",left:0,top:90,width:1080,height:675,overflow:"hidden"}}><div style={{width:960,height:540,transform:"scale(1.25)",transformOrigin:"top left"}}><Demo/></div></div><div style={{position:"absolute",left:70,top:790,width:940,textAlign:"center",zIndex:8}}><div style={{fontSize:64,fontWeight:800,lineHeight:1.12,color:"#1d1d1f"}}>{prepared.title}</div><div style={{display:"inline-block",marginTop:18,padding:"10px 22px",borderRadius:999,background:prepared.accent,color:"#fff",fontSize:30,fontWeight:650}}>{prepared.subtitle}</div></div><div style={{position:"absolute",left:180,top:1040,width:720,height:780,zIndex:5}}>{sceneInputs.presenter}</div></AbsoluteFill>}\n`;
  const tsx=path.join(cardsDir,`${id}.tsx`);fs.writeFileSync(tsx,source+wrapper.replace(/\n\+/g,"\n"));
  const contract={schema_version:"talkcraft-card-contract/v1",card_id:id,scene:"full-frame",scene_input_slots:["presenter"],geometry:{demo_rect:{x:0,y:90,width:1080,height:675},title_rect:{x:70,y:790,width:940,height:170},presenter_rect:{x:180,y:1040,width:720,height:780},bottom_caption_safe_px:100},sfx_cues:[{cueId:"card-in",frame:10,anchor:"card-in",name:"ui-pop",assetKey:"talkcraft-ui-pop",volume:.28,playbackRate:1}]};
  const contractPath=path.join(cardsDir,`${id}.contract.json`);fs.writeFileSync(contractPath,JSON.stringify(contract,null,2)+"\n");
  const cue={cueId:"card-in",frame:10,anchor:"card-in",name:"ui-pop",assetKey:"talkcraft-ui-pop",src:"qualification/talkcraft-ui-pop.mp3",sha256:"e19e3e04563c470068ee8fd179fb4d0ac2a6e51724cb60fd2e92237c456eacd4",volume:.28,playbackRate:1};
  const make=(caseId,title,subtitle,accent)=>({case_id:caseId,duration_frames:duration,scene:{layout:"full-frame",presenterRect:null},presenter:null,scene_inputs:[{slot:"presenter",kind:"presenter-alpha",fixture_id:"alt-block-lines-presenter"}],sfx:[cue],raw:{title,subtitle,accent}});
  const cases={schema_version:"talkcraft-qualification-cases/v2",card_id:id,adapter_version:"1.0.0-candidate",implementation_sha256:sha(tsx),contract_sha256:sha(contractPath),cases:[make("contrast-a",a,b,"#007AFF"),make("contrast-b",`${a}对照`,`${b}升级`,"#FF375F")]};
  fs.writeFileSync(path.join(casesDir,`${id}.json`),JSON.stringify(cases,null,2)+"\n");
  console.log(`${id}\t${duration}`);
}
