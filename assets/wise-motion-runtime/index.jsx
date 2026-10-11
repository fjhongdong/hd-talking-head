// Static director labels only. Every moving card is unmodified Wise orbit.
import React, {useEffect, useState} from 'react';
import {AbsoluteFill, Composition, Sequence, cancelRender, continueRender,
  delayRender, registerRoot, staticFile} from 'remotion';
import {WiseMotionEffect} from 'wise-motion';

const ink = '#222226';
const accent = '#d54a19';
const Scene = ({title, context_labels, layers, theme, composition}) => {
  const [handle] = useState(() => delayRender('Wise portrait static Chinese font'));
  useEffect(() => {
    let active = true;
    const fonts = [400, 700].map(weight => new FontFace('WisePortrait',
      `url("${staticFile(`wise-motion/catalog/fonts/SourceHanSansSC-${weight === 700 ? 'Bold' : 'Regular'}.woff2`)}")`,
      {weight: String(weight)}));
    Promise.all(fonts.map(font => font.load())).then(loaded => {
      if (!active) return;
      loaded.forEach(font => document.fonts.add(font));
      continueRender(handle);
    }).catch(error => {if (active) cancelRender(error);});
    return () => {active = false;};
  }, [handle]);
  return <AbsoluteFill style={{backgroundColor: '#f7f5f0', color: ink,
    fontFamily: 'WisePortrait', fontWeight: 400}}>
    <div style={{position: 'absolute', left: 80, top: 88, fontSize: 27,
      letterSpacing: 4, color: accent, fontWeight: 700}}>不只是一次问答</div>
    <div style={{position:'absolute',left:80,top:250,fontSize:76,fontWeight:700}}>{title}</div>
    <div style={{position:'absolute',left:80,top:1080,fontSize:29,color:'#67646b'}}>持续关注</div>
    {context_labels.map((label, i) => <div key={i} style={{position:'absolute',
      left:80,top:1150+i*66,fontSize:43,fontWeight:700,color:ink}}>{label}</div>)}
    {layers.map((layer, i) => {
      return <Sequence key={i} from={layer.from} durationInFrames={composition.frames} layout="none">
        <div style={{position: 'absolute', left: layer.layout.x, top: layer.layout.y}}>
          <WiseMotionEffect effectId={layer.id} content={layer.content} speed={layer.speed}
            theme={theme} transparent={layer.transparent} includeAudio={false}
            width={layer.layout.width} height={layer.layout.height}/>
        </div>
      </Sequence>;
    })}
    <div style={{position:'absolute',left:493,top:714,fontSize:62,fontWeight:700,
      lineHeight:'76px',color:accent}}>AI</div>
  </AbsoluteFill>;
};
const Root = () => <Composition id="WiseNative" component={Scene}
  durationInFrames={50} fps={24} width={1080} height={1920}
  calculateMetadata={({props}) => ({durationInFrames: props.composition.frames})}/>;
registerRoot(Root);
