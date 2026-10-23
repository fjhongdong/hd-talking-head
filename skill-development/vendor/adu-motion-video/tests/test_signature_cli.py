"""Normal legacy renderer: old-project fallback, opt-out, tamper rejection."""
import hashlib,json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('node') and shutil.which('ffmpeg'), 'requires Node and FFmpeg')
class SignatureCliTests(unittest.TestCase):
 def test_legacy_project_is_unchanged_and_explicit_opt_out_works(self):
  with tempfile.TemporaryDirectory(prefix='adu-signature-cli-') as tmp:
   p=Path(tmp);entry=p/'index.html'
   entry.write_text('<style>body{margin:0}#stage{width:320px;height:180px;background:white}</style><div id=stage></div><script>window.END=15;window.renderAt=t=>{};window.READY=Promise.resolve();</script>')
   before=hashlib.sha256(entry.read_bytes()).hexdigest()
   command=['node',str(ROOT/'scripts/render_project.mjs'),str(entry),'--width','320','--height','180','--times','1,9,10']
   result=subprocess.run(command+['--stills-dir',str(p/'enabled')],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   data=json.loads(result.stdout);self.assertEqual(data['signature']['duration'],15)
   self.assertEqual(data['signature']['windows'],[dict(start=8,end=13.5,fade=.4)])
   frames=list((p/'enabled').glob('*.png'));self.assertEqual(len(frames),3)
   self.assertNotEqual(frames[1].read_bytes(),frames[2].read_bytes())
   self.assertEqual(hashlib.sha256(entry.read_bytes()).hexdigest(),before)
   self.assertFalse((p/'brand').exists());self.assertFalse((p/'output-signature.json').exists())
   (p/'output-signature.json').write_text(json.dumps(dict(schema='adu-output-signature/1',enabled=False)))
   result=subprocess.run(command+['--stills-dir',str(p/'disabled')],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['signature'],dict(enabled=False))
   self.assertNotEqual(next((p/'enabled').glob('frame_000*')).read_bytes(),next((p/'disabled').glob('frame_000*')).read_bytes())
 def test_modified_asset_fails_without_publishing_or_editing_project(self):
  with tempfile.TemporaryDirectory(prefix='adu-signature-cli-') as tmp:
   p=Path(tmp);(p/'brand').mkdir();entry=p/'index.html'
   entry.write_text('<div id=stage></div><script>window.END=15;window.renderAt=t=>{};window.READY=Promise.resolve();</script>')
   (p/'output-signature.json').write_text(json.dumps(dict(schema='adu-output-signature/1',enabled=True,assets='brand')))
   for source in (ROOT/'template/brand').glob('*.webm'):shutil.copy2(source,p/'brand'/source.name)
   with (p/'brand/motiongit-circle-lighter.webm').open('ab') as f:f.write(b'changed')
   result=subprocess.run(['node',str(ROOT/'scripts/render_project.mjs'),str(entry),'--stills-dir',str(p/'frames'),'--times','9'],capture_output=True,text=True)
   self.assertNotEqual(result.returncode,0);self.assertIn('Official signature asset changed',result.stderr);self.assertFalse((p/'frames').exists())
if __name__=='__main__':unittest.main()
