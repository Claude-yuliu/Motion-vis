from __future__ import annotations

import csv
import json
from pathlib import Path

import bpy
from bpy.app.handlers import persistent

SCALAR_CSV_PATH = Path(r"F:\Yu\CMSC-DataVis\Motion-Vis\mocap\dance\02_scalar.csv")
MATERIAL_SUFFIX = "_MotionScalar"
TRAJECTORY_FRAME_INTERVAL = 200
TRAJECTORY_START_FRAME: int | None = None
TRAJECTORY_END_FRAME: int | None = None
TRAJECTORY_COLLECTION_NAME = "Motion Trajectory"
TRAJECTORY_MATERIAL_SUFFIX = "_Trajectory"
TRAJECTORY_ALPHA = 0.25  #default 0.25
COUNTER_OBJECT_NAME = "counter"

# Extract the scalar component from a [scalar, smoothed_speed] cell.
def parse_scalar_cell(raw_value: str) -> float:
    parsed = json.loads(raw_value)
    if not isinstance(parsed, list) or len(parsed) != 2:
        raise ValueError(
            "Expected each scalar cell to be a JSON list shaped like "
            "[scalar, smoothed_speed]."
        )
    return float(parsed[0])

# Load scalar values keyed by frame index and joint name.
def load_scalar_frame_data(csv_path: Path) -> tuple[dict[int, dict[str, float]], list[str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Scalar CSV not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "Frame index" not in reader.fieldnames:
            raise ValueError("Scalar CSV must contain a 'Frame index' column.")

        joint_names = [name for name in reader.fieldnames if name != "Frame index"]
        frame_data: dict[int, dict[str, float]] = {}

        for row in reader:
            frame_index = int(row["Frame index"])
            frame_data[frame_index] = {
                joint_name: parse_scalar_cell(row[joint_name])
                for joint_name in joint_names
                if row[joint_name] is not None
            }

    return frame_data, joint_names

# Map 0..1 to a light-yellow->red palette, with mid values pulled toward red.
def scalar_to_palette_color(scalar: float) -> tuple[float, float, float, float]:
    clamped_scalar = max(0.0, min(1.0, scalar))
    biased_scalar = clamped_scalar**0.55
    start_color = (1.0, 0.96, 0.35, 1.0)
    end_color = (1.0, 0.0, 0.0, 1.0)
    return (
        start_color[0] + (end_color[0] - start_color[0]) * biased_scalar,
        start_color[1] + (end_color[1] - start_color[1]) * biased_scalar,
        start_color[2] + (end_color[2] - start_color[2]) * biased_scalar,
        1.0,
    )

def color_with_alpha(
    color: tuple[float, float, float, float],
    alpha: float,
) -> tuple[float, float, float, float]:
    return (color[0], color[1], color[2], alpha)

def find_counter_object() -> bpy.types.Object | None:
    counter_obj = bpy.data.objects.get(COUNTER_OBJECT_NAME)
    if counter_obj is not None:
        return counter_obj

    for obj in bpy.data.objects:
        if obj.name.lower() == COUNTER_OBJECT_NAME:
            return obj

    return None

@persistent
def update_frame_counter(scene: bpy.types.Scene) -> None:
    counter_obj = find_counter_object()
    if counter_obj is None or counter_obj.type != "FONT":
        return

    counter_obj.data.body = f"Frame: {scene.frame_current}"

def register_frame_counter() -> None:
    bpy.app.handlers.frame_change_pre[:] = [
        handler
        for handler in bpy.app.handlers.frame_change_pre
        if getattr(handler, "__name__", "") != update_frame_counter.__name__
    ]
    bpy.app.handlers.frame_change_pre.append(update_frame_counter)
    update_frame_counter(bpy.context.scene)

    if find_counter_object() is None:
        print(
            f"[motion-vis] Frame counter not found. "
            f"Create a text object named '{COUNTER_OBJECT_NAME}' to show frames."
        )

# Remove existing object-color keys over the CSV frame range.
def clear_object_color_animation(
    obj: bpy.types.Object,
    frame_numbers: list[int],
) -> None:
    if not frame_numbers:
        return

    for frame_index in frame_numbers:
        try:
            obj.keyframe_delete(data_path="color", frame=frame_index)
        except RuntimeError:
            continue

# Ensure the object has one dedicated material configured to use Object Info color.
def ensure_object_material(obj: bpy.types.Object) -> bpy.types.Material | None:
    if obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
        return None
    if not hasattr(obj.data, "materials"):
        return None

    target_name = f"{obj.name}{MATERIAL_SUFFIX}"
    material = obj.active_material

    if material is None:
        material = bpy.data.materials.new(name=target_name)
        obj.data.materials.append(material)
    elif material.users > 1 or material.name != target_name:
        material = material.copy()
        material.name = target_name
        if obj.material_slots:
            obj.material_slots[0].material = material
        else:
            obj.data.materials.append(material)

    material.use_nodes = True
    node_tree = material.node_tree
    nodes = node_tree.nodes
    links = node_tree.links

    output_node = nodes.get("Material Output")
    if output_node is None:
        output_node = nodes.new(type="ShaderNodeOutputMaterial")

    bsdf_node = nodes.get("Principled BSDF")
    if bsdf_node is None:
        bsdf_node = nodes.new(type="ShaderNodeBsdfPrincipled")

    object_info_node = nodes.get("Object Info")
    if object_info_node is None:
        object_info_node = nodes.new(type="ShaderNodeObjectInfo")

    for link in list(bsdf_node.inputs["Base Color"].links):
        links.remove(link)

    if not any(
        link.from_node == object_info_node and link.to_node == bsdf_node
        and link.from_socket.name == "Color" and link.to_socket.name == "Base Color"
        for link in links
    ):
        links.new(object_info_node.outputs["Color"], bsdf_node.inputs["Base Color"])

    if not any(
        link.from_node == bsdf_node and link.to_node == output_node
        and link.from_socket.name == "BSDF" and link.to_socket.name == "Surface"
        for link in links
    ):
        links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

    return material

def ensure_transparent_copy_material(source_material: bpy.types.Material) -> bpy.types.Material:
    target_name = f"{source_material.name}{TRAJECTORY_MATERIAL_SUFFIX}"
    material = bpy.data.materials.get(target_name)
    if material is None:
        material = source_material.copy()
        material.name = target_name

    material.use_nodes = True
    material.blend_method = "BLEND"
    material.show_transparent_back = True
    if hasattr(material, "use_screen_refraction"):
        material.use_screen_refraction = True

    bsdf_node = material.node_tree.nodes.get("Principled BSDF")
    if bsdf_node is not None and "Alpha" in bsdf_node.inputs:
        bsdf_node.inputs["Alpha"].default_value = TRAJECTORY_ALPHA

    return material

def rebuild_trajectory_collection() -> bpy.types.Collection:
    existing_collection = bpy.data.collections.get(TRAJECTORY_COLLECTION_NAME)
    if existing_collection is not None:
        for obj in list(existing_collection.objects):
            data_block = obj.data if hasattr(obj, "data") else None
            bpy.data.objects.remove(obj, do_unlink=True)
            if (
                data_block is not None
                and data_block.users == 0
                and hasattr(bpy.data, "batch_remove")
            ):
                bpy.data.batch_remove([data_block])
        bpy.data.collections.remove(existing_collection, do_unlink=True)

    trajectory_collection = bpy.data.collections.new(TRAJECTORY_COLLECTION_NAME)
    bpy.context.scene.collection.children.link(trajectory_collection)
    return trajectory_collection

def detach_trajectory_object(obj: bpy.types.Object) -> None:
    obj.animation_data_clear()
    obj.parent = None
    obj.parent_type = "OBJECT"
    obj.parent_bone = ""

    for constraint in list(getattr(obj, "constraints", [])):
        obj.constraints.remove(constraint)
    for modifier in list(getattr(obj, "modifiers", [])):
        obj.modifiers.remove(modifier)
    for vertex_group in list(getattr(obj, "vertex_groups", [])):
        obj.vertex_groups.remove(vertex_group)

def copy_object_for_trajectory(
    obj: bpy.types.Object,
    evaluated_obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> bpy.types.Object:
    if obj.type == "MESH":
        mesh = bpy.data.meshes.new_from_object(evaluated_obj, depsgraph=depsgraph)
        trajectory_obj = bpy.data.objects.new(obj.name, mesh)
    else:
        trajectory_obj = obj.copy()
        if hasattr(obj, "data") and obj.data is not None:
            trajectory_obj.data = obj.data.copy()

    detach_trajectory_object(trajectory_obj)
    return trajectory_obj

def keyframe_trajectory_visibility(
    obj: bpy.types.Object,
    appear_frame: int,
    hide_before_frame: int,
    hide_after_frame: int | None = None,
) -> None:
    obj.hide_viewport = True
    obj.hide_render = True
    obj.keyframe_insert(data_path="hide_viewport", frame=hide_before_frame)
    obj.keyframe_insert(data_path="hide_render", frame=hide_before_frame)

    obj.hide_viewport = False
    obj.hide_render = False
    obj.keyframe_insert(data_path="hide_viewport", frame=appear_frame)
    obj.keyframe_insert(data_path="hide_render", frame=appear_frame)

    if hide_after_frame is not None:
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=hide_after_frame)
        obj.keyframe_insert(data_path="hide_render", frame=hide_after_frame)

def create_trajectory_motion(
    frame_data: dict[int, dict[str, float]],
    joint_names: list[str],
    frame_interval: int = TRAJECTORY_FRAME_INTERVAL,
    start_frame: int | None = TRAJECTORY_START_FRAME,
    end_frame: int | None = TRAJECTORY_END_FRAME,
) -> None:
    if frame_interval <= 0:
        raise ValueError("frame_interval must be a positive integer.")
    if not frame_data:
        return

    scene = bpy.context.scene
    original_frame = scene.frame_current
    frame_numbers = sorted(frame_data)
    csv_first_frame = frame_numbers[0]
    csv_last_frame = frame_numbers[-1]
    trajectory_start_frame = csv_first_frame if start_frame is None else start_frame
    trajectory_end_frame = csv_last_frame if end_frame is None else end_frame

    if trajectory_start_frame > trajectory_end_frame:
        raise ValueError("TRAJECTORY_START_FRAME must be less than or equal to TRAJECTORY_END_FRAME.")

    trajectory_frame_numbers = [
        frame_index
        for frame_index in frame_numbers
        if trajectory_start_frame <= frame_index <= trajectory_end_frame
    ]
    if not trajectory_frame_numbers:
        print(
            "[motion-vis] No trajectory copies created because no CSV frames fall "
            f"within {trajectory_start_frame}..{trajectory_end_frame}."
        )
        return

    sampled_frames = [
        frame_index
        for frame_index in trajectory_frame_numbers
        if (
            frame_index != trajectory_start_frame
            and (frame_index - trajectory_start_frame) % frame_interval == 0
        )
    ]
    target_objects = {
        joint_name: bpy.data.objects.get(joint_name)
        for joint_name in joint_names
        if bpy.data.objects.get(joint_name) is not None
    }
    trajectory_collection = rebuild_trajectory_collection()
    copied_count = 0

    for frame_index in sampled_frames:
        scene.frame_set(frame_index)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        frame_scalars = frame_data[frame_index]

        for joint_name, obj in target_objects.items():
            evaluated_obj = obj.evaluated_get(depsgraph)
            trajectory_obj = copy_object_for_trajectory(obj, evaluated_obj, depsgraph)
            trajectory_obj.name = f"{joint_name}_trajectory_{frame_index}"
            trajectory_obj.matrix_world = evaluated_obj.matrix_world.copy()
            trajectory_obj.color = color_with_alpha(
                scalar_to_palette_color(frame_scalars.get(joint_name, 0.0)),
                TRAJECTORY_ALPHA,
            )
            trajectory_obj.hide_select = True

            trajectory_collection.objects.link(trajectory_obj)
            source_material = obj.active_material or trajectory_obj.active_material
            if (
                source_material is not None
                and hasattr(trajectory_obj.data, "materials")
            ):
                trajectory_material = ensure_transparent_copy_material(source_material)
                trajectory_obj.data.materials.clear()
                trajectory_obj.data.materials.append(trajectory_material)
            keyframe_trajectory_visibility(
                obj=trajectory_obj,
                appear_frame=frame_index,
                hide_before_frame=max(trajectory_start_frame, frame_index - 1),
                hide_after_frame=trajectory_end_frame + 1,
            )
            copied_count += 1

    scene.frame_set(original_frame)
    print(
        f"[motion-vis] Created {copied_count} trajectory copies "
        f"every {frame_interval} frames within "
        f"{trajectory_start_frame}..{trajectory_end_frame}, "
        f"excluding frame {trajectory_start_frame}."
    )

# Bake CSV-driven object colors into keyframes
def bake_joint_colors(csv_path: Path) -> None:
    frame_data, joint_names = load_scalar_frame_data(csv_path)
    frame_numbers = sorted(frame_data)
    scene = bpy.context.scene
    existing_objects = [bpy.data.objects.get(joint_name) for joint_name in joint_names]
    target_objects = [obj for obj in existing_objects if obj is not None]

    for obj in target_objects:
        ensure_object_material(obj)
        clear_object_color_animation(obj, frame_numbers)

    for frame_index in frame_numbers:
        frame_scalars = frame_data[frame_index]     
        for joint_name in joint_names:
            obj = bpy.data.objects.get(joint_name)
            if obj is None:
                continue

            obj.color = scalar_to_palette_color(frame_scalars.get(joint_name, 0.0))
            obj.keyframe_insert(data_path="color", frame=frame_index)

    if frame_data:
        scene.frame_start = min(scene.frame_start, frame_numbers[0])
        scene.frame_end = max(scene.frame_end, frame_numbers[-1])
        scene.frame_set(scene.frame_current)

    missing_joint_names = [joint_name for joint_name in joint_names if bpy.data.objects.get(joint_name) is None]
    print(
        f"[motion-vis] Baked colors for {len(target_objects)} objects from {csv_path}."
    )
    if missing_joint_names:
        print(
            "[motion-vis] Missing scene objects for joints: "
            + ", ".join(missing_joint_names)
        )


def main() -> None:
    frame_data, joint_names = load_scalar_frame_data(SCALAR_CSV_PATH)
    register_frame_counter()
    bake_joint_colors(SCALAR_CSV_PATH)
    create_trajectory_motion(
        frame_data,
        joint_names,
        start_frame=TRAJECTORY_START_FRAME,
        end_frame=TRAJECTORY_END_FRAME,
    )


main()
