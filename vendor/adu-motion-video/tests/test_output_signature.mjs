import test from 'node:test';
import assert from 'node:assert/strict';
import {signatureWindows, signatureAssets} from '../scripts/output-signature.mjs';
test('a long film never ends with a truncated signature window',()=>{
  for(const duration of [14,20,36,40,43.49,44,60,65,180,600]){
    const windows=signatureWindows(duration);
    assert.ok(windows.length>0);
    for(const w of windows){assert.equal(w.end-w.start,5.5);assert.ok(w.end<=duration);assert.equal(w.fade,.4);}
    assert.equal(windows[0].start,8);
    windows.slice(1).forEach((w,i)=>assert.equal(w.start-windows[i].start,30));
  }
});
test('short films retain a bounded, nonempty animation and both fades',()=>{
  for(const duration of [.2,1,3,6,8,13.9])for(const w of signatureWindows(duration)){
    assert.ok(w.start>=0&&w.end> w.start&&w.end<duration);
    assert.ok(w.fade>0&&w.fade*2<=w.end-w.start);
  }
});
test('invalid duration fails before asset decoding or browser work',()=>{
  for(const n of [0,-1,NaN,Infinity])assert.throws(()=>signatureWindows(n));
  assert.deepEqual(Object.keys(signatureAssets),['lighter','path']);
});
