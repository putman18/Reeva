"""
clip_detector.py

Detects highlight moments in a gaming VOD using:
  1. Audio peak detection (librosa) - spikes = hype moments, reactions, kills
  2. Scene change detection (ffmpeg) - rapid cuts = action sequences

Only needed for full VODs (streamer clients).
Vyro/ClipFarm clips are pre-cut - skip this script for those.

Usage:
    python clipping/execution/clip_detector.py --input vod.mp4
    python clipping/execution/clip_detector.py --input vod.mp4 --top 10 --min-duration 25 --max-duration 45
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT  = Path(__file__).parent.parent.parent
DEFAULT_OUT   = PROJECT_ROOT / ".tmp" / "clipping" / "segments"


def detect_audio_peaks(video_path: Path, top_n: int = 20) -> list[float]:
    """
    Use librosa to find timestamps where audio energy spikes.
    Returns a list of peak timestamps in seconds.
    """
    try:
        import librosa
        import numpy as np
    except ImportError:
        print("librosa not installed. Run clip_setup.py first.")
        return []

    print("  Loading audio for peak detection...")
    # Load audio at reduced sample rate for speed
    y, sr = librosa.load(str(video_path), sr=11025, mono=True)

    # RMS energy per frame
    hop_length = 512
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)

    # Smooth the RMS curve
    import numpy as np
    window = int(sr / hop_length)  # ~1 second window
    rms_smooth = np.convolve(rms, np.ones(window) / window, mode="same")

    # Find local maxima above the 85th percentile
    threshold = np.percentile(rms_smooth, 85)
    peaks = []
    min_gap = int(sr / hop_length * 30)  # at least 30s between peaks

    last_peak = -min_gap
    for i, val in enumerate(rms_smooth):
        if val > threshold and (i - last_peak) > min_gap:
            peaks.append((float(times[i]), float(val)))
            last_peak = i

    # Sort by energy, take top N
    peaks.sort(key=lambda x: x[1], reverse=True)
    timestamps = [p[0] for p in peaks[:top_n]]
    timestamps.sort()  # re-sort chronologically

    print(f"  Found {len(timestamps)} audio peaks")
    return timestamps


def detect_scene_changes(video_path: Path, threshold: float = 0.4) -> list[float]:
    """
    Use ffmpeg scene filter to detect rapid visual changes.
    Returns timestamps in seconds.
    """
    print("  Detecting scene changes...")
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    timestamps = []
    for line in result.stderr.split("\n"):
        if "pts_time:" in line:
            try:
                t = float(line.split("pts_time:")[1].split()[0])
                timestamps.append(t)
            except (IndexError, ValueError):
                continue

    print(f"  Found {len(timestamps)} scene changes")
    return timestamps


def get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data["format"].get("duration", 0))


def merge_timestamps(
    audio_peaks: list[float],
    scene_changes: list[float],
    duration: float,
    clip_duration: int = 35,
    min_gap: int = 60,
) -> list[dict]:
    """
    Combine audio peaks and scene changes into ranked clip candidates.
    Returns list of {start, end, score, type} sorted by score descending.
    """
    import numpy as np

    # Score each audio peak
    candidates = []
    for t in audio_peaks:
        start = max(0, t - 5)  # 5s before the peak
        end = min(duration, start + clip_duration)
        if end - start < 15:
            continue

        # Boost score if scene changes nearby
        nearby_scenes = sum(1 for s in scene_changes if abs(s - t) < 10)
        score = 1.0 + nearby_scenes * 0.3
        candidates.append({"start": start, "end": end, "score": score, "type": "audio_peak"})

    # Add pure scene change clusters (groups of rapid cuts = action)
    if scene_changes:
        scene_arr = np.array(scene_changes)
        i = 0
        while i < len(scene_arr):
            # Find cluster of scene changes within 10s window
            cluster = [scene_arr[i]]
            j = i + 1
            while j < len(scene_arr) and scene_arr[j] - scene_arr[i] < 10:
                cluster.append(scene_arr[j])
                j += 1
            if len(cluster) >= 3:  # 3+ cuts in 10s = action sequence
                t = cluster[0]
                start = max(0, t - 2)
                end = min(duration, start + clip_duration)
                score = 0.5 + len(cluster) * 0.1
                candidates.append({"start": start, "end": end, "score": score, "type": "scene_cluster"})
            i = j if j > i else i + 1

    # Deduplicate: remove overlapping clips (keep highest score)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected = []
    for c in candidates:
        overlaps = any(
            abs(c["start"] - s["start"]) < min_gap for s in selected
        )
        if not overlaps:
            selected.append(c)

    selected.sort(key=lambda x: x["start"])
    return selected


def extract_segments(video_path: Path, clips: list[dict], out_dir: Path) -> list[Path]:
    """Cut each highlight segment from the VOD using ffmpeg."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem[:40]
    output_paths = []

    for i, clip in enumerate(clips):
        out_path = out_dir / f"{stem}_highlight_{i+1:02d}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip["start"]),
            "-t", str(clip["end"] - clip["start"]),
            "-i", str(video_path),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            str(out_path)
        ]
        print(f"  Extracting clip {i+1}/{len(clips)}: {clip['start']:.0f}s-{clip['end']:.0f}s (score: {clip['score']:.2f})")
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            output_paths.append(out_path)
        else:
            print(f"  Failed to extract clip {i+1}")

    return output_paths


def detect(
    video_path: Path,
    out_dir: Path,
    top_n: int = 8,
    clip_duration: int = 35,
) -> list[Path]:
    """Full detection pipeline. Returns extracted segment file paths."""
    print(f"\nDetecting highlights in: {video_path.name}")

    duration = get_video_duration(video_path)
    print(f"  Video duration: {duration/60:.1f} minutes")

    audio_peaks   = detect_audio_peaks(video_path, top_n=top_n * 3)
    scene_changes = detect_scene_changes(video_path)

    clips = merge_timestamps(audio_peaks, scene_changes, duration, clip_duration)
    clips = clips[:top_n]

    print(f"\nSelected {len(clips)} highlights:")
    for i, c in enumerate(clips):
        print(f"  {i+1}. {c['start']:.0f}s - {c['end']:.0f}s ({c['type']}, score: {c['score']:.2f})")

    print(f"\nExtracting segments to {out_dir}...")
    paths = extract_segments(video_path, clips, out_dir)
    print(f"\nDone. {len(paths)} segments ready for processing.")
    return paths


def main():
    parser = argparse.ArgumentParser(description="Detect highlight moments in a VOD")
    parser.add_argument("--input",        required=True, help="Input VOD file (.mp4)")
    parser.add_argument("--out",          default=str(DEFAULT_OUT), help="Output folder for segments")
    parser.add_argument("--top",          type=int, default=8, help="Number of highlights to extract (default 8)")
    parser.add_argument("--clip-duration",type=int, default=35, help="Length of each clip in seconds (default 35)")
    args = parser.parse_args()

    paths = detect(
        Path(args.input),
        Path(args.out),
        top_n=args.top,
        clip_duration=args.clip_duration,
    )
    print("\nNext step: run clip_processor.py --input .tmp/clipping/segments/ --batch")


if __name__ == "__main__":
    main()
