"""Stable action identifiers shared by the scene tree and application layer."""

from enum import StrEnum


class SceneAction(StrEnum):
    VISIBILITY_CHANGED = "visibility_changed"
    SAVE_PROJECT = "save_project"
    IMPORT_POINT_CLOUD = "import_point_cloud"
    IMPORT_CAD = "import_cad"
    IMPORT_ROBOT = "import_robot"
    SET_POINT_CLOUD_POSE = "set_point_cloud_pose"
    SET_CAD_MODEL_POSE = "set_cad_model_pose"
    PROCESS_POINT_CLOUD = "process_point_cloud"
    CROP_POINT_CLOUD = "crop_point_cloud"
    FORWARD_KINEMATICS = "forward_kinematics"
    INVERSE_KINEMATICS = "inverse_kinematics"
    COLLISION_CHECK = "collision_check"
    RENAME_NODE = "rename_node"
    DELETE_NODE = "delete_node"
