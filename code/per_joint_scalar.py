from __future__ import annotations

import argparse
import json
import math
from collections import deque
from pathlib import Path
from typing import Deque

import pandas as pd

default_path = Path(__file__).resolve().parent / "mocap" / "basic" / "03.csv"

EPSILON = 1e-8
DEFAULT_SMOOTHING_FACTOR = 0.95             #default 0.95
DEFAULT_RELEASE_SMOOTHING_FACTOR = 0.98     #default 0.98
DEFAULT_WINDOW_SIZE = 200                   #default 200
DEFAULT_DELTA_FRAME = 1.0
DEFAULT_STARTUP_ZERO_FRAMES = 2
BVH_ROTATION_ORDER = "ZYX"
JOINT_SCALAR_REPLACEMENTS = {
    "LeftShoulder": ("Spine",),
    "RightShoulder": ("Spine",),
    "LeftHipJoint": ("Hips",),
    "RightHipJoint": ("Hips",),
    "LHipJoint": ("Hips",),
    "RHipJoint": ("Hips",),
}

# Parse a CSV cell into numeric joint channel values.
def parse_joint_channels(raw_value: object) -> list[float]:
    if isinstance(raw_value, str):
        parsed = json.loads(raw_value)
    elif isinstance(raw_value, list):
        parsed = raw_value
    else:
        raise TypeError(f"Unsupported joint value type: {type(raw_value)!r}")

    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON list, received: {parsed!r}")

    return [float(value) for value in parsed]

def extract_euler_rotation(channel_values: list[float]) -> list[float]:
    if len(channel_values) == 3:
        return channel_values
    if len(channel_values) == 6:
        return channel_values[3:]

    raise ValueError(
        "Expected joint channels to contain either 3 rotation values or "
        f"3 position + 3 rotation values, received {len(channel_values)} values."
    )

def axis_angle_to_quaternion(
    axis: str,
    angle_radians: float,
) -> tuple[float, float, float, float]:
    half_angle = angle_radians * 0.5
    sin_half = math.sin(half_angle)
    cos_half = math.cos(half_angle)

    if axis == "X":
        return (cos_half, sin_half, 0.0, 0.0)
    if axis == "Y":
        return (cos_half, 0.0, sin_half, 0.0)
    if axis == "Z":
        return (cos_half, 0.0, 0.0, sin_half)

    raise ValueError(f"Unsupported rotation axis: {axis!r}")

def multiply_quaternions(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )

def normalize_quaternion(
    quaternion: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    magnitude = math.sqrt(sum(component * component for component in quaternion))
    if magnitude == 0.0:
        return (1.0, 0.0, 0.0, 0.0)

    return tuple(component / magnitude for component in quaternion)

def conjugate_quaternion(
    quaternion: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    w, x, y, z = quaternion
    return (w, -x, -y, -z)

def euler_rotation_to_quaternion(
    euler_degrees: list[float],
    rotation_order: str = BVH_ROTATION_ORDER,
) -> tuple[float, float, float, float]:
    if len(euler_degrees) != len(rotation_order):
        raise ValueError(
            "Euler rotation width must match the rotation order: "
            f"{len(euler_degrees)} != {len(rotation_order)}"
        )

    quaternion = (1.0, 0.0, 0.0, 0.0)
    for axis, angle_degrees in zip(rotation_order, euler_degrees):
        axis_quaternion = axis_angle_to_quaternion(axis, math.radians(angle_degrees))
        quaternion = multiply_quaternions(quaternion, axis_quaternion)

    return normalize_quaternion(quaternion)

def compute_angular_speed(
    previous_quaternion: tuple[float, float, float, float] | None,
    current_quaternion: tuple[float, float, float, float],
    delta_frame: float,
) -> float:
    if previous_quaternion is None:
        return 0.0

    relative_quaternion = multiply_quaternions(
        current_quaternion,
        conjugate_quaternion(previous_quaternion),
    )
    relative_quaternion = normalize_quaternion(relative_quaternion)
    w, x, y, z = relative_quaternion
    vector_magnitude = math.sqrt(x * x + y * y + z * z)
    angular_difference = 2.0 * math.atan2(vector_magnitude, abs(w))
    return angular_difference / delta_frame

# Return the rolling 95th percentile for the current history window.
def compute_q95(history: Deque[float]) -> float:
    if not history:
        return 0.0

    values = sorted(history)
    if len(values) == 1:
        return values[0]

    rank = 0.95 * (len(values) - 1)
    lower_index = int(math.floor(rank))
    upper_index = int(math.ceil(rank))

    if lower_index == upper_index:
        return values[lower_index]

    lower_value = values[lower_index]
    upper_value = values[upper_index]
    weight = rank - lower_index
    return lower_value + (upper_value - lower_value) * weight

# Replace selected joint scalar cells with their parent joint's value.
def apply_joint_scalar_replacements(output_row: dict[str, object]) -> None:
    for target_joint, source_joints in JOINT_SCALAR_REPLACEMENTS.items():
        if target_joint not in output_row:
            continue

        for source_joint in source_joints:
            if source_joint in output_row:
                output_row[target_joint] = output_row[source_joint]
                break

# Convert a motion CSV into per-joint [scalar, angular_speed] values.
def motion_csv_to_scalar_dataframe(
    input_path: Path,
    smoothing_factor: float = DEFAULT_SMOOTHING_FACTOR,
    release_smoothing_factor: float = DEFAULT_RELEASE_SMOOTHING_FACTOR,
    window_size: int = DEFAULT_WINDOW_SIZE,
    delta_frame: float = DEFAULT_DELTA_FRAME,
    startup_zero_frames: int = DEFAULT_STARTUP_ZERO_FRAMES,
    epsilon: float = EPSILON,
) -> pd.DataFrame:
    
    if not 0.0 <= smoothing_factor <= 1.0:
        raise ValueError("smoothing_factor must be between 0 and 1.")
    if not 0.0 <= release_smoothing_factor <= 1.0:
        raise ValueError("release_smoothing_factor must be between 0 and 1.")
    if window_size <= 0:
        raise ValueError("window_size must be a positive integer.")
    if delta_frame <= 0:
        raise ValueError("delta_frame must be positive.")
    if startup_zero_frames < 0:
        raise ValueError("startup_zero_frames cannot be negative.")
    if epsilon <= 0:
        raise ValueError("epsilon must be positive.")
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    dataframe = pd.read_csv(input_path)

    if "Frame index" not in dataframe.columns:
        raise ValueError("Input CSV must contain a 'Frame index' column.")

    joint_columns = [column for column in dataframe.columns if column != "Frame index"]
    output_rows: list[dict[str, object]] = []

    previous_quaternions: dict[str, tuple[float, float, float, float] | None] = {
        joint_name: None for joint_name in joint_columns
    }
    previous_scalars: dict[str, float] = {
        joint_name: 0.0 for joint_name in joint_columns
    }
    angular_speed_histories: dict[str, Deque[float]] = {
        joint_name: deque(maxlen=window_size) for joint_name in joint_columns
    }

    for frame_number, (_, row) in enumerate(dataframe.iterrows(), start=1):
        output_row: dict[str, object] = {"Frame index": row["Frame index"]}

        for joint_name in joint_columns:
            current_channels = parse_joint_channels(row[joint_name])
            current_euler_rotation = extract_euler_rotation(current_channels)
            current_quaternion = euler_rotation_to_quaternion(current_euler_rotation)
            angular_speed = compute_angular_speed(
                previous_quaternion=previous_quaternions[joint_name],
                current_quaternion=current_quaternion,
                delta_frame=delta_frame,
            )

            angular_speed_history = angular_speed_histories[joint_name]
            angular_speed_history.append(angular_speed)
            q95 = compute_q95(angular_speed_history)
            normalized_motion = min(max(angular_speed / (q95 + epsilon), 0.0), 1.0)

            previous_scalar = previous_scalars[joint_name]
            if frame_number <= startup_zero_frames:
                scalar = 0.0
            else:
                active_smoothing_factor = (
                    release_smoothing_factor
                    if normalized_motion < previous_scalar
                    else smoothing_factor
                )
                scalar = (
                    active_smoothing_factor * previous_scalar
                    + (1.0 - active_smoothing_factor) * normalized_motion
                )

            output_row[joint_name] = json.dumps([scalar, angular_speed])
            previous_quaternions[joint_name] = current_quaternion
            previous_scalars[joint_name] = scalar

        apply_joint_scalar_replacements(output_row)
        output_rows.append(output_row)

    return pd.DataFrame(output_rows)

# Save a scalar-enhanced motion CSV beside the source file.
def convert_motion_csv_to_scalar_csv(
    input_path: Path,
    output_path: Path | None = None,
    smoothing_factor: float = DEFAULT_SMOOTHING_FACTOR,
    release_smoothing_factor: float = DEFAULT_RELEASE_SMOOTHING_FACTOR,
    window_size: int = DEFAULT_WINDOW_SIZE,
    delta_frame: float = DEFAULT_DELTA_FRAME,
    startup_zero_frames: int = DEFAULT_STARTUP_ZERO_FRAMES,
    epsilon: float = EPSILON,
) -> Path:
    if output_path is None:
        output_path = input_path.with_name(f"{input_path.stem}_scalar.csv")

    scalar_dataframe = motion_csv_to_scalar_dataframe(
        input_path=input_path,
        smoothing_factor=smoothing_factor,
        release_smoothing_factor=release_smoothing_factor,
        window_size=window_size,
        delta_frame=delta_frame,
        startup_zero_frames=startup_zero_frames,
        epsilon=epsilon,
    )
    scalar_dataframe.to_csv(output_path, index=False)
    return output_path


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Convert a motion CSV into per-joint scalar and angular speed values."
    )
    default_input = default_path

    parser.add_argument(
        "input_csv",
        nargs="?",
        type=Path,
        default=default_input,
        help=f"Source CSV path. Defaults to {default_input}.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output CSV path. Defaults to <input>_scalar.csv.",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_SMOOTHING_FACTOR,
        help=f"Rising-motion smoothing factor. Default: {DEFAULT_SMOOTHING_FACTOR}.",
    )
    parser.add_argument(
        "--release-alpha",
        type=float,
        default=DEFAULT_RELEASE_SMOOTHING_FACTOR,
        help=(
            "Falling-motion smoothing factor. Higher values decay more slowly. "
            f"Default: {DEFAULT_RELEASE_SMOOTHING_FACTOR}."
        ),
    )
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW_SIZE,
        help=f"Rolling percentile window size. Default: {DEFAULT_WINDOW_SIZE}.",
    )
    parser.add_argument(
        "--delta-frame",
        type=float,
        default=DEFAULT_DELTA_FRAME,
        help=f"Frame delta used in the angular speed computation. Default: {DEFAULT_DELTA_FRAME}.",
    )
    parser.add_argument(
        "--startup-zero-frames",
        type=int,
        default=DEFAULT_STARTUP_ZERO_FRAMES,
        help=(
            "Number of initial frames whose scalar is forced to 0. "
            f"Default: {DEFAULT_STARTUP_ZERO_FRAMES}."
        ),
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=EPSILON,
        help=f"Small positive constant used during normalization. Default: {EPSILON}.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    output_path = convert_motion_csv_to_scalar_csv(
        input_path=args.input_csv,
        output_path=args.output,
        smoothing_factor=args.alpha,
        release_smoothing_factor=args.release_alpha,
        window_size=args.window,
        delta_frame=args.delta_frame,
        startup_zero_frames=args.startup_zero_frames,
        epsilon=args.epsilon,
    )
    print(f"Saved scalar CSV to: {output_path}")


if __name__ == "__main__":
    main()
