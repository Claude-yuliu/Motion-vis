from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple

import pandas as pd

path = Path(__file__).resolve().parent / "mocap" / "basic" / "03.bvh"

# Return joint names, channel counts per joint, and the MOTION line index.
def parse_bvh_channels(lines: List[str]) -> Tuple[List[str], List[int], int]:
    joint_stack: List[str] = []
    pending_joint: str | None = None
    joint_names: List[str] = []
    channel_counts: List[int] = []

    motion_index = -1

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()

        if line == "MOTION":
            motion_index = i
            break

        if line.startswith(("ROOT ", "JOINT ")):
            pending_joint = line.split()[1]
            continue

        if line == "{":
            if pending_joint is not None:
                joint_stack.append(pending_joint)
                pending_joint = None
            continue

        if line == "}":
            if joint_stack:
                joint_stack.pop()
            continue

        if line.startswith("CHANNELS "):
            parts = line.split()
            channel_count = int(parts[1])
            joint_names.append(joint_stack[-1])
            channel_counts.append(channel_count)

    if motion_index == -1:
        raise ValueError("Invalid BVH file: missing MOTION section.")

    return joint_names, channel_counts, motion_index

# Parse all motion frames and validate their width.
def parse_bvh_frames(lines: List[str], motion_index: int, expected_values: int) -> List[List[float]]:
    frame_lines = []

    for raw_line in lines[motion_index + 1 :]:
        line = raw_line.strip()
        if not line or line.startswith("Frames:") or line.startswith("Frame Time:"):
            continue
        frame_lines.append(line)

    frames: List[List[float]] = []
    for frame_number, line in enumerate(frame_lines, start=1):
        values = [float(value) for value in line.split()]
        if len(values) != expected_values:
            raise ValueError(
                f"Frame {frame_number} has {len(values)} values; expected {expected_values}."
            )
        frames.append(values)

    return frames

# Convert a BVH file into a DataFrame with one column per joint.
def bvh_to_dataframe(bvh_path: Path) -> pd.DataFrame:
    if not bvh_path.exists():
        raise FileNotFoundError(f"BVH file not found: {bvh_path}")

    lines = bvh_path.read_text(encoding="utf-8").splitlines()
    joint_names, channel_counts, motion_index = parse_bvh_channels(lines)
    total_channels = sum(channel_counts)
    frames = parse_bvh_frames(lines, motion_index, total_channels)

    records = []
    for frame_index, frame_values in enumerate(frames, start=1):
        row = {"Frame index": frame_index}
        cursor = 0

        for joint_name, channel_count in zip(joint_names, channel_counts):
            joint_values = frame_values[cursor : cursor + channel_count]
            row[joint_name] = json.dumps(joint_values)
            cursor += channel_count

        records.append(row)

    return pd.DataFrame(records)

# Read a BVH file and save its motion data as CSV.
def convert_bvh_to_csv(bvh_path: Path, output_path: Path | None = None) -> Path:
    if output_path is None:
        output_path = bvh_path.with_suffix(".csv")

    dataframe = bvh_to_dataframe(bvh_path)
    dataframe.to_csv(output_path, index=False)
    return output_path


def main() -> None:
    bvh_path = path
    output_path = convert_bvh_to_csv(bvh_path)
    print(f"Saved CSV to: {output_path}")


if __name__ == "__main__":
    main()
