bl_info = {
    "name": "Camera Marker Binder",https://github.com/mrchinda/RENDER-HELPER-FOR-RESQ/tree/main
    "author": "In-house Tools",
    "version": (1, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Cam Markers",
    "description": "Creates one timeline marker per scene camera bound to that camera, sets the end frame to the camera count, and can set up a fast Cycles/GPU render preset.",
    "category": "Animation",
}

import bpy


def get_scene_cameras(scene):
    """Return all camera objects present in the scene, sorted by name."""
    cams = [obj for obj in scene.objects if obj.type == 'CAMERA']
    cams.sort(key=lambda o: o.name)
    return cams


class CAMMARKER_OT_bind_cameras_to_markers(bpy.types.Operator):
    """Create a marker per camera (frame 1..N), bind cameras, set end frame to N"""
    bl_idname = "cammarker.bind_cameras_to_markers"
    bl_label = "Bind Cameras to Markers"
    bl_options = {'REGISTER', 'UNDO'}

    clear_existing_markers: bpy.props.BoolProperty(
        name="Clear Existing Markers",
        description="Remove all existing timeline markers before creating new ones",
        default=True,
    )

    start_frame: bpy.props.IntProperty(
        name="Start Frame",
        description="Frame number for the first camera's marker",
        default=1,
        min=0,
    )

    def execute(self, context):
        scene = context.scene
        cams = get_scene_cameras(scene)

        if not cams:
            self.report({'WARNING'}, "No cameras found in the scene.")
            return {'CANCELLED'}

        if self.clear_existing_markers:
            scene.timeline_markers.clear()

        last_frame = self.start_frame
        for i, cam in enumerate(cams):
            frame = self.start_frame + i
            marker = scene.timeline_markers.new(name=cam.name, frame=frame)
            marker.camera = cam
            last_frame = frame

        # Set scene frame range to match: start at start_frame, end at last marker frame
        scene.frame_start = self.start_frame
        scene.frame_end = last_frame

        self.report(
            {'INFO'},
            f"Created {len(cams)} marker(s), frame_end set to {last_frame}."
        )
        return {'FINISHED'}


class CAMMARKER_OT_setup_fast_render(bpy.types.Operator):
    """Switch to Cycles, drop samples to 400, enable Simplify, turn on Persistent Data, and set device to GPU"""
    bl_idname = "cammarker.setup_fast_render"
    bl_label = "Setup Fast Render (Cycles/GPU)"
    bl_options = {'REGISTER', 'UNDO'}

    samples: bpy.props.IntProperty(
        name="Samples",
        description="Render samples for Cycles",
        default=400,
        min=1,
    )

    def execute(self, context):
        scene = context.scene

        # Switch render engine to Cycles
        scene.render.engine = 'CYCLES'
        cycles = scene.cycles

        # Drop sample count
        cycles.samples = self.samples

        # Enable Simplify
        scene.render.use_simplify = True

        # Enable Persistent Data
        cycles.use_persistent_data = True

        # Switch to GPU compute
        cycles.device = 'GPU'

        # Make sure the Cycles addon preferences actually have a GPU
        # backend selected and all available devices enabled, otherwise
        # cycles.device = 'GPU' silently falls back to CPU.
        prefs = context.preferences
        cycles_prefs = prefs.addons.get('cycles')

        if cycles_prefs is None:
            self.report(
                {'WARNING'},
                "Cycles device is set to GPU, but the Cycles addon "
                "preferences were not found to verify a backend/device. "
                "Check Edit > Preferences > System manually."
            )
            return {'FINISHED'}

        cprefs = cycles_prefs.preferences

        # Preferred backend order if none is already chosen
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
                "No GPU compute backend (OptiX/CUDA/HIP/Metal) is available "
                "on this system. Device is set to GPU but will fall back to CPU."
            )
            return {'FINISHED'}

        # Refresh and enable every detected device
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
                f"Backend '{chosen_backend}' selected, but no GPU device was "
                "detected. Check Edit > Preferences > System > Cycles Render Devices."
            )
        else:
            self.report(
                {'INFO'},
                f"Cycles set up: {self.samples} samples, Simplify on, "
                f"Persistent Data on, GPU device ({chosen_backend})."
            )

        return {'FINISHED'}


class CAMMARKER_PT_panel(bpy.types.Panel):
    """Panel in the 3D Viewport sidebar"""
    bl_label = "Cam Markers"
    bl_idname = "CAMMARKER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Cam Markers"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        cams = get_scene_cameras(scene)

        col = layout.column()
        col.label(text=f"Cameras found: {len(cams)}")

        op = col.operator(
            CAMMARKER_OT_bind_cameras_to_markers.bl_idname,
            icon='MARKER_HLT',
        )

        col.separator()
        col.label(text="Options are also available in the")
        col.label(text="operator redo panel (bottom-left).")

        col.separator()
        col.label(text="Render Settings")
        col.operator(
            CAMMARKER_OT_setup_fast_render.bl_idname,
            icon='RESTRICT_RENDER_OFF',
        )


classes = (
    CAMMARKER_OT_bind_cameras_to_markers,
    CAMMARKER_OT_setup_fast_render,
    CAMMARKER_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
