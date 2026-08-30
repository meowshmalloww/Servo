#!/usr/bin/env python3
"""Select sharp, connected evidence frames from every decoded video frame.

This is the T1 ingestion preflight.  It deliberately does not estimate poses,
depth, Gaussians, or metric scale.  Its output is a hash-bound image sequence
and receipt suitable for HorizonStream, WildGS-SLAM, or another sealed
geometry backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np


RECONSTRUCTION_DIR = Path(__file__).resolve().parent
if str(RECONSTRUCTION_DIR) not in sys.path:
    sys.path.insert(0, str(RECONSTRUCTION_DIR))

from servo_worker import (  # noqa: E402
    frame_features,
    overlap_motion,
    probe_video_decode,
    write_selected_frame,
)
from servo_prepare_360_capture import prepare as prepare_360_capture  # noqa: E402


SCHEMA = "servo.t1-video-evidence-selection/v1"
METHOD = "all-frame-windowed-sharp-connected-v1"


@dataclass
class Candidate:
    frame_index: int
    timestamp: float
    frame: Any
    global_focus: float
    regional_focus: float
    clipped_fraction: float
    keypoints: Any
    descriptors: Any
    diagonal: float

    @property
    def quality(self) -> float:
        # Clipped pixels carry little recoverable texture.  Keep this penalty
        # bounded so an unusually bright/dark but sharp bridge can still win.
        exposure_factor = max(0.20, 1.0 - 2.0 * self.clipped_fraction)
        return self.regional_focus * exposure_factor


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def clipped_pixel_fraction(frame: Any) -> float:
    height, width = frame.shape[:2]
    scale = min(1.0, 480.0 / max(height, width))
    sample = (
        cv2.resize(
            frame,
            (max(2, round(width * scale)), max(2, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        if scale < 1.0
        else frame
    )
    gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
    return float(np.mean((gray <= 4) | (gray >= 251)))


def locate_ffmpeg_bin(explicit: Path | None = None) -> Path:
    if explicit is not None:
        candidates = [explicit.resolve()]
    else:
        candidates = []
        discovered = shutil.which("ffmpeg")
        if discovered:
            candidates.append(Path(discovered).resolve().parent)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            package_root = (
                Path(local_app_data)
                / "Microsoft"
                / "WinGet"
                / "Packages"
                / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
            )
            if package_root.is_dir():
                candidates.extend(
                    path.parent
                    for path in sorted(package_root.glob("ffmpeg-*/bin/ffmpeg.exe"))
                )
    for candidate in candidates:
        if (candidate / "ffmpeg.exe").is_file():
            return candidate
    raise RuntimeError(
        "FFmpeg was not found. Pass --ffmpeg-bin pointing to an existing bin "
        "directory; this tool will not install or download it."
    )


def probe_video_decode_nominal(
    source_path: Path, max_dimension: int, ffmpeg_bin: Path
) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(source_path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"OpenCV could not inspect {source_path.name}.")
        width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(round(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
    finally:
        capture.release()
    if width <= 0 or height <= 0 or not math.isfinite(fps) or fps <= 0.0:
        raise RuntimeError("The video has no usable dimensions or frame rate.")
    if frame_count <= 0:
        raise RuntimeError("The video has no reported frame count.")
    # A nominal-timestamp fallback is safe only for a constant-rate ingestion
    # preflight.  The limitation is written into the receipt and this output
    # is not allowed to carry calibrated camera poses.
    resize_scale = min(1.0, max_dimension / float(max(width, height)))
    output_width = max(2, int(round(width * resize_scale / 2.0) * 2))
    output_height = max(2, int(round(height * resize_scale / 2.0) * 2))
    environment = dict(os.environ)
    environment["PATH"] = str(ffmpeg_bin) + os.pathsep + environment.get("PATH", "")
    version = subprocess.run(
        [str(ffmpeg_bin / "ffmpeg.exe"), "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
        env=environment,
    )
    stream_probe = subprocess.run(
        [
            str(ffmpeg_bin / "ffmpeg.exe"),
            "-hide_banner",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-f",
            "null",
            "NUL" if os.name == "nt" else "/dev/null",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
        env=environment,
    )
    stream_text = stream_probe.stderr.lower()
    if "arib-std-b67" in stream_text:
        decode_filter = (
            "zscale=min=2020_ncl:tin=arib-std-b67:pin=2020:rin=limited:"
            "t=linear:npl=1000,format=gbrpf32le,"
            "tonemap=mobius:param=0.3:desat=0,"
            "zscale=tin=linear:t=iec61966-2-1:p=709:m=gbr:r=full,"
            f"scale={output_width}:{output_height}:flags=lanczos,format=bgr24"
        )
        display_transform = "bt2020-hlg-limited-to-bt709-srgb-mobius-v1"
        color_primaries = "bt2020"
        color_transfer = "arib-std-b67"
        color_space = "bt2020nc"
        color_range = "tv"
    elif "smpte2084" in stream_text or "smpte-st-2084" in stream_text:
        raise RuntimeError(
            "PQ HDR requires a calibrated display transform; this preflight "
            "will not decode it implicitly."
        )
    elif "bt2020" in stream_text:
        raise RuntimeError(
            "BT.2020 video has unrecognized transfer metadata; implicit color "
            "conversion is disabled."
        )
    else:
        decode_filter = (
            f"scale={output_width}:{output_height}:flags=lanczos,format=bgr24"
        )
        display_transform = "ffmpeg-declared-sdr-to-bgr24-v1"
        color_primaries = "unknown"
        color_transfer = "unknown"
        color_space = "unknown"
        color_range = "unknown"
    return {
        "ffmpeg": str(ffmpeg_bin / "ffmpeg.exe"),
        "ffprobe": None,
        "environment": environment,
        "timestamps": [index / fps for index in range(frame_count)],
        "timestampSource": "nominal-constant-frame-rate-fallback-v1",
        "nominalFps": fps,
        "width": output_width,
        "height": output_height,
        "sourceWidth": width,
        "sourceHeight": height,
        "rotationDegrees": 0,
        "colorPrimaries": color_primaries,
        "colorTransfer": color_transfer,
        "colorSpace": color_space,
        "colorRange": color_range,
        "filter": decode_filter,
        "displayTransform": display_transform,
        "ffmpegVersion": version.stdout.splitlines()[0]
        if version.stdout
        else "unknown",
    }


def inspect_video(
    source_path: Path, max_dimension: int, ffmpeg_bin: Path
) -> dict[str, Any]:
    if (ffmpeg_bin / "ffprobe.exe").is_file():
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + original_path
        try:
            result = probe_video_decode(source_path, max_dimension)
            result["timestampSource"] = "ffprobe-best-effort-presentation-time-v1"
            return result
        finally:
            os.environ["PATH"] = original_path
    return probe_video_decode_nominal(source_path, max_dimension, ffmpeg_bin)


def make_candidate(frame_index: int, timestamp: float, frame: Any) -> Candidate:
    global_focus, regional_focus, keypoints, descriptors, diagonal = frame_features(
        frame
    )
    return Candidate(
        frame_index=frame_index,
        timestamp=timestamp,
        frame=frame,
        global_focus=global_focus,
        regional_focus=regional_focus,
        clipped_fraction=clipped_pixel_fraction(frame),
        keypoints=keypoints,
        descriptors=descriptors,
        diagonal=diagonal,
    )


def choose_window_candidate(
    candidates: Sequence[Candidate],
    previous: Candidate | None,
    *,
    minimum_overlap: float = 0.12,
    minimum_matches: int = 24,
    maximum_motion: float = 0.40,
    minimum_motion: float = 0.0,
    minimum_regional_focus: float = 0.0,
    minimum_interval: float = 0.0,
) -> tuple[Candidate, dict[str, Any]]:
    if not candidates:
        raise ValueError("A selection window must contain at least one candidate.")
    if previous is None:
        chosen = max(candidates, key=lambda item: (item.quality, -item.frame_index))
        return chosen, {
            "movement": 0.0,
            "overlap": 1.0,
            "matches": 0,
            "connected": True,
            "selectionReason": "sharpest-first-window",
        }

    evaluated: list[
        tuple[Candidate, float, float, int, bool, bool, float]
    ] = []
    for candidate in candidates:
        movement, overlap, matches = overlap_motion(
            previous.keypoints,
            previous.descriptors,
            candidate.keypoints,
            candidate.descriptors,
            candidate.diagonal,
        )
        connected = (
            overlap >= minimum_overlap
            and matches >= minimum_matches
            and movement <= maximum_motion
        )
        eligible = (
            connected
            and movement >= minimum_motion
            and candidate.regional_focus >= minimum_regional_focus
            and candidate.timestamp - previous.timestamp >= minimum_interval
        )
        # Sharpness remains primary, but among similarly sharp frames prefer
        # the one whose epipolar evidence connects cleanly to the last window.
        rank = candidate.quality * (0.75 + 0.25 * overlap)
        evaluated.append(
            (candidate, movement, overlap, matches, connected, eligible, rank)
        )

    eligible_items = [item for item in evaluated if item[5]]
    connected_items = [item for item in evaluated if item[4]]
    pool = eligible_items or connected_items or evaluated
    chosen, movement, overlap, matches, connected, eligible, _ = max(
        pool,
        key=lambda item: (item[6], item[0].quality, -item[0].frame_index),
    )
    return chosen, {
        "movement": movement,
        "overlap": overlap,
        "matches": matches,
        "connected": connected,
        "selectionReason": (
            "sharpest-connected-window"
            if connected
            else "sharpest-unconnected-window"
        ),
        "eligible": eligible,
    }


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def write_contact_sheet(path: Path, selected: Sequence[dict[str, Any]]) -> None:
    if not selected:
        return
    count = min(24, len(selected))
    indices = np.linspace(0, len(selected) - 1, count, dtype=np.int64)
    columns = 6
    cell_width = 280
    cell_height = 180
    rows = int(math.ceil(count / columns))
    sheet = np.full((rows * cell_height, columns * cell_width, 3), 20, np.uint8)
    for position, selected_index in enumerate(indices.tolist()):
        item = selected[selected_index]
        image = cv2.imread(str(item["absolutePath"]), cv2.IMREAD_COLOR)
        if image is None:
            continue
        scale = min(cell_width / image.shape[1], (cell_height - 24) / image.shape[0])
        resized = cv2.resize(
            image,
            (
                max(1, round(image.shape[1] * scale)),
                max(1, round(image.shape[0] * scale)),
            ),
            interpolation=cv2.INTER_AREA,
        )
        x0 = (position % columns) * cell_width
        y0 = (position // columns) * cell_height
        sheet[y0 : y0 + resized.shape[0], x0 : x0 + resized.shape[1]] = resized
        cv2.putText(
            sheet,
            f"{item['timestampSeconds']:.2f}s  f={item['regionalFocus']:.0f}",
            (x0 + 5, y0 + cell_height - 7),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (230, 230, 230),
            1,
            cv2.LINE_AA,
        )
    if not cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90]):
        raise RuntimeError(f"Unable to write contact sheet: {path}")


def prepare(
    *,
    video: Path,
    output: Path,
    target_fps: float = 10.0,
    max_dimension: int = 1910,
    capture_type: str = "perspective",
    ffmpeg_bin: Path | None = None,
    minimum_regional_focus: float = 300.0,
    minimum_motion: float = 0.002,
    minimum_interval: float = 0.08,
    maximum_interval: float = 0.35,
) -> dict[str, Any]:
    video = video.resolve()
    output = output.resolve()
    if not video.is_file():
        raise RuntimeError(f"Input video does not exist: {video}")
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite output: {output}")
    if not (1.0 <= target_fps <= 30.0):
        raise RuntimeError("target_fps must be between 1 and 30.")
    if max_dimension < 320:
        raise RuntimeError("max_dimension must be at least 320 pixels.")
    if capture_type not in {"perspective", "equirectangular360"}:
        raise RuntimeError("capture_type must be perspective or equirectangular360.")

    resolved_ffmpeg_bin = locate_ffmpeg_bin(ffmpeg_bin)
    output.mkdir(parents=True)
    images = output / "images" / "video-000"
    images.mkdir(parents=True)
    decode = inspect_video(video, max_dimension, resolved_ffmpeg_bin)
    timestamps = list(decode["timestamps"])
    width = int(decode["width"])
    height = int(decode["height"])
    frame_bytes = width * height * 3
    command = [
        str(decode["ffmpeg"]),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        str(decode["filter"]),
        "-fps_mode",
        "passthrough",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "pipe:1",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env=decode["environment"],
    )

    def read_frame() -> bytes:
        assert process.stdout is not None
        data = bytearray()
        while len(data) < frame_bytes:
            block = process.stdout.read(frame_bytes - len(data))
            if not block:
                break
            data.extend(block)
        if data and len(data) != frame_bytes:
            raise RuntimeError("FFmpeg produced a partial video frame.")
        return bytes(data)

    selected_records: list[dict[str, Any]] = []
    selected_candidates: list[Candidate] = []
    window: list[Candidate] = []
    current_window: int | None = None
    decoded_count = 0
    unconnected_count = 0
    bridge_count = 0
    first_timestamp = timestamps[0]
    pending: list[Candidate] = []

    def commit_window() -> None:
        nonlocal window, pending, unconnected_count, bridge_count
        if not window:
            return
        pending.extend(window)
        window = []
        previous = selected_candidates[-1] if selected_candidates else None
        chosen, connectivity = choose_window_candidate(
            pending,
            previous,
            minimum_motion=minimum_motion,
            minimum_regional_focus=minimum_regional_focus,
            minimum_interval=minimum_interval,
        )
        latest_timestamp = max(item.timestamp for item in pending)
        elapsed = chosen.timestamp - previous.timestamp if previous else math.inf
        sharp_motion = (
            previous is None
            or (
                connectivity["connected"]
                and chosen.regional_focus >= minimum_regional_focus
                and float(connectivity["movement"]) >= minimum_motion
                and elapsed >= minimum_interval
            )
        )
        force_bridge = (
            previous is not None
            and latest_timestamp - previous.timestamp >= maximum_interval
            and connectivity["connected"]
        )
        if not sharp_motion and not force_bridge:
            return
        if force_bridge and not sharp_motion:
            connectivity["selectionReason"] = "connectivity-bridge"
            bridge_count += 1
        output_name = f"{len(selected_records):08d}.png"
        output_path = images / output_name
        write_selected_frame(output_path, chosen.frame)
        if not connectivity["connected"]:
            unconnected_count += 1
        selected_candidates.append(chosen)
        selected_records.append(
            {
                "image": f"video-000/{output_name}",
                "absolutePath": str(output_path),
                "sourceFrameIndex": chosen.frame_index,
                "timestampSeconds": chosen.timestamp,
                "globalFocus": chosen.global_focus,
                "regionalFocus": chosen.regional_focus,
                "clippedPixelFraction": chosen.clipped_fraction,
                "qualityScore": chosen.quality,
                **connectivity,
                "candidateCountSinceSelection": len(pending),
            }
        )
        pending = []

    try:
        for frame_index, timestamp in enumerate(timestamps):
            raw = read_frame()
            if not raw:
                raise RuntimeError(
                    f"FFmpeg decoded {decoded_count} frames but ffprobe indexed "
                    f"{len(timestamps)}."
                )
            decoded_count += 1
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
            candidate = make_candidate(frame_index, float(timestamp), frame.copy())
            window_index = int(
                math.floor((float(timestamp) - first_timestamp) * target_fps + 1e-8)
            )
            if current_window is None:
                current_window = window_index
            elif window_index != current_window:
                commit_window()
                current_window = window_index
            window.append(candidate)
        commit_window()
        extra = read_frame()
        if extra:
            raise RuntimeError("FFmpeg decoded more frames than ffprobe indexed.")
        return_code = process.wait(timeout=60)
        if return_code != 0:
            stderr = (
                process.stderr.read().decode("utf-8", errors="replace")
                if process.stderr is not None
                else ""
            )
            raise RuntimeError(f"FFmpeg decode failed: {stderr[-4000:]}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    if not selected_records:
        raise RuntimeError("No frames were selected.")

    for item in selected_records:
        item.pop("absolutePath", None)
    focus_values = [float(item["regionalFocus"]) for item in selected_records]
    overlap_values = [
        float(item["overlap"])
        for item in selected_records[1:]
        if int(item["matches"]) > 0
    ]
    timestamp_gaps = [
        float(selected_records[index]["timestampSeconds"])
        - float(selected_records[index - 1]["timestampSeconds"])
        for index in range(1, len(selected_records))
    ]
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "method": METHOD,
        "input": {
            "path": str(video),
            "sha256": sha256_file(video),
            "bytes": video.stat().st_size,
            "captureType": capture_type,
            "sourceWidth": int(decode["sourceWidth"]),
            "sourceHeight": int(decode["sourceHeight"]),
            "rotationDegrees": int(decode["rotationDegrees"]),
            "colorTransform": decode["displayTransform"],
        },
        "decoder": {
            "method": "ffmpeg-all-frames-raw-bgr24-v1",
            "version": decode["ffmpegVersion"],
            "timestampSource": decode["timestampSource"],
            "nominalFps": decode.get("nominalFps"),
            "decodedFrames": decoded_count,
            "outputWidth": width,
            "outputHeight": height,
        },
        "selection": {
            "targetFps": target_fps,
            "minimumRegionalFocus": minimum_regional_focus,
            "minimumMotion": minimum_motion,
            "minimumIntervalSeconds": minimum_interval,
            "maximumIntervalSeconds": maximum_interval,
            "selectedFrames": len(selected_records),
            "unconnectedWindows": unconnected_count,
            "connectivityBridgeFrames": bridge_count,
            "regionalFocusP10": percentile(focus_values, 10),
            "regionalFocusP50": percentile(focus_values, 50),
            "regionalFocusP90": percentile(focus_values, 90),
            "overlapP10": percentile(overlap_values, 10),
            "overlapP50": percentile(overlap_values, 50),
            "maximumTimestampGapSeconds": max(timestamp_gaps, default=0.0),
            "posesEstimated": False,
            "depthEstimated": False,
            "metric": False,
        },
        "frames": selected_records,
    }
    # The contact sheet is generated from the committed image sequence and is
    # not reconstruction evidence.  Restore absolute paths only in memory.
    contact_records = [
        {**item, "absolutePath": images / Path(str(item["image"])).name}
        for item in selected_records
    ]
    write_contact_sheet(output / "selection-contact-sheet.jpg", contact_records)
    if capture_type == "equirectangular360":
        cubemap_output = output / "cubemap"
        cubemap = prepare_360_capture(
            images,
            cubemap_output,
            face_resolution=max(2, width // 4),
        )
        receipt["derivedCubemap"] = {
            "schema": cubemap["schema"],
            "method": cubemap["method"],
            "receipt": "cubemap/receipt.json",
            "receiptSha256": sha256_file(cubemap_output / "receipt.json"),
            "faceResolution": cubemap["faceResolution"],
            "facesPerFrame": 6,
            "sharedOpticalCenter": True,
            "sourceIsEvidenceMaster": True,
        }
    atomic_json(output / "selection-receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-fps", type=float, default=10.0)
    parser.add_argument("--max-dimension", type=int, default=1910)
    parser.add_argument("--minimum-regional-focus", type=float, default=300.0)
    parser.add_argument("--minimum-motion", type=float, default=0.002)
    parser.add_argument("--minimum-interval", type=float, default=0.08)
    parser.add_argument("--maximum-interval", type=float, default=0.35)
    parser.add_argument(
        "--ffmpeg-bin",
        type=Path,
        help="Existing directory containing ffmpeg.exe and ffprobe.exe.",
    )
    parser.add_argument(
        "--capture-type",
        choices=("perspective", "equirectangular360"),
        default="perspective",
    )
    arguments = parser.parse_args()
    receipt = prepare(
        video=arguments.video,
        output=arguments.output,
        target_fps=arguments.target_fps,
        max_dimension=arguments.max_dimension,
        capture_type=arguments.capture_type,
        ffmpeg_bin=arguments.ffmpeg_bin,
        minimum_regional_focus=arguments.minimum_regional_focus,
        minimum_motion=arguments.minimum_motion,
        minimum_interval=arguments.minimum_interval,
        maximum_interval=arguments.maximum_interval,
    )
    print(json.dumps(receipt["selection"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
