"""The settings in the sidebar panel, kept on the scene."""

import math

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty
from bpy.types import PropertyGroup


class COCOREDUCE_Settings(PropertyGroup):
    mode: EnumProperty(
        name="Mode",
        items=(
            ('HARD', "Hard Surface",
             "Panels, bevels and sharp edges: edges bent past the Sharp Angle are kept "
             "as lines, and fairly flat areas become n-gons"),
            ('ORGANIC', "Organic",
             "Curved surfaces: only UV seams, edges marked sharp, open borders and "
             "material borders are kept as lines, and no n-gons are made"),
        ),
        default='HARD',
    )
    percent: FloatProperty(
        name="Size",
        description="Triangles to keep, as a share of the selected mesh",
        subtype='PERCENTAGE',
        default=50.0,
        min=0.1,
        max=100.0,
        soft_min=1.0,
        precision=0,
    )
    part_size: FloatProperty(
        name="Small Parts",
        description="Loose parts up to this size, as a share of the whole mesh's size, may be removed "
                    "whole when the Size cannot be reached without breaking a shape. "
                    "The smallest go first, and copies of a part go together. 0 keeps every part",
        subtype='PERCENTAGE',
        default=2.0,
        min=0.0,
        max=20.0,
        precision=1,
    )
    min_sides: IntProperty(
        name="Min Sides",
        description="The fewest sides a round part (a tube, a wheel, a rounded edge) may keep. "
                    "Lower it to reduce further: at 6, a 12-sided tube can lose every other side",
        default=8,
        min=3,
        max=64,
    )
    sharp_angle: FloatProperty(
        name="Sharp Angle",
        description="Edges bent more than this are kept as lines, like seams",
        subtype='ANGLE',
        default=math.radians(30.0),
        min=0.0,
        max=math.pi,
    )
    flat_angle: FloatProperty(
        name="Flat Angle",
        description="Faces within this angle of each other are joined into one n-gon",
        subtype='ANGLE',
        default=math.radians(5.0),
        min=0.0,
        max=math.radians(45.0),
    )


def register():
    bpy.utils.register_class(COCOREDUCE_Settings)
    bpy.types.Scene.coco_reduce = PointerProperty(type=COCOREDUCE_Settings)


def unregister():
    del bpy.types.Scene.coco_reduce
    bpy.utils.unregister_class(COCOREDUCE_Settings)
