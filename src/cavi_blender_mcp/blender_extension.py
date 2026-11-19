"""Sidebar controls for the bridge inside an interactive Blender with user preferences."""

import bpy

from . import blender_bridge

_errors = []


def start():
    _errors.clear()
    try:
        blender_bridge.register()
    except (OSError, RuntimeError, ValueError) as exc:
        _errors.append(str(exc))
        return False
    return True


def start_after_startup():
    start()


class CAVI_OT_bridge_start(bpy.types.Operator):
    bl_idname = "cavi.bridge_start"
    bl_label = "Start Bridge"
    bl_description = "Accept MCP tool calls in this Blender session"

    def execute(self, context):
        if start():
            return {"FINISHED"}
        self.report({"ERROR"}, _errors[0])
        return {"CANCELLED"}


class CAVI_OT_bridge_stop(bpy.types.Operator):
    bl_idname = "cavi.bridge_stop"
    bl_label = "Stop Bridge"
    bl_description = "Stop accepting MCP tool calls in this Blender session"

    def execute(self, context):
        blender_bridge.unregister()
        return {"FINISHED"}


class CAVI_PT_bridge(bpy.types.Panel):
    bl_label = "MCP Bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "CAVI"

    def draw(self, context):
        workspace = blender_bridge.serving_workspace()
        if workspace is not None:
            self.layout.label(text="Running", icon="CHECKMARK")
            self.layout.label(text=str(workspace))
            self.layout.operator(CAVI_OT_bridge_stop.bl_idname)
            return
        for reason in _errors:
            self.layout.label(text=reason, icon="ERROR")
        self.layout.operator(CAVI_OT_bridge_start.bl_idname)


CLASSES = (CAVI_OT_bridge_start, CAVI_OT_bridge_stop, CAVI_PT_bridge)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    # Background runs (renders, `blender --command`, runtime start) never take the connection.
    if not bpy.app.background:
        # Startup restricts bpy.data while add-ons register; the timer runs once the UI is up.
        bpy.app.timers.register(start_after_startup, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(start_after_startup):
        bpy.app.timers.unregister(start_after_startup)
    blender_bridge.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
