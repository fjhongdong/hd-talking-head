"""Normalize approved direct media; the component executor owns source selection."""
from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import subprocess
import tempfile
import shutil

from .broll_component_executor import AdapterResult, ArtifactProbe, KindAdapter
from .contract_artifacts import sha256_file

_EXECUTORS = {'local_material': 'local-media', 'external_stock': 'external-stock',
              'official_material': 'official-media'}


def _fds(path):
    return (int(path.name),) if path.parent == Path('/dev/fd') else ()


def _video_info(ffprobe, path):
    result = subprocess.run([str(ffprobe), '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, text=True,
                            check=True, timeout=30, pass_fds=_fds(path))
    data = json.loads(result.stdout)
    videos = [stream for stream in data['streams'] if stream['codec_type'] == 'video']
    if len(videos) != 1:
        raise ValueError('Material must contain exactly one video stream')
    return data, videos[0]


def create_adapter(kind, media_type, ffmpeg_executable, ffprobe_executable):
    if kind not in _EXECUTORS or media_type not in {'image', 'video'}:
        raise ValueError('Unsupported direct material')
    ffmpeg, ffprobe = (Path(value).resolve(strict=True) for value in (ffmpeg_executable, ffprobe_executable))

    def invoke(context):
        source = context.source_path
        if (source is None or context.source_sha256 != context.component['sha256']
                or sha256_file(source) != context.source_sha256):
            raise ValueError('Approved material bytes changed')
        contract = context.component['artifact_contract']
        size = (contract['width'], contract['height'])
        applied_crop = None
        if media_type == 'image':
            from PIL import Image
            from .visual_strategy import official_portrait_crop
            with Image.open(source) as image:
                crop = official_portrait_crop(context.component) if kind == 'official_material' else None
                if crop:
                    if image.size != (crop['source_width'], crop['source_height']) or size != (1080, 1920):
                        raise ValueError('Official crop source dimensions or portrait output differ')
                    image = image.crop((crop['x'], crop['y'], crop['x'] + crop['width'], crop['y'] + crop['height']))
                    image = image.resize(size, Image.Resampling.LANCZOS)
                    applied_crop = crop
                elif image.size != size:
                    raise ValueError('Material binding must use its actual source dimensions')
                image.convert('RGBA' if contract['alpha'] else 'RGB').save(context.staging_path, format='PNG')
        else:
            _data, video = _video_info(ffprobe, source)
            if (video['width'], video['height']) != size:
                raise ValueError('Material binding must use its actual source dimensions')
            if contract['alpha']:
                raise ValueError('Direct video must use the opaque material contract')
            copy_video = (video['codec_name'] == 'h264' and video['pix_fmt'] == 'yuv420p'
                          and Fraction(video['avg_frame_rate']) == contract['fps']
                          and Fraction(video['r_frame_rate']) == contract['fps'])
            encoding = ['-c:v', 'copy'] if copy_video else [
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', str(contract['fps'])]
            with tempfile.TemporaryDirectory(prefix='hd-material-') as temporary:
                output = Path(temporary) / 'normalized.mp4'
                subprocess.run([str(ffmpeg), '-v', 'error', '-nostdin', '-y', '-i', str(source),
                                '-map', '0:v:0', '-an', *encoding, '-movflags', '+faststart',
                                '-f', 'mp4', str(output)], pass_fds=_fds(source),
                               capture_output=True, check=True, timeout=120)
                with output.open('rb') as src, context.staging_path.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
        return AdapterResult(invocation_evidence={'source_sha256': context.source_sha256,
            'external_requests': 0, 'source_preserved': True,
            **({'portrait_crop': applied_crop, 'output_canvas': list(size)} if applied_crop else {})},
            qa={'passed': True, 'checks': ['approved source identity checked; explicit official crop or original dimensions retained']})

    identity = sha256_file(Path(__file__)) + ':' + sha256_file(ffmpeg)
    return KindAdapter(kind=kind, approved_executor=_EXECUTORS[kind],
                       adapter_id='direct-material-' + media_type, adapter_version=identity,
                       artifact_media_type=media_type, invoke=invoke)


def create_artifact_probe(*, ffprobe_executable):
    ffprobe = Path(ffprobe_executable).resolve(strict=True)

    def probe(path, media_type, contract):
        if media_type == 'image':
            from PIL import Image
            with Image.open(path) as image:
                if image.format != 'PNG' or image.mode not in {'RGB', 'RGBA'}:
                    raise ValueError('Material image must be an RGB/RGBA PNG')
                return {'media_type': 'image', 'container': 'png', 'codec': 'png',
                        'pixel_format': 'rgba' if image.mode == 'RGBA' else 'rgb24',
                        'alpha': image.mode == 'RGBA', 'width': image.width, 'height': image.height,
                        'fps': None, 'frame_count': 1, 'duration': None}
        data, stream = _video_info(ffprobe, path)
        if len(data['streams']) != 1:
            raise ValueError('Visual artifact must have no audio or other streams')
        fps = Fraction(stream['avg_frame_rate'])
        if fps <= 0 or Fraction(stream['r_frame_rate']) != fps:
            raise ValueError('Visual artifact must have a constant frame rate')
        formats = data['format']['format_name'].split(',')
        codec, pixel = stream['codec_name'], stream['pix_fmt']
        alpha = pixel in {'yuva444p10le', 'yuva444p12le', 'argb'}
        container = 'mov' if alpha and 'mov' in formats else ('mp4' if 'mp4' in formats else formats[0])
        # ffprobe reports the ProRes codec name, while our renderer contract names its encoder.
        if codec == 'prores' and pixel in {'yuva444p10le', 'yuva444p12le'}:
            codec = 'prores_ks'
        frames = int(stream['nb_frames'])
        if (stream.get('sample_aspect_ratio', '1:1') not in {'1:1', 'N/A'}
                or any(float(item.get('rotation', 0)) for item in stream.get('side_data_list', []))
                or float(stream.get('tags', {}).get('rotate', 0))):
            raise ValueError('Visual artifact must use square pixels without rotation')
        return {'media_type': 'video', 'container': container, 'codec': codec,
                'pixel_format': pixel, 'alpha': alpha, 'width': stream['width'], 'height': stream['height'],
                'fps': float(fps), 'frame_count': frames, 'duration': float(stream['duration'])}

    return ArtifactProbe('direct-and-native-media', sha256_file(Path(__file__)) + ':' + sha256_file(ffprobe), probe)
