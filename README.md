# Motion-Vis

## ⛹️ Intro

Motion-Vis is a visualization tool that takes **BVH (Biovision Hierarchy)** motion capture files as input and visualizes human motion using Blender.

The visualization pipeline converts BVH files into CSV format and performs motion analysis by computing changes in joint rotations over time. The resulting visualization highlights how intensively different joints move throughout a motion sequence.

Most motion capture files primarily store **relative joint positions and rotations**, making it difficult to directly understand the intensity and activity level of individual joints across different motions. Motion-Vis addresses this by providing an intuitive visual representation that helps users better understand joint movement patterns.


## 🚶‍♂️ Demo

![boxing](./demo/gif/boxing.gif)

![walk](./demo/gif/walking.gif)

Demo examples are provided in the `demo/` directory.

Example visualizations include:

* Basic motions
* Dance motions
* Sport motions

## 💻 Requirements

Required software:

* Blender 5.0+

## ▶️ Getting Started

Example Blender files with pre-loaded BVH data are provided in the `blender_file/` directory.

To run an example:

1. Open Blender
2. Navigate to:

```text
blender_file/basic/basic.blend
```

3. Open the file
4. Press **Play** to view the motion visualization

Three motion categories are currently included:

* `basic`
* `dance`
* `sport`

For more detailed instructions, please refer to the `user_guide`.

## 🏝️ Directory Structure

```text
Motion-Vis/
├── blender_file/
│   ├── basic/              # Blender files for basic motions
│   ├── dance/              # Blender files for dance motions
│   └── sport/              # Blender files for sport motions
│
├── code/
│   ├── blender_script.py   # Blender execution script
│   ├── pen_joint_scalar.py # Convert CSV → scalar values
│   ├── scalar_vis.py       # Visualize scalar values
│   └── to_csv.py           # Convert BVH → CSV
│
├── data/
│   ├── humanoid/           # Humanoid OBJ models
│   └── mocap/              # Raw and processed motion capture data
│
└── demo/
    ├── sport_3/
    └── gif/
```

## 📬 Contact
Name: Yu Liu
Email: [claudeliu2002@gmail.com](mailto:claudeliu2002@gmail.com)
