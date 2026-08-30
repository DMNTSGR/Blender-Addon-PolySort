bl_info = {
    "name": "PolySort",
    "author": "DMNTSGR",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > N-Panel > PolySort",
    "description": "Polygon Sort - Sorts scene models by face count in descending order, placing the heaviest meshes at the top.",
    "category": "3D View",
}

import re
import bpy


_PREFIX_RE = re.compile(r'^[A-Za-z]{1,4}_')


def strip_prefix(name):
    """Drop a short leading naming-convention prefix like SM_, sm_, Mesh_ for sorting."""
    return _PREFIX_RE.sub('', name)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class HPB_ListItem(bpy.types.PropertyGroup):
    obj_name: bpy.props.StringProperty()
    faces: bpy.props.IntProperty()


_syncing_from_scene = False


def _select_active_item(self, context):
    """Runs when the user clicks a row in the list: select + zoom to it."""
    if _syncing_from_scene:
        return

    props = context.scene.hpb_props
    if props.active_index < 0 or props.active_index >= len(props.items):
        return
    item = props.items[props.active_index]
    obj = context.scene.objects.get(item.obj_name)
    if obj is None:
        return

    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj

    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        override = context.copy()
                        override["area"] = area
                        override["region"] = region
                        with context.temp_override(**override):
                            bpy.ops.view3d.view_selected()
                        break
                break


class HPB_Properties(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=HPB_ListItem)
    active_index: bpy.props.IntProperty(update=_select_active_item)


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------

def scan_polycounts(context):
    global _syncing_from_scene

    depsgraph = context.evaluated_depsgraph_get()
    results = []

    for obj in context.scene.objects:
        if obj.type != 'MESH':
            continue
        try:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            count = len(mesh.polygons)
            eval_obj.to_mesh_clear()
        except RuntimeError:
            count = len(obj.data.polygons)
        results.append((obj.name, count))

    results.sort(key=lambda x: x[1], reverse=True)

    props = context.scene.hpb_props
    props.items.clear()
    for name, count in results:
        item = props.items.add()
        item.name = name
        item.obj_name = name
        item.faces = count

    # keep the list pointed at whatever is actually selected in the scene
    active_obj = context.view_layer.objects.active
    if active_obj is not None:
        for i, item in enumerate(props.items):
            if item.obj_name == active_obj.name:
                if props.active_index != i:
                    _syncing_from_scene = True
                    props.active_index = i
                    _syncing_from_scene = False
                break


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class HPB_OT_refresh(bpy.types.Operator):
    bl_idname = "hpb.refresh"
    bl_label = ""
    bl_description = "Force a refresh (use this if the list doesn't update on its own)"

    def execute(self, context):
        scan_polycounts(context)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Timer (auto-refresh)
# ---------------------------------------------------------------------------

def _timer_tick():
    context = bpy.context
    scene = context.scene
    if scene is None or not hasattr(scene, "hpb_props"):
        return 2.0

    scan_polycounts(context)
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    return 2.0


# ---------------------------------------------------------------------------
# UIList (resizable board, working search + prefix-aware sort)
# ---------------------------------------------------------------------------

class HPB_UL_items(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        split = layout.split(factor=0.7)
        split.label(text=f"{index+1}. {item.obj_name}")
        count_col = split.row()
        count_col.alignment = 'RIGHT'
        count_col.label(text=f"{item.faces:,} faces")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        helper = bpy.types.UI_UL_list

        # search bar: plain "contains" match anywhere in the name, case-insensitive
        if self.filter_name:
            search = self.filter_name.lower()
            filtered = [
                self.bitflag_filter_item if search in item.obj_name.lower() else 0
                for item in items
            ]
        else:
            filtered = [self.bitflag_filter_item] * len(items)

        # A-Z sort: ignore short naming prefixes like SM_ when ordering
        if self.use_filter_sort_alpha:
            ordered = helper.sort_items_helper(
                [(i, strip_prefix(item.obj_name).lower()) for i, item in enumerate(items)],
                key=lambda pair: pair[1],
            )
        else:
            ordered = []

        return filtered, ordered


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class HPB_PT_panel(bpy.types.Panel):
    bl_label = "PolySort"
    bl_idname = "HPB_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PolySort"

    def draw(self, context):
        layout = self.layout
        props = context.scene.hpb_props

        layout.operator("hpb.refresh", icon='FILE_REFRESH')

        # list_id enables the native drag-to-resize grip at the bottom-right
        layout.template_list(
            "HPB_UL_items", "hpb_list",
            props, "items",
            props, "active_index",
            rows=5,
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

classes = (
    HPB_ListItem,
    HPB_Properties,
    HPB_OT_refresh,
    HPB_UL_items,
    HPB_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.hpb_props = bpy.props.PointerProperty(type=HPB_Properties)
    if not bpy.app.timers.is_registered(_timer_tick):
        bpy.app.timers.register(_timer_tick, first_interval=1.0)


def unregister():
    if bpy.app.timers.is_registered(_timer_tick):
        bpy.app.timers.unregister(_timer_tick)
    del bpy.types.Scene.hpb_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
