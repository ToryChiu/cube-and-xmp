"""Read original Sony video frames without applying a display transform."""

import json
import math
import subprocess
from pathlib import Path


def video_info(ffprobe: str, source: Path) -> dict:
    details = json.loads(subprocess.check_output([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=duration,color_range,color_space:format=duration",
        "-of", "json", str(source),
    ]))
    streams = details.get("streams", [])
    if not streams:
        raise ValueError("文件里没有可读取的视频。")
    stream = streams[0]
    for value in (stream.get("duration"), details.get("format", {}).get("duration")):
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(duration) and duration > 0:
            break
    else:
        raise ValueError("无法识别视频时长。")
    return {"duration": duration, "range": {"tv": "video", "pc": "full"}.get(stream.get("color_range")),
            "matrix": stream.get("color_space")}


def extract_log_frame(ffmpeg: str, source: Path, target: Path, seconds: float,
                      source_range: str, matrix: str | None) -> None:
    matrix_option = ":in_color_matrix=bt709" if matrix in {None, "unknown", "unspecified", "bt709"} else ""
    input_range = "limited" if source_range == "video" else "full"
    command = [
        ffmpeg, "-nostdin", "-v", "error", "-ss", str(seconds), "-i", str(source),
        "-map", "0:v:0", "-an", "-frames:v", "1",
        "-vf", f"scale=in_range={input_range}:out_range=full{matrix_option},format=gbrp10le",
        "-c:v", "dpx", "-f", "image2", "-update", "1", str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode or not target.is_file():
        raise ValueError("该位置无法取帧，请试着往前移动一点，或检查视频编码。")
