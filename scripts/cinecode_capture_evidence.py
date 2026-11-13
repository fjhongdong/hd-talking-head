"""Inspect the encoded scene at a few fixed times, independent of page claims."""
from __future__ import annotations

import struct
import subprocess
import zlib

WIDTH = 270
HEIGHT = 480


def review_indices(frame_count):
    return sorted({round((frame_count - 1) * index / 4) for index in range(5)})


def review_frames(ffmpeg, media, indices):
    selection = '+'.join(f'eq(n,{index})' for index in indices)
    result = subprocess.run(
        [ffmpeg, '-v', 'error', '-nostdin', '-i', str(media), '-map', '0:v:0',
         '-vf', f"select='{selection}',scale={WIDTH}:{HEIGHT}:flags=area,format=rgb24",
         '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-threads', '1', 'pipe:1'],
        check=True, capture_output=True, timeout=120)
    frame_size = WIDTH * HEIGHT * 3
    if len(result.stdout) != len(indices) * frame_size:
        raise ValueError('CineCode could not extract review frames from the actual video')
    return [result.stdout[start:start + frame_size]
            for start in range(0, len(result.stdout), frame_size)]


def has_visible_content(pixels):
    # A flat field can be an intentional transition. Only reject a wholly flat sample set.
    return any(max(channel) - min(channel) >= 4 for channel in
               (pixels[0::3], pixels[1::3], pixels[2::3]))


def review_png(pixels):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    width = WIDTH * 3
    rows = b''.join(b'\x00' + pixels[start:start + width] for start in range(0, len(pixels), width))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows))
            + chunk(b'IEND', b''))
