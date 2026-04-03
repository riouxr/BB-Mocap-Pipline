bl_info = {
    "name": "Mocap Pipeline",
    "author": "Pipeline Tool",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > N-Panel > Mocap Pipeline",
    "description": "Automates the Tarena character pipeline",
    "category": "Pipeline",
}

import bpy
import os
import re


def get_action_fcurves(action):
    if action is None:
        return []
    if hasattr(action, 'layers') and len(action.layers) > 0:
        fcurves_list = []
        for layer in action.layers:
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    fcurves_list.extend(channelbag.fcurves)
        return fcurves_list
    if hasattr(action, 'fcurves'):
        return action.fcurves
    return []


def copy_fcurve_keyframes(src_fcurve, tgt_fcurve):
    while len(tgt_fcurve.keyframe_points) > 0:
        tgt_fcurve.keyframe_points.remove(tgt_fcurve.keyframe_points[0])
    for kf in src_fcurve.keyframe_points:
        new_kf = tgt_fcurve.keyframe_points.insert(kf.co.x, kf.co.y)
        new_kf.interpolation = kf.interpolation
        new_kf.handle_left_type = kf.handle_left_type
        new_kf.handle_right_type = kf.handle_right_type
        new_kf.handle_left = kf.handle_left
        new_kf.handle_right = kf.handle_right
    tgt_fcurve.extrapolation = src_fcurve.extrapolation
    tgt_fcurve.color_mode = src_fcurve.color_mode
    tgt_fcurve.color = src_fcurve.color


def get_or_create_fcurve(action, data_path, array_index=0, target_data=None):
    fcurves = get_action_fcurves(action)
    for fc in fcurves:
        if fc.data_path == data_path and fc.array_index == array_index:
            return fc
    if hasattr(action, 'layers'):
        if len(action.layers) == 0:
            action.layers.new("Layer")
        layer = action.layers[0]
        if len(layer.strips) == 0:
            layer.strips.new(type='KEYFRAME')
        strip = layer.strips[0]
        slot = None
        if hasattr(strip, 'channelbags'):
            if target_data is not None and hasattr(action, 'slots'):
                for s in action.slots:
                    if hasattr(s, 'target') and s.target == target_data:
                        slot = s
                        break
                if slot is None:
                    try:
                        slot = action.slots.new(id_type='KEY', name=target_data.name if target_data else "Key")
                        if hasattr(action, 'assign_id') and target_data:
                            try:
                                action.assign_id(slot, target_data)
                            except Exception:
                                pass
                    except Exception:
                        pass
            channelbag = None
            for cb in strip.channelbags:
                if slot is None or (hasattr(cb, 'slot_handle') and slot and cb.slot_handle == slot.handle):
                    channelbag = cb
                    break
            if channelbag is None:
                try:
                    channelbag = strip.channelbags.new(slot) if slot else strip.channelbags.new()
                except Exception:
                    return None
            return channelbag.fcurves.new(data_path=data_path, index=array_index)
    if hasattr(action, 'fcurves'):
        return action.fcurves.new(data_path=data_path, index=array_index)
    return None


def run_copy_animation(source_obj, target_obj):
    if source_obj is None or target_obj is None:
        return False, "Source or target object not found."
    key_tgt = target_obj.data.shape_keys
    if key_tgt is None:
        return False, f"'{target_obj.name}' has no shape keys."
    if key_tgt.animation_data is None:
        key_tgt.animation_data_create()
    if key_tgt.animation_data.action is None:
        key_tgt.animation_data.action = bpy.data.actions.new(name=f"{target_obj.name}_ShapekeyAction")
    action_tgt = key_tgt.animation_data.action
    if hasattr(action_tgt, 'slots') and len(action_tgt.slots) > 0:
        if hasattr(action_tgt, 'assign_id'):
            try:
                action_tgt.assign_id(None, key_tgt)
            except Exception:
                pass
    copied_curves = 0
    skipped_curves = 0
    key_src = source_obj.data.shape_keys
    if key_src is None or key_src.animation_data is None or key_src.animation_data.action is None:
        return False, f"'{source_obj.name}' has no shapekey animation."
    action_src = key_src.animation_data.action
    src_fcurves = get_action_fcurves(action_src)
    for src_fcurve in src_fcurves:
        if not src_fcurve.data_path.startswith('key_blocks'):
            continue
        match = re.match(r'key_blocks\["(.+?)"\]\.value', src_fcurve.data_path)
        if not match:
            continue
        key_name = match.group(1)
        if key_name not in key_src.key_blocks or key_name not in key_tgt.key_blocks:
            skipped_curves += 1
            continue
        data_path = f'key_blocks["{key_name}"].value'
        tgt_fcurve = get_or_create_fcurve(action_tgt, data_path, src_fcurve.array_index, key_tgt)
        if tgt_fcurve is None:
            skipped_curves += 1
            continue
        try:
            copy_fcurve_keyframes(src_fcurve, tgt_fcurve)
            copied_curves += 1
        except Exception:
            skipped_curves += 1
    if hasattr(action_tgt, 'slots') and len(action_tgt.slots) > 0:
        slot = action_tgt.slots[0]
        if hasattr(key_tgt.animation_data, 'action_slot_handle'):
            key_tgt.animation_data.action_slot_handle = slot.handle
    return True, f"Copied {copied_curves} animation curve(s), skipped {skipped_curves}."


def run_copy_armature_anim(source_arm, target_arm):
    if source_arm is None or target_arm is None:
        return False, "Source or target armature not found."
    if source_arm.type != 'ARMATURE' or target_arm.type != 'ARMATURE':
        return False, "Both objects must be armatures."
    if target_arm.animation_data is None:
        target_arm.animation_data_create()
    ad_tgt = target_arm.animation_data
    ad_src = source_arm.animation_data
    if ad_src is None:
        return False, f"'{source_arm.name}' has no animation data."
    copied_strips = 0
    slot_action_assigned = False
    if ad_src.action:
        src_action = ad_src.action
        source_slot_handle = None
        source_slot_name = None
        if hasattr(src_action, 'slots'):
            if hasattr(ad_src, 'action_slot_handle'):
                source_slot_handle = ad_src.action_slot_handle
                for slot in src_action.slots:
                    if hasattr(slot, 'handle') and slot.handle == source_slot_handle:
                        source_slot_name = slot.name_display if hasattr(slot, 'name_display') else slot.name
                        break
        new_action = src_action.copy()
        new_action.name = f"{target_arm.name}_{src_action.name}"
        ad_tgt.action = new_action
        if hasattr(new_action, 'slots'):
            armature_slot = None
            armature_slot_handle = None
            for slot in new_action.slots:
                slot_name = slot.name_display if hasattr(slot, 'name_display') else slot.name
                slot_id_type = slot.id_type if hasattr(slot, 'id_type') else None
                slot_handle = slot.handle if hasattr(slot, 'handle') else None
                if (slot_id_type == 'ARMATURE') or (source_slot_name and slot_name == source_slot_name):
                    armature_slot = slot
                    armature_slot_handle = slot_handle
                    break
            if armature_slot and armature_slot_handle:
                if hasattr(ad_tgt, 'action_slot_handle'):
                    ad_tgt.action_slot_handle = armature_slot_handle
                if hasattr(new_action, 'assign_id'):
                    try:
                        new_action.assign_id(armature_slot, target_arm.data)
                    except Exception:
                        pass
        slot_action_assigned = True
    if ad_src.nla_tracks:
        for track in ad_src.nla_tracks:
            new_track = ad_tgt.nla_tracks.new()
            new_track.name = track.name
            for strip in track.strips:
                ns = new_track.strips.new(strip.name, int(strip.frame_start), strip.action)
                ns.frame_end = strip.frame_end
                copied_strips += 1
    if slot_action_assigned and copied_strips > 0:
        msg = f"Assigned slot action and copied {copied_strips} NLA strip(s)."
    elif slot_action_assigned:
        msg = "Assigned slot action."
    elif copied_strips > 0:
        msg = f"Copied {copied_strips} NLA strip(s)."
    else:
        msg = "No animation data found to copy."
    return True, msg


def delete_with_hierarchy(obj):
    def collect_children(o):
        result = [o]
        for child in o.children:
            result.extend(collect_children(child))
        return result
    to_delete = collect_children(obj)
    for o in reversed(to_delete):
        bpy.data.objects.remove(o, do_unlink=True)


def get_bone_children_recursive(armature_data, bone_name):
    result = []
    def recurse(name):
        result.append(name)
        for bone in armature_data.bones:
            if bone.parent and bone.parent.name == name:
                recurse(bone.name)
    recurse(bone_name)
    return result


def delete_keyframes_from_frame(armature_obj, bone_names, from_frame=70, channel=None):
    """
    Delete keyframes at frame >= from_frame for the given bone names.
    channel: if None deletes all channels; pass 'location', 'rotation_euler', etc.
             to restrict deletion to that channel type only.
    """
    if armature_obj is None or armature_obj.type != 'ARMATURE':
        return False, "Not a valid armature object."
    if armature_obj.animation_data is None or armature_obj.animation_data.action is None:
        return False, "Armature has no animation data or action."

    if isinstance(bone_names, str):
        bone_names = [bone_names]

    action = armature_obj.animation_data.action
    fcurves = get_action_fcurves(action)
    deleted_count = 0

    for fc in fcurves:
        bone_match = any(
            fc.data_path.startswith(f'pose.bones["{name}"]') for name in bone_names
        )
        if not bone_match:
            continue
        if channel is not None and not fc.data_path.endswith(f'.{channel}'):
            continue
        indices = [i for i, kp in enumerate(fc.keyframe_points) if kp.co.x >= from_frame]
        for i in reversed(indices):
            fc.keyframe_points.remove(fc.keyframe_points[i])
            deleted_count += 1
        if indices:
            fc.keyframe_points.handles_recalc()

    return True, f"Deleted {deleted_count} keyframe(s) >= frame {from_frame} across {len(bone_names)} bone(s)."


def save_objects_as_blend(filepath, objects):
    if not filepath.lower().endswith('.blend'):
        filepath += '.blend'
    sel_objs = list(objects)
    if not sel_objs:
        return False, "No objects to export."
    temp_scene = bpy.data.scenes.new("TempExportScene")
    temp_root = temp_scene.collection
    for obj in sel_objs:
        try:
            temp_root.objects.link(obj)
        except RuntimeError:
            pass
    datablocks = {temp_scene, temp_root}
    bpy.data.libraries.write(filepath, datablocks=datablocks, path_remap='RELATIVE')
    bpy.data.scenes.remove(temp_scene)
    return True, f"Exported blend to {filepath}"


class TARENA_OT_ApplyAnimation(bpy.types.Operator):
    """Import FBX, copy animation/armature data, then delete the Armature."""
    bl_idname = "tarena.apply_animation"
    bl_label = "Apply Animation"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        num = context.scene.tarena_number.strip()
        if not num:
            self.report({'ERROR'}, "Please enter a number (e.g. 01, 02).")
            return {'CANCELLED'}

        base_path = r"I:\Tarena 2026\04_Resources\Export"
        fbx_path = os.path.join(base_path, f"{num}.fbx")

        # 1. Import FBX
        if not os.path.isfile(fbx_path):
            self.report({'ERROR'}, f"FBX not found: {fbx_path}")
            return {'CANCELLED'}
        try:
            bpy.ops.import_scene.fbx(filepath=fbx_path)
        except Exception as e:
            self.report({'ERROR'}, f"FBX import failed: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Imported FBX: {fbx_path}")

        # 2. Copy Animation: CC_Base_Body -> OldManBody
        cc_body = bpy.data.objects.get("CC_Base_Body")
        old_man_body = bpy.data.objects.get("OldManBody")
        if cc_body is None:
            self.report({'ERROR'}, "Object 'CC_Base_Body' not found.")
            return {'CANCELLED'}
        if old_man_body is None:
            self.report({'ERROR'}, "Object 'OldManBody' not found.")
            return {'CANCELLED'}
        ok, msg = run_copy_animation(cc_body, old_man_body)
        self.report({'INFO' if ok else 'WARNING'}, f"Copy Animation: {msg}")

        # 3. Copy Armature: Armature -> MasterOldMan
        armature_obj = bpy.data.objects.get("Armature")
        master_old_man = bpy.data.objects.get("MasterOldMan")
        if armature_obj is None:
            self.report({'ERROR'}, "Object 'Armature' not found.")
            return {'CANCELLED'}
        if master_old_man is None:
            self.report({'ERROR'}, "Object 'MasterOldMan' not found.")
            return {'CANCELLED'}
        ok, msg = run_copy_armature_anim(armature_obj, master_old_man)
        self.report({'INFO' if ok else 'WARNING'}, f"Copy Armature: {msg}")

        # 4. Scan Armature for last keyframe BEFORE deleting it
        armature_obj = bpy.data.objects.get("Armature")
        last_frame = 0
        if armature_obj and armature_obj.animation_data and armature_obj.animation_data.action:
            action = armature_obj.animation_data.action
            for fc in get_action_fcurves(action):
                for kp in fc.keyframe_points:
                    if kp.co.x > last_frame:
                        last_frame = kp.co.x

        if armature_obj:
            delete_with_hierarchy(armature_obj)
            self.report({'INFO'}, "Deleted 'Armature' and its hierarchy.")

        # 5. Set scene frame range: 0 to last keyframe found on Armature
        if last_frame > 0:
            context.scene.frame_start = 0
            context.scene.frame_end = int(last_frame)
            self.report({'INFO'}, f"Frame range set to 0 – {int(last_frame)}.")
        else:
            self.report({'WARNING'}, "Could not determine last keyframe; frame range unchanged.")

        self.report({'INFO'}, "Apply Animation complete!")
        return {'FINISHED'}


class TARENA_OT_FixPelvis(bpy.types.Operator):
    """Stabilize feet and hip: IK plants feet, Copy Rotation freezes foot orientation."""
    bl_idname = "tarena.fix_pelvis"
    bl_label = "Fix Pelvis"
    bl_options = {'REGISTER', 'UNDO'}

    FOOT_BONES = {
        'L': 'CC_Base_L_Foot',
        'R': 'CC_Base_R_Foot',
    }
    IK_BONE_NAMES = {
        'L': 'IK_L_Foot',
        'R': 'IK_R_Foot',
    }

    def execute(self, context):
        from_frame = context.scene.frame_current
        scene = context.scene
        frame_start = scene.frame_start
        frame_end = scene.frame_end

        master = bpy.data.objects.get("MasterOldMan")
        if master is None:
            self.report({'ERROR'}, "Object 'MasterOldMan' not found.")
            return {'CANCELLED'}
        if master.type != 'ARMATURE':
            self.report({'ERROR'}, "'MasterOldMan' is not an armature.")
            return {'CANCELLED'}

        for side, bone_name in self.FOOT_BONES.items():
            if bone_name not in master.pose.bones:
                self.report({'ERROR'}, f"Foot bone '{bone_name}' not found.")
                return {'CANCELLED'}

        context.view_layer.objects.active = master
        original_frame = scene.frame_current

        # ----------------------------------------------------------------
        # Step 1 — Bake foot world matrices BEFORE touching anything.
        # pb.matrix is armature-local and includes both position and rotation.
        # ----------------------------------------------------------------
        bpy.ops.object.mode_set(mode='POSE')

        foot_matrices = {'L': {}, 'R': {}}
        for frame in range(frame_start, frame_end + 1):
            scene.frame_set(frame)
            context.view_layer.update()
            for side, bone_name in self.FOOT_BONES.items():
                foot_matrices[side][frame] = master.pose.bones[bone_name].matrix.copy()

        # The last good frame is the freeze pose
        freeze_frame = max(frame_start, from_frame - 1)
        freeze_matrices = {side: foot_matrices[side][freeze_frame] for side in ('L', 'R')}

        scene.frame_set(original_frame)
        self.report({'INFO'}, f"Baked foot matrices ({frame_end - frame_start + 1} frames).")

        # ----------------------------------------------------------------
        # Step 2 — Create IK target bones (no parent, no deform).
        # ----------------------------------------------------------------
        bpy.ops.object.mode_set(mode='EDIT')
        arm = master.data

        IK_POSITIONS = {
            'L': (-6.2818,  1.938,  1.4554),
            'R': (-34.109,  1.5,   17.488),
        }

        for side, ik_name in self.IK_BONE_NAMES.items():
            eb = arm.edit_bones.get(ik_name) or arm.edit_bones.new(ik_name)
            head = IK_POSITIONS[side]
            eb.head = head
            eb.tail = (head[0], head[1], head[2] + 0.1)
            eb.parent = None
            eb.use_deform = False

        self.report({'INFO'}, "Created IK target bones.")

        # ----------------------------------------------------------------
        # Step 3 — Keyframe IK targets:
        #   Before from_frame  → follow original baked position + rotation
        #   From from_frame on → frozen at freeze_frame value
        # ----------------------------------------------------------------
        bpy.ops.object.mode_set(mode='POSE')

        for frame in range(frame_start, frame_end + 1):
            scene.frame_set(frame)
            for side, ik_name in self.IK_BONE_NAMES.items():
                ik_pb = master.pose.bones[ik_name]
                mat = foot_matrices[side][frame] if frame < from_frame else freeze_matrices[side]
                # Assign the full matrix — Blender computes pose.location
                # relative to the bone's rest position automatically.
                ik_pb.matrix = mat
                context.view_layer.update()
                ik_pb.keyframe_insert(data_path="location", frame=frame)
                ik_pb.rotation_mode = 'XYZ'
                ik_pb.keyframe_insert(data_path="rotation_euler", frame=frame)

        scene.frame_set(original_frame)
        self.report({'INFO'}, f"Keyframed IK targets (frozen from frame {from_frame}).")

        # ----------------------------------------------------------------
        # Step 4 — Add IK constraint on foot bones (position only).
        # ----------------------------------------------------------------
        for side, foot_name in self.FOOT_BONES.items():
            foot_pb = master.pose.bones[foot_name]
            ik_name = self.IK_BONE_NAMES[side]

            for c in list(foot_pb.constraints):
                if c.type in ('IK', 'COPY_ROTATION'):
                    foot_pb.constraints.remove(c)

            ik = foot_pb.constraints.new('IK')
            ik.target = master
            ik.subtarget = ik_name
            ik.chain_count = 2
            ik.use_rotation = False

        self.report({'INFO'}, "Added IK constraints on both feet (position only).")

        # ----------------------------------------------------------------
        # Step 5 — Freeze foot rotation from from_frame onwards.
        # We directly overwrite the rotation keyframes on the foot bones
        # using the freeze matrix, avoiding any constraint space mismatch.
        # First delete all rotation keyframes from from_frame, then insert
        # a single keyframe at from_frame with the frozen rotation and hold.
        # ----------------------------------------------------------------
        bpy.ops.object.mode_set(mode='POSE')

        for side, foot_name in self.FOOT_BONES.items():
            foot_pb = master.pose.bones[foot_name]

            # Delete all rotation keyframes from from_frame onwards
            delete_keyframes_from_frame(
                master, [foot_name], from_frame=from_frame, channel='rotation_euler'
            )
            delete_keyframes_from_frame(
                master, [foot_name], from_frame=from_frame, channel='rotation_quaternion'
            )

            # Set the frozen rotation directly on the pose bone and keyframe it.
            # pb.matrix is armature-local; we write it back the same way.
            freeze_mat = freeze_matrices[side]
            scene.frame_set(from_frame)

            # Write the matrix back through the bone's parent inverse
            # so the pose channels reflect the correct local rotation.
            foot_pb.matrix = freeze_mat
            context.view_layer.update()

            foot_pb.rotation_mode = 'XYZ'
            foot_pb.keyframe_insert(data_path="rotation_euler", frame=from_frame)

            # Set the fcurve extrapolation to CONSTANT so it holds forever
            action = master.animation_data.action
            if action:
                bone_path = f'pose.bones["{foot_name}"].rotation_euler'
                for fc in get_action_fcurves(action):
                    if fc.data_path == bone_path:
                        fc.extrapolation = 'CONSTANT'

        scene.frame_set(original_frame)
        self.report({'INFO'}, "Frozen foot rotations baked directly onto foot bones.")

        # ----------------------------------------------------------------
        # Step 6 — Delete CC_Base_Hip location from from_frame onwards.
        # ----------------------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')
        ok, msg = delete_keyframes_from_frame(
            master, ["CC_Base_Hip"], from_frame=from_frame, channel='location'
        )
        self.report({'INFO' if ok else 'WARNING'}, f"Hip location cleanup: {msg}")

        self.report({'INFO'}, "Fix Pelvis complete!")
        return {'FINISHED'}


class TARENA_OT_ExportAlembic(bpy.types.Operator):
    """Delete pelvis/leg keyframes, export & re-import Alembic, then export .blend."""
    bl_idname = "tarena.export_alembic"
    bl_label = "Export Alembic"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        num = context.scene.tarena_number.strip()
        if not num:
            self.report({'ERROR'}, "Please enter a number (e.g. 01, 02).")
            return {'CANCELLED'}

        base_path = r"I:\Tarena 2026\04_Resources\Export"
        abc_path = os.path.join(base_path, f"{num}.abc")
        blend_path = os.path.join(base_path, f"{num}.blend")

        # 5. Select Hair, OldManBody, Pareo -> export Alembic
        bpy.ops.object.select_all(action='DESELECT')
        export_names = ["Hair", "OldManBody", "Pareo"]
        missing = []
        for name in export_names:
            obj = bpy.data.objects.get(name)
            if obj:
                obj.select_set(True)
            else:
                missing.append(name)
        if missing:
            self.report({'ERROR'}, f"Objects not found for Alembic export: {missing}")
            return {'CANCELLED'}
        try:
            bpy.ops.wm.alembic_export(filepath=abc_path, selected=True, face_sets=True)
        except Exception as e:
            self.report({'ERROR'}, f"Alembic export failed: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Exported Alembic: {abc_path}")

        # 7. Import the Alembic
        try:
            bpy.ops.wm.alembic_import(filepath=abc_path)
        except Exception as e:
            self.report({'ERROR'}, f"Alembic import failed: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Imported Alembic: {abc_path}")

        # 7b. Add Subdivision modifier to OldManBody.002 and Pareo.001
        for obj_name in ["OldManBody.002", "Pareo.001"]:
            obj = bpy.data.objects.get(obj_name)
            if obj is None:
                self.report({'WARNING'}, f"'{obj_name}' not found -- skipping subdivision modifier.")
                continue
            mod = obj.modifiers.new(name="Subdivision", type='SUBSURF')
            mod.levels = 1
            mod.render_levels = 1
            self.report({'INFO'}, f"Added Subdivision modifier to '{obj_name}'.")

        # 8. Copy material from Pareo to Pareo.001
        pareo = bpy.data.objects.get("Pareo")
        pareo_002 = bpy.data.objects.get("Pareo.001")
        if pareo is None:
            self.report({'WARNING'}, "'Pareo' not found -- cannot copy material.")
        elif pareo_002 is None:
            self.report({'WARNING'}, "'Pareo.001' not found -- cannot copy material.")
        else:
            if pareo.material_slots:
                mat = pareo.material_slots[0].material
                if not pareo_002.material_slots:
                    pareo_002.data.materials.append(mat)
                else:
                    pareo_002.material_slots[0].material = mat
                self.report({'INFO'}, f"Copied material '{mat.name}' to Pareo.001.")
            else:
                self.report({'WARNING'}, "'Pareo' has no materials to copy.")

        # 9. Export MasterOldMan.001 and its hierarchy as .blend
        master_001 = bpy.data.objects.get("MasterOldMan.001")
        if master_001 is None:
            self.report({'ERROR'}, "Object 'MasterOldMan.001' not found -- cannot export blend.")
            return {'CANCELLED'}

        def collect_hierarchy(o):
            result = [o]
            for child in o.children:
                result.extend(collect_hierarchy(child))
            return result

        blend_objects = collect_hierarchy(master_001)
        ok, msg = save_objects_as_blend(blend_path, blend_objects)
        self.report({'INFO' if ok else 'ERROR'}, f"Blend export: {msg}")
        if not ok:
            return {'CANCELLED'}

        self.report({'INFO'}, "Export Alembic complete!")
        return {'FINISHED'}


class TARENA_PT_Panel(bpy.types.Panel):
    bl_label = "BB Mocap Pipline"
    bl_idname = "Mocap_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Mocap'

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "tarena_number", text="Number")
        layout.separator()
        layout.label(text="Export")
        layout.operator("tarena.apply_animation", text="Apply Animation", icon='PLAY')
        layout.separator()
        layout.operator("tarena.fix_pelvis", text="Fix Pelvis", icon='BONE_DATA')
        layout.separator()
        layout.operator("tarena.export_alembic", text="Export Alembic", icon='EXPORT')
        layout.separator()
        layout.label(text="Import")
        layout.operator("tarena.import_assets", text="Import Assets", icon='IMPORT')


# ============================================================
# Import Operator
# ============================================================

class TARENA_OT_Import(bpy.types.Operator):
    """Append OldMan assets from the exported .blend and set transforms/modifiers."""
    bl_idname = "tarena.import_assets"
    bl_label = "Import Assets"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        num = context.scene.tarena_number.strip()
        if not num:
            self.report({'ERROR'}, "Please enter a number (e.g. 01, 02).")
            return {'CANCELLED'}

        base_path = r"I:\Tarena 2026\04_Resources\Export"
        blend_file = os.path.join(base_path, f"{num}.blend")

        if not os.path.isfile(blend_file):
            self.report({'ERROR'}, f".blend not found: {blend_file}")
            return {'CANCELLED'}

        # Ensure OldMan collection exists and set it active
        collection_name = "OldMan"
        if collection_name not in bpy.data.collections:
            self.report({'ERROR'}, f"Collection '{collection_name}' not found.")
            return {'CANCELLED'}

        collection = bpy.data.collections[collection_name]
        lc = context.view_layer.layer_collection.children.get(collection_name)
        if lc:
            context.view_layer.active_layer_collection = lc

        # Append all objects from the .blend
        with bpy.data.libraries.load(blend_file, link=False) as (data_from, data_to):
            data_to.objects = data_from.objects

        for obj in data_to.objects:
            if obj is not None:
                try:
                    collection.objects.link(obj)
                except RuntimeError:
                    pass

        self.report({'INFO'}, f"Appended {len([o for o in data_to.objects if o])} object(s) from {blend_file}")

        # Set location on MasterOldMan.001
        target = bpy.data.objects.get("MasterOldMan.001")
        if target:
            target.location = (1.97, -2.93, -0.058)
            self.report({'INFO'}, "Set location on MasterOldMan.001.")
        else:
            self.report({'WARNING'}, "MasterOldMan.001 not found -- skipping location.")

        # Set frame_offset on MeshSequenceCache modifier of OldManBody.002
        mesh_obj = None
        for obj in bpy.data.objects:
            if obj.name.startswith("OldManBody.002"):
                mesh_obj = obj
                break

        if mesh_obj is None:
            self.report({'WARNING'}, "OldManBody.002 not found -- skipping frame_offset.")
        else:
            found = False
            for mod in mesh_obj.modifiers:
                if mod.type == 'MESH_SEQUENCE_CACHE':
                    if mod.cache_file:
                        mod.cache_file.frame_offset = 1152
                        found = True
                        self.report({'INFO'}, "frame_offset set to 1152 on MeshSequenceCache.")
                    else:
                        self.report({'WARNING'}, "MeshSequenceCache has no cache file.")
            if not found:
                self.report({'WARNING'}, "No MeshSequenceCache modifier found on OldManBody.002.")

        self.report({'INFO'}, "Import complete!")
        return {'FINISHED'}



def register():
    bpy.types.Scene.tarena_number = bpy.props.StringProperty(
        name="Tarena Number",
        description="The file number to process, e.g. 01, 02, 10",
        default="01",
    )

    bpy.utils.register_class(TARENA_OT_ApplyAnimation)
    bpy.utils.register_class(TARENA_OT_FixPelvis)
    bpy.utils.register_class(TARENA_OT_ExportAlembic)
    bpy.utils.register_class(TARENA_OT_Import)
    bpy.utils.register_class(TARENA_PT_Panel)


def unregister():
    del bpy.types.Scene.tarena_number
    bpy.utils.unregister_class(TARENA_OT_ApplyAnimation)
    bpy.utils.unregister_class(TARENA_OT_FixPelvis)
    bpy.utils.unregister_class(TARENA_OT_ExportAlembic)
    bpy.utils.unregister_class(TARENA_OT_Import)
    bpy.utils.unregister_class(TARENA_PT_Panel)


if __name__ == "__main__":
    register()
