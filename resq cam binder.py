bl_info = {
    "name": "Camera Marker Binder",
    "author": "You",
    "version": (1, 3, 0),
    "blender": (2, 93, 0),
    "location": "3D Viewport > Ctrl + Alt + C  |  Sidebar > Cam Markers",
    "description": "Add a camera, navigate to frame it, press Enter to bind it to a timeline marker. "
                   "Also: bind all unbound cameras to markers, and a fast Cycles/GPU render preset.",
    "category": "Camera",
}

import bpy


# ===========================================================================
# PRIORITY 1: original workflow (Ctrl + Alt + C)  -- unchanged
# ===========================================================================

def next_marker_frame(scene):
    """Frame 1 (scene start) first, then one frame after the last camera marker."""
    cam_frames = [m.frame for m in scene.timeline_markers if m.camera]
    if not cam_frames:
        return scene.frame_start
    return max(cam_frames) + 1


class CAMERA_OT_marker_bind(bpy.types.Operator):
    """Add a camera, fly the view to frame it, press Enter to bind it to a marker"""
    bl_idname = "camera.marker_bind"
    bl_label = "Add Camera and Bind to Marker"
    bl_options = {'REGISTER', 'UNDO'}

    _cam = None
    _space = None

    @classmethod
    def poll(cls, context):
        return context.area and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        scene = context.scene
        space = context.space_data

        # 1. Add a camera
        cam_data = bpy.data.cameras.new("Camera")
        cam = bpy.data.objects.new("Camera", cam_data)
        context.collection.objects.link(cam)

        # 2. Make it the active camera / active object
        for o in context.selected_objects:
            o.select_set(False)
        cam.select_set(True)
        context.view_layer.objects.active = cam
        scene.camera = cam

        # 3. Match camera to current view, then enter camera view
        bpy.ops.view3d.camera_to_view()
        bpy.ops.view3d.view_camera()

        # 4. Enable navigation: "Lock Camera to View" so orbit/pan/zoom moves the camera
        space.lock_camera = True

        self._cam = cam
        self._space = space

        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "Navigate to frame your shot. Enter = bind to marker, Esc = cancel")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            scene = context.scene
            frame = next_marker_frame(scene)

            marker = scene.timeline_markers.new(self._cam.name, frame=frame)
            marker.camera = self._cam

            scene.frame_current = frame
            self._space.lock_camera = False
            self.report({'INFO'}, f"{self._cam.name} bound to marker at frame {frame}")
            return {'FINISHED'}

        if event.type == 'ESC' and event.value == 'PRESS':
            self._space.lock_camera = False
            bpy.data.objects.remove(self._cam, do_unlink=True)
            return {'CANCELLED'}

        # Let all other input through so view navigation works
        return {'PASS_THROUGH'}


# ===========================================================================
# Bind-all automation (catches cameras not bound via the shortcut)
# ===========================================================================

def get_scene_cameras(scene):
    """All camera objects in the scene, sorted by name."""
    cams = [obj for obj in scene.objects if obj.type == 'CAMERA']
    cams.sort(key=lambda o: o.name)
    return cams


class CAMERA_OT_bind_all_cameras(bpy.types.Operator):
    """Bind every camera in the scene that has no timeline marker yet"""
    bl_idname = "camera.bind_all_cameras"
    bl_label = "Bind All Cameras to Markers"
    bl_options = {'REGISTER', 'UNDO'}

    rebuild_all: bpy.props.BoolProperty(
        name="Rebuild All Markers",
        description="Delete all existing markers and recreate one per camera "
                    "(frames start at the scene start frame). "
                    "Off = only add markers for cameras that are not bound yet",
        default=False,
    )

    def execute(self, context):
        scene = context.scene
        cams = get_scene_cameras(scene)

        if not cams:
            self.report({'WARNING'}, "No cameras found in the scene.")
            return {'CANCELLED'}

        if self.rebuild_all:
            scene.timeline_markers.clear()
            to_bind = cams
        else:
            already_bound = {m.camera for m in scene.timeline_markers if m.camera}
            to_bind = [c for c in cams if c not in already_bound]

        if not to_bind:
            self.report({'INFO'}, "All cameras are already bound to markers.")
            return {'FINISHED'}

        for cam in to_bind:
            frame = next_marker_frame(scene)
            marker = scene.timeline_markers.new(cam.name, frame=frame)
            marker.camera = cam

        # End frame = last camera marker; start frame = first camera marker
        frames = [m.frame for m in scene.timeline_markers if m.camera]
        scene.frame_start = min(frames)
        scene.frame_end = max(frames)

        self.report(
            {'INFO'},
            f"Bound {len(to_bind)} camera(s). Frame range {scene.frame_start}-{scene.frame_end}."
        )
        return {'FINISHED'}


# ===========================================================================
# Render settings
# ===========================================================================

class CAMERA_OT_fast_render(bpy.types.Operator):
    """Switch to Cycles, set samples to 68, enable Simplify and Persistent Data, use GPU"""
    bl_idname = "camera.fast_render"
    bl_label = "Setup Fast Render (Cycles/GPU)"
    bl_options = {'REGISTER', 'UNDO'}

    samples: bpy.props.IntProperty(
        name="Samples",
        description="Render samples for Cycles",
        default=68,
        min=1,
    )

    def execute(self, context):
        scene = context.scene

        scene.render.engine = 'CYCLES'
        cycles = scene.cycles
        cycles.samples = self.samples
        scene.render.use_simplify = True
        cycles.use_persistent_data = True
        cycles.device = 'GPU'

        # Make sure the Cycles addon preferences have a GPU backend and
        # devices enabled, otherwise 'GPU' silently falls back to CPU.
        cycles_prefs = context.preferences.addons.get('cycles')
        if cycles_prefs is None:
            self.report(
                {'WARNING'},
                "Device set to GPU, but Cycles preferences were not found. "
                "Check Edit > Preferences > System manually."
            )
            return {'FINISHED'}

        cprefs = cycles_prefs.preferences

        backend_priority = ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI')
        current_backend = getattr(cprefs, 'compute_device_type', 'NONE')
        chosen_backend = current_backend if current_backend != 'NONE' else None

        if chosen_backend is None:
            for backend in backend_priority:
                try:
                    cprefs.compute_device_type = backend
                    chosen_backend = backend
                    break
                except TypeError:
                    continue

        if chosen_backend is None:
            self.report(
                {'WARNING'},
                "No GPU backend (OptiX/CUDA/HIP/Metal) available. "
                "Device is set to GPU but will fall back to CPU."
            )
            return {'FINISHED'}

        cprefs.get_devices()
        gpu_found = False
        for device in cprefs.devices:
            if device.type != 'CPU':
                device.use = True
                gpu_found = True
            else:
                device.use = False

        if not gpu_found:
            self.report(
                {'WARNING'},
                f"Backend '{chosen_backend}' selected, but no GPU detected. "
                "Check Edit > Preferences > System > Cycles Render Devices."
            )
        else:
            self.report(
                {'INFO'},
                f"Cycles: {self.samples} samples, Simplify on, "
                f"Persistent Data on, GPU ({chosen_backend})."
            )
        return {'FINISHED'}


# ===========================================================================
# UI
# ===========================================================================

class CAMERA_PT_marker_tools(bpy.types.Panel):
    """Sidebar panel in the 3D Viewport"""
    bl_label = "Cam Markers"
    bl_idname = "CAMERA_PT_marker_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Cam Markers"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        cams = get_scene_cameras(scene)
        bound = {m.camera for m in scene.timeline_markers if m.camera}
        unbound = [c for c in cams if c not in bound]

        col = layout.column()
        col.label(text="Add a camera: Ctrl + Alt + C")

        col.separator()
        col.label(text=f"Cameras: {len(cams)}   Unbound: {len(unbound)}")
        col.operator(CAMERA_OT_bind_all_cameras.bl_idname, icon='MARKER_HLT')

        col.separator()
        col.label(text="Render Settings")
        col.operator(CAMERA_OT_fast_render.bl_idname, icon='RESTRICT_RENDER_OFF')


def menu_func(self, context):
    self.layout.operator(CAMERA_OT_marker_bind.bl_idname, icon='CAMERA_DATA')


# ===========================================================================
# Registration
# ===========================================================================

classes = (
    CAMERA_OT_marker_bind,
    CAMERA_OT_bind_all_cameras,
    CAMERA_OT_fast_render,
    CAMERA_PT_marker_tools,
)

addon_keymaps = []


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Backup: View menu > "Add Camera and Bind to Marker"
    bpy.types.VIEW3D_MT_view.append(menu_func)

    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Object Mode", space_type='EMPTY')
        # Ctrl + Alt + C
        kmi = km.keymap_items.new(CAMERA_OT_marker_bind.bl_idname, 'C', 'PRESS', ctrl=True, alt=True)
        addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    bpy.types.VIEW3D_MT_view.remove(menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
