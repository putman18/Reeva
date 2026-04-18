"""
clip_processor.py

Processes a video file into a TikTok/Shorts-ready vertical clip:
  1. Trim to specified start/duration (or use full file)
  2. Crop to 9:16 aspect ratio (center crop)
  3. Resize to 1080x1920
  4. Transcribe audio with faster-whisper
  5. Burn captions onto video with ffmpeg

Requires: ffmpeg installed and on PATH

Usage:
    # Process a single file (full length)
    python clipping/execution/clip_processor.py --input video.mp4

    # Trim a segment from a longer VOD
    python clipping/execution/clip_processor.py --input vod.mp4 --start 142 --duration 35

    # Process all mp4s in a folder
    python clipping/execution/clip_processor.py --input .tmp/clipping/segments/ --batch
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_OUT  = PROJECT_ROOT / ".tmp" / "clipping" / "processed"

# Caption style - big, bold, centered (TikTok style)
CAPTION_STYLE = {
    "fontsize":   60,
    "fontcolor":  "white",
    "bordercolor": "black",
    "borderwidth": 3,
    "line_chars": 30,   # max chars per caption line
}


def check_ffmpeg():
    import shutil
    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg not found. Run: winget install ffmpeg")
        sys.exit(1)


def get_video_info(path: Path) -> dict:
    """Return duration, width, height of a video file."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    return {
        "duration": float(data["streams"][0].get("duration", 0)),
        "width":    int(video["width"]),
        "height":   int(video["height"]),
    }


def transcribe(path: Path) -> list[dict]:
    """
    Transcribe audio using faster-whisper.
    Returns list of segments: [{start, end, text}, ...]
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  faster-whisper not installed, skipping captions")
        return []

    print("  Transcribing audio...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(path), beam_size=5, language="en")
    result = []
    for seg in segments:
        result.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
    print(f"  Transcribed {len(result)} segments")
    return result


def build_subtitle_file(segments: list[dict], tmp_dir: Path) -> Path | None:
    """Write an SRT subtitle file for ffmpeg to burn in."""
    if not segments:
        return None

    srt_path = tmp_dir / "captions.srt"
    lines = []

    def fmt_time(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    for i, seg in enumerate(segments, 1):
        # Wrap long lines
        words = seg["text"].split()
        lines_text = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 > CAPTION_STYLE["line_chars"]:
                if current:
                    lines_text.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        if current:
            lines_text.append(current)

        lines.append(str(i))
        lines.append(f"{fmt_time(seg['start'])} --> {fmt_time(seg['end'])}")
        lines.append("\n".join(lines_text))
        lines.append("")

    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return srt_path


def process_clip(
    input_path: Path,
    out_dir: Path,
    start: float = 0,
    duration: float = None,
    captions: bool = True,
    slug: str = None,
) -> Path:
    """
    Process a single video into a 1080x1920 vertical clip with captions.
    Returns the output file path.
    """
    check_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)

    slug = slug or input_path.stem[:50]
    out_path = out_dir / f"{slug}_vertical.mp4"

    info = get_video_info(input_path)
    w, h = info["width"], info["height"]

    # Crop: take center square then resize to 9:16
    # For landscape (w > h): crop to h x h centered, then resize to 1080x1920
    # For portrait already: just resize
    if w > h:
        crop_size = h
        crop_x = (w - crop_size) // 2
        crop_filter = f"crop={crop_size}:{crop_size}:{crop_x}:0,scale=1080:1920:flags=lanczos"
    else:
        crop_filter = "scale=1080:1920:flags=lanczos"

    # Trim args
    trim_args = []
    if start > 0:
        trim_args += ["-ss", str(start)]
    if duration:
        trim_args += ["-t", str(duration)]

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        # Step 1: trim + crop to a temp file (needed for transcription)
        trimmed = tmp / "trimmed.mp4"
        cmd_trim = [
            "ffmpeg", "-y",
            *trim_args,
            "-i", str(input_path),
            "-vf", crop_filter,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(trimmed)
        ]
        print(f"  Cropping to 9:16...")
        subprocess.run(cmd_trim, capture_output=True, check=True)

        # Step 2: transcribe
        subtitle_path = None
        if captions:
            segments = transcribe(trimmed)
            subtitle_path = build_subtitle_file(segments, tmp)

        # Step 3: burn captions (or just copy if no captions)
        if subtitle_path:
            print("  Burning captions...")
            # Escape path for ffmpeg filter (Windows backslashes)
            srt_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
            vf = (
                f"subtitles='{srt_escaped}':force_style='"
                f"FontSize={CAPTION_STYLE['fontsize']},"
                f"PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,"
                f"Outline={CAPTION_STYLE['borderwidth']},"
                f"Bold=1,Alignment=2'"
            )
            cmd_final = [
                "ffmpeg", "-y",
                "-i", str(trimmed),
                "-vf", vf,
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "copy",
                str(out_path)
            ]
            result = subprocess.run(cmd_final, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  Caption burn failed, saving without captions")
                print(f"  {result.stderr[-300:]}")
                # Fallback: save without captions
                import shutil as sh
                sh.copy(trimmed, out_path)
        else:
            import shutil as sh
            sh.copy(trimmed, out_path)

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  Saved: {out_path.name} ({size_mb:.1f} MB)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Process video to vertical clip")
    parser.add_argument("--input",    required=True, help="Input video file or folder (with --batch)")
    parser.add_argument("--out",      default=str(DEFAULT_OUT), help="Output directory")
    parser.add_argument("--start",    type=float, default=0, help="Start time in seconds")
    parser.add_argument("--duration", type=float, default=None, help="Duration in seconds")
    parser.add_argument("--no-captions", action="store_true", help="Skip caption generation")
    parser.add_argument("--batch",    action="store_true", help="Process all mp4s in input folder")
    args = parser.parse_args()

    out_dir = Path(args.out)
    captions = not args.no_captions

    if args.batch:
        input_dir = Path(args.input)
        mp4_files = sorted(input_dir.glob("*.mp4"))
        print(f"Batch mode: {len(mp4_files)} files in {input_dir}")
        for f in mp4_files:
            print(f"\nProcessing: {f.name}")
            process_clip(f, out_dir, captions=captions)
    else:
        input_path = Path(args.input)
        print(f"Processing: {input_path.name}")
        out = process_clip(
            input_path, out_dir,
            start=args.start,
            duration=args.duration,
            captions=captions,
        )
        print(f"\nDone: {out}")


if __name__ == "__main__":
    main()
