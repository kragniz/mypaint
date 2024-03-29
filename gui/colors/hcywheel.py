# This file is part of MyPaint.
# Copyright (C) 2012 by Andrew Chadwick <andrewc-git@piffle.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.


"""Hue/Relative chroma/Luma adjuster widgets, with an editable gamut mask.
"""

import math
from copy import deepcopy
from random import random
import re
import os.path

import gtk
from gtk import gdk
import cairo
from gettext import gettext as _

from bases import CachedBgDrawingArea
from adjbases import ColorAdjuster
from adjbases import ColorAdjusterWidget
from adjbases import HueSaturationWheelMixin
from adjbases import HueSaturationWheelAdjuster
from sliders import HCYLumaSlider
from combined import CombinedAdjusterPage
from uicolor import *
from util import *
from palette import Palette
import geom
from uimisc import borderless_button


PREFS_MASK_KEY = "colors.hcywheel.mask.gamuts"
PREFS_ACTIVE_KEY = "colors.hcywheel.mask.active"
MASK_EDITOR_HELP=_("""<b>Gamut mask editor</b>

Edit the gamut mask here, or turn it off or on. Gamut masks are like a piece of
tracing paper with cut-out holes, placed over the color wheel to limit the
range of colors you can select. This allows you to plan your color schemes in
advance, which is useful for color scripting or to create specific moods. The
theory is that the corners of each mask shape represent a <i>subjective</i>
primary color, and that each shape contains all the colors which can be mixed
using those corner primaries. Subjective secondary colors lie at the midpoints
of the shape edges, and the center of the shape is the subjective neutral tone
for the shape.

Click to add shapes if the wheel is blank. Shapes can be dragged around and
their outlines can be adjusted by adding or moving the control points. Make a
shape too small to be useful to remove it: dragging a shape to the edge of the
disc is a quick way of doing this. You can delete shapes by dragging them
inside other shapes too. The entire mask can be rotated by turning the edge of
the disc to generate new and unexpected color schemes.

Gamut masks can be saved to GIMP-format palette files, and loaded from them.
The New button lets you choose one of several templates as a starting point.
""")


class MaskableWheelMixin:
    """Provides wheel widgets with maskable areas.

    For use with implementations of `HueSaturationWheelAdjusterMixin`.
    Concrete implementations can be masked so that they ignore clicks outside
    certain colour areas. If the mask is active, clicks inside the mask
    shapes are treated as normal, but clicks outside them are remapped to a
    point on the nearest edge of the nearest shape. This can be useful for
    artists who wish to plan the colour gamut of their artwork in advance.

    http://gurneyjourney.blogspot.com/2011/09/part-1-gamut-masking-method.html
    http://gurneyjourney.blogspot.com/2008/01/color-wheel-masking-part-1.html

    """

    # Class-level variables: drawing constants etc.
    min_shape_size = 0.15 #: Smallest useful shape: fraction of radius

    # Instance variables (defaults / documentation)
    __mask = None
    mask_toggle = None #: gtk.ToggleAction controling whether the mask is used
    mask_observers = None #: List of no-argument mask change observer callbacks


    def __init__(self):
        """Instantiate instance vars and bind actions.
        """
        self.__mask = []
        self.mask_observers = []
        action_name = "wheel%s_masked" % (id(self),)
        self.mask_toggle = gtk.ToggleAction(action_name,
          _("Gamut mask active"),
          _("Limit your palette for specific moods using a gamut mask"),
          None)
        self.mask_toggle.connect("toggled", self.__mask_toggled_cb)


    def __mask_toggled_cb(self, action):
        active = action.get_active()
        prefs = self._get_prefs()
        prefs[PREFS_ACTIVE_KEY] = active
        self.queue_draw()


    def set_color_manager(self, manager):
        """Sets the color manager, and reads an initial mask from prefs.

        Extends `ColorAdjuster`'s implementation.

        """
        ColorAdjuster.set_color_manager(self, manager)
        prefs = self._get_prefs()
        mask_flat = prefs.get(PREFS_MASK_KEY, None)
        mask_active = prefs.get(PREFS_ACTIVE_KEY, False)
        if mask_flat is not None:
            self.set_mask(self._unflatten_mask(mask_flat))
            self.mask_toggle.set_active(mask_active)

    @staticmethod
    def _flatten_mask(mask):
        flat_mask = []
        for shape_colors in mask:
            shape_flat = [c.to_hex_str() for c in shape_colors]
            flat_mask.append(shape_flat)
        return flat_mask

    @staticmethod
    def _unflatten_mask(flat_mask):
        mask = []
        for shape_flat in flat_mask:
            shape_colors = [RGBColor.new_from_hex_str(s) for s in shape_flat]
            mask.append(shape_colors)
        return mask


    def set_mask_from_palette(self, pal):
        """Sets the mask from a palette.

        Any `palette.Palette` can be loaded into the wheel widget, and colour
        names are used for distinguishing mask shapes. If a colour name
        matches the pattern "``mask #<decimal-int>``", it will be associated
        with the shape having the ID ``<decimal-int>``.

        """
        if pal is None:
            return
        mask_id_re = re.compile(r'\bmask\s*#?\s*(\d+)\b')
        mask_shapes = {}
        for i in xrange(len(pal)):
            color = pal.get_color(i)
            if color is None:
                continue
            shape_id = 0
            color_name = pal.get_color_name(i)
            if color_name is not None:
                mask_id_match = mask_id_re.search(color_name)
                if mask_id_match:
                    shape_id = int(mask_id_match.group(1))
            if shape_id not in mask_shapes:
                mask_shapes[shape_id] = []
            mask_shapes[shape_id].append(color)
        mask_list = []
        shape_ids = mask_shapes.keys()
        shape_ids.sort()
        for shape_id in shape_ids:
            mask_list.append(mask_shapes[shape_id])
        self.set_mask(mask_list)


    def set_mask(self, mask):
        """Sets the mask (a list of lists of `UIColor`s).
        """
        mgr = self.get_color_manager()
        prefs = self._get_prefs()
        if mask is None:
            self.__mask = None
            self.mask_toggle.set_active(False)
            prefs[PREFS_MASK_KEY] = None
        else:
            self.mask_toggle.set_active(True)
            self.__mask = mask
            prefs[PREFS_MASK_KEY] = self._flatten_mask(mask)
        for func in self.mask_observers:
            func()
        self.queue_draw()


    def get_mask(self):
        """Returns the current mask.
        """
        return self.__mask


    def get_mask_voids(self):
        """Returns the current mask as a list of lists of (x, y) pairs.
        """
        voids = []
        if not self.__mask:
            return voids
        for shape in self.__mask:
            if len(shape) >= 3:
                void = self.colors_to_mask_void(shape)
                voids.append(void)
        return voids


    def colors_to_mask_void(self, colors):
        """Converts a set of colours to a mask void (convex hull).

        Mask voids are the convex hulls of the (x, y) positions for the
        colours making up the mask, so mask shapes with fewer than 3 colours
        are returned as the empty list.

        """
        points = []
        if len(colors) < 3:
            return points
        for col in colors:
            points.append(self.get_pos_for_color(col))
        return geom.convex_hull(points)


    def get_color_at_position(self, x, y, ignore_mask=False):
        """Converts an `x`, `y` position to a colour.

        Ordinarily, this implmentation uses any active mask to limit the
        colours which can be clicked on. Set `ignore_mask` to disable this
        added behaviour.

        """
        sup = HueSaturationWheelMixin
        if ignore_mask or not self.mask_toggle.get_active():
            return sup.get_color_at_position(self, x, y)
        voids = self.get_mask_voids()
        if not voids:
            return sup.get_color_at_position(self, x, y)
        isects = []
        for vi, void in enumerate(voids):
            # If we're inside a void, use the unchanged value
            if geom.point_in_convex_poly((x, y), void):
                return sup.get_color_at_position(self, x, y)
            # If outside, find the nearest point on the nearest void's edge
            for p1, p2 in geom.pairwise(void):
                isect = geom.nearest_point_in_segment(p1,p2, (x,y))
                if isect is not None:
                    d = math.sqrt((isect[0]-x)**2 + (isect[1]-y)**2)
                    isects.append((d, isect))
                # Above doesn't include segment ends, so add those
                d = math.sqrt((p1[0]-x)**2 + (p1[1]-y)**2)
                isects.append((d, p1))
        # Determine the closest point.
        if isects:
            isects.sort()
            x, y = isects[0][1]
        return sup.get_color_at_position(self, x, y)


    @staticmethod
    def _get_void_size(void):
        """Size metric for a mask void (list of x,y points; convex hull)
        """
        area = geom.poly_area(void)
        return math.sqrt(area)


    def _get_mask_fg(self):
        """Returns the mask edge drawing colour as an rgb triple.
        """
        state = self.get_state()
        style = self.get_style()
        c = style.fg[state]
        return RGBColor.new_from_gdk_color(c).get_rgb()


    def _get_mask_bg(self):
        """Returns the mask area drawing colour as an rgb triple.
        """
        state = self.get_state()
        style = self.get_style()
        c = style.bg[state]
        return RGBColor.new_from_gdk_color(c).get_rgb()


    def draw_mask(self, cr, wd, ht):
        """Draws the mask, if enabled and if it has any usable voids.

        For the sake of the editor subclass, this doesn't draw any voids
        which are smaller than `self.min_shape_size` times the wheel radius.

        """

        if not self.mask_toggle.get_active():
            return
        if self.__mask is None or self.__mask == []:
            return

        cr.save()

        radius = self.get_radius(wd=wd, ht=ht)
        cx, cy = self.get_center(wd=wd, ht=ht)
        cr.arc(cx, cy, radius+self.border, 0, 2*math.pi)
        cr.clip()

        bg_rgb = self._get_mask_bg()
        fg_rgb = self._get_mask_fg()

        cr.push_group()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgb(*bg_rgb)
        cr.rectangle(0, 0, wd, ht)
        cr.fill()
        voids = []
        min_size = radius * self.min_shape_size
        for void in self.get_mask_voids():
            if len(void) < 3:
                continue
            size = self._get_void_size(void)
            if size >= min_size:
                voids.append(void)
        cr.set_source_rgb(*fg_rgb)
        for void in voids:
            cr.new_sub_path()
            cr.move_to(*void[0])
            for x, y in void[1:]:
                cr.line_to(x, y)
            cr.close_path()
        cr.set_line_width(2.0)
        cr.stroke_preserve()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(1,1,1,0)
        cr.fill()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.pop_group_to_source()

        cr.paint_with_alpha(0.666)
        cr.restore()


    def paint_foreground_cb(self, cr, wd, ht):
        """Paints the foreground items: mask, then marker.
        """
        self.draw_mask(cr, wd, ht)
        HueSaturationWheelMixin.paint_foreground_cb(self, cr, wd, ht)


class HCYHueChromaWheelMixin:
    """Mixin for wheel-style adjusters to display the H+C from the HCY model.

    For use with implementations of `HueSaturationWheelAdjusterMixin`; make
    sure this mixin comes before it in the MRO.

    """

    def get_normalized_polar_pos_for_color(self, col):
        col = HCYColor(color=col)
        return col.c, col.h

    def color_at_normalized_polar_pos(self, r, theta):
        col = HCYColor(color=self.get_managed_color())
        col.h = theta
        col.c = r
        return col


class HCYHueChromaWheel (MaskableWheelMixin,
                         HCYHueChromaWheelMixin,
                         HueSaturationWheelAdjuster):
    """Circular mapping of the H and C terms of the HCY model.
    """

    tooltip_text = _("HCY Hue and Chroma")

    def __init__(self):
        """Instantiate, binding events.
        """
        MaskableWheelMixin.__init__(self)
        HueSaturationWheelAdjuster.__init__(self)
        self.connect("scroll-event", self.__scroll_cb)
        self.add_events(gdk.SCROLL_MASK)


    def __scroll_cb(self, widget, event):
        # Scrolling controls luma.
        d = self.scroll_delta
        if event.direction in (gdk.SCROLL_DOWN, gdk.SCROLL_LEFT):
            d *= -1
        col = HCYColor(color=self.get_managed_color())
        y = clamp(col.y+d, 0.0, 1.0)
        if col.y != y:
            col.y = y
            self.set_managed_color(col)
        return True



class HCYMaskEditorWheel (HCYHueChromaWheel):
    """HCY wheel specialized for mask editing.
    """

    ## Instance vars
    is_editable = False
    __last_cursor = None   # previously set cursor (determines some actions)
    # Objects which are active or being manipulated
    __tmp_new_ctrlpoint = None   # new control-point colour
    __active_ctrlpoint = None   # active point in active_void
    __active_shape = None  # list of colours or None
    # Drag state
    __drag_func = None
    __drag_start_pos = None

    ## Class-level constants and variables
    # Specialized cursors for different actions
    __add_cursor = gdk.Cursor(gdk.PLUS)
    __move_cursor = gdk.Cursor(gdk.FLEUR)
    __move_point_cursor = gdk.Cursor(gdk.CROSSHAIR)
    __rotate_cursor = gdk.Cursor(gdk.EXCHANGE)

    # Drawing constraints and activity proximities
    __ctrlpoint_radius = 2.5
    __ctrlpoint_grab_radius = 10
    __max_num_shapes = 6   # how many shapes are allowed
    tooltip_text = _("Gamut mask editor. Click in the middle to create "
                     "or manipulate shapes, or rotate the mask using "
                     "the edges of the disc.")


    def __init__(self):
        """Instantiate, and connect the editor events.
        """
        HCYHueChromaWheel.__init__(self)
        self.connect("button-press-event", self.__button_press_cb)
        self.connect("button-release-event", self.__button_release_cb)
        self.connect("motion-notify-event", self.__motion_cb)
        self.connect("leave-notify-event", self.__leave_cb)
        self.add_events(gdk.POINTER_MOTION_MASK|gdk.LEAVE_NOTIFY_MASK)


    def __leave_cb(self, widget, event):
        # Reset the active objects when the pointer leaves.
        if self.__drag_func is not None:
            return
        self.__active_shape = None
        self.__active_ctrlpoint = None
        self.__tmp_new_ctrlpoint = None
        self.queue_draw()
        self.__set_cursor(None)


    def __set_cursor(self, cursor):
        # Sets the window cursor, retaining a record.
        if cursor != self.__last_cursor:
            self.get_window().set_cursor(cursor)
            self.__last_cursor = cursor


    def __update_active_objects(self, x, y):
        # Decides what a click or a drag at (x, y) would do, and updates the
        # mouse cursor and draw state to match.

        assert self.__drag_func is None
        self.__active_shape = None
        self.__active_ctrlpoint = None
        self.__tmp_new_ctrlpoint = None
        self.queue_draw()  # yes, always

        # Possible mask void manipulations
        mask = self.get_mask()
        for mask_idx in xrange(len(mask)):
            colors = mask[mask_idx]
            if len(colors) < 3:
                continue

            # If the pointer is near an existing control point, clicking and
            # dragging will move it.
            void = []
            for col_idx in xrange(len(colors)):
                col = colors[col_idx]
                px, py = self.get_pos_for_color(col)
                dp = math.sqrt((x-px)**2 + (y-py)**2)
                if dp <= self.__ctrlpoint_grab_radius:
                    mask.remove(colors)
                    mask.insert(0, colors)
                    self.__active_shape = colors
                    self.__active_ctrlpoint = col_idx
                    self.__set_cursor(None)
                    return
                void.append((px, py))

            # If within a certain distance of an edge, dragging will create and
            # then move a new control point.
            void = geom.convex_hull(void)
            for p1, p2 in geom.pairwise(void):
                isect = geom.nearest_point_in_segment(p1, p2, (x, y))
                if isect is not None:
                    ix, iy = isect
                    di = math.sqrt((ix-x)**2 + (iy-y)**2)
                    if di <= self.__ctrlpoint_grab_radius:
                        newcol = self.get_color_at_position(ix, iy)
                        self.__tmp_new_ctrlpoint = newcol
                        mask.remove(colors)
                        mask.insert(0, colors)
                        self.__active_shape = colors
                        self.__set_cursor(None)
                        return

            # If the mouse is within a mask void, then dragging would move that
            # shape around within the mask.
            if geom.point_in_convex_poly((x, y), void):
                mask.remove(colors)
                mask.insert(0, colors)
                self.__active_shape = colors
                self.__set_cursor(None)
                return

        # Away from shapes, clicks and drags manipulate the entire mask: adding
        # cutout voids to it, or rotating the whole mask around its central
        # axis.
        alloc = self.get_allocation()
        cx, cy = self.get_center(alloc=alloc)
        radius = self.get_radius(alloc=alloc)
        dx, dy = x-cx, y-cy
        r = math.sqrt(dx**2 + dy**2)
        if r < radius*(1.0-self.min_shape_size):
            if len(mask) < self.__max_num_shapes:
                d = self.__dist_to_nearest_shape(x, y)
                minsize = radius * self.min_shape_size
                if d is None or d > minsize:
                    # Clicking will result in a new void
                    self.__set_cursor(self.__add_cursor)
        else:
            # Click-drag to rotate the entire mask
            self.__set_cursor(self.__rotate_cursor)


    def __drag_active_shape(self, px, py):
        # Updates the position of the active shape during drags.
        sup = HCYHueChromaWheel
        x0, y0 = self.__drag_start_pos
        dx = px - x0
        dy = py - y0
        self.__active_shape[:] = []
        for col in self.__active_shape_predrag:
            cx, cy = self.get_pos_for_color(col)
            cx += dx
            cy += dy
            col2 = sup.get_color_at_position(self, cx, cy, ignore_mask=True)
            self.__active_shape.append(col2)


    def __drag_active_ctrlpoint(self, px, py):
        # Moves the highlighted control point during drags.
        sup = HCYHueChromaWheel
        x0, y0 = self.__drag_start_pos
        dx = px - x0
        dy = py - y0
        col = self.__active_ctrlpoint_predrag
        cx, cy = self.get_pos_for_color(col)
        cx += dx
        cy += dy
        col = sup.get_color_at_position(self, cx, cy, ignore_mask=True)
        self.__active_shape[self.__active_ctrlpoint] = col


    def __rotate_mask(self, px, py):
        # Rotates the entire mask around the grey axis during drags.
        cx, cy = self.get_center()
        x0, y0 = self.__drag_start_pos
        theta0 = math.atan2(x0-cx, y0-cy)
        theta = math.atan2(px-cx, py-cy)
        dntheta = (theta0 - theta) / (2*math.pi)
        while dntheta <= 0:
            dntheta += 1.0
        if self.__mask_predrag is None:
            self.__mask_predrag = []
            for shape in self.get_mask():
                shape_hcy = [HCYColor(color=c) for c in shape]
                self.__mask_predrag.append(shape_hcy)
        newmask = []
        for shape in self.__mask_predrag:
            shape_rot = []
            for col in shape:
                col_r = HCYColor(color=col)
                col_r.h += dntheta
                col_r.h %= 1.0
                shape_rot.append(col_r)
            newmask.append(shape_rot)
        self.set_mask(newmask)


    def __button_press_cb(self, widget, event):
        # Begins drags.
        if self.__drag_func is None:
            self.__update_active_objects(event.x, event.y)
            self.__drag_start_pos = event.x, event.y
            if self.__tmp_new_ctrlpoint is not None:
                self.__active_ctrlpoint = len(self.__active_shape)
                self.__active_shape.append(self.__tmp_new_ctrlpoint)
                self.__tmp_new_ctrlpoint = None
            if self.__active_ctrlpoint is not None:
                self.__active_shape_predrag = self.__active_shape[:]
                ctrlpt = self.__active_shape[self.__active_ctrlpoint]
                self.__active_ctrlpoint_predrag = ctrlpt
                self.__drag_func = self.__drag_active_ctrlpoint
                self.__set_cursor(self.__move_point_cursor)
            elif self.__active_shape is not None:
                self.__active_shape_predrag = self.__active_shape[:]
                self.__drag_func = self.__drag_active_shape
                self.__set_cursor(self.__move_cursor)
            elif self.__last_cursor is self.__rotate_cursor:
                self.__mask_predrag = None
                self.__drag_func = self.__rotate_mask


    def __button_release_cb(self, widget, event):
        # Ends the current drag & cleans up, or handle other clicks.
        if self.__drag_func is None:
            # Clicking when not in a drag adds a new shape
            if self.__last_cursor is self.__add_cursor:
                self.__add_void(event.x, event.y)
        else:
            # Cleanup when dragging ends
            self.__drag_func = None
            self.__drag_start_pos = None
            self.__cleanup_mask()
        self.__update_active_objects(event.x, event.y)


    def __motion_cb(self, widget, event):
        # Fire the current drag function if one's active.
        if self.__drag_func is not None:
            self.__drag_func(event.x, event.y)
            self.queue_draw()
        else:
            self.__update_active_objects(event.x, event.y)


    def __cleanup_mask(self):
        mask = self.get_mask()

        # Drop points from all shapes which are not part of the convex hulls.
        for shape in mask:
            if len(shape) <= 3:
                continue
            points = [self.get_pos_for_color(c) for c in shape]
            edge_points = geom.convex_hull(points)
            for col, point in zip(shape, points):
                if point in edge_points:
                    continue
                shape.remove(col)

        # Drop shapes smaller than the minimum size.
        newmask = []
        min_size = self.get_radius() * self.min_shape_size
        for shape in mask:
            points = [self.get_pos_for_color(c) for c in shape]
            void = geom.convex_hull(points)
            size = self._get_void_size(void)
            if size >= min_size:
                newmask.append(shape)
        mask = newmask

        # Drop shapes whose points entirely lie within other shapes
        newmask = []
        maskvoids = [(shape, geom.convex_hull([self.get_pos_for_color(c)
                                               for c in shape]))
                     for shape in mask]
        for shape1, void1 in maskvoids:
            shape1_subsumed = True
            for p1 in void1:
                p1_subsumed = False
                for shape2, void2 in maskvoids:
                    if shape1 is shape2:
                        continue
                    if geom.point_in_convex_poly(p1, void2):
                        p1_subsumed = True
                        break
                if not p1_subsumed:
                    shape1_subsumed = False
                    break
            if not shape1_subsumed:
                newmask.append(shape1)
        mask = newmask

        self.set_mask(mask)
        self.queue_draw()


    def __dist_to_nearest_shape(self, x, y):
        # Distance from `x`, `y` to the nearest edge or vertex of any shape.
        dists = []
        for hull in self.get_mask_voids():
            # cx, cy = geom.poly_centroid(hull)
            for p1, p2 in geom.pairwise(hull):
                np = geom.nearest_point_in_segment(p1,p2, (x,y))
                if np is not None:
                    nx, ny = np
                    d = math.sqrt((x-nx)**2 + (y-ny)**2)
                    dists.append(d)
            # Segment end too
            d = math.sqrt((p1[0]-x)**2 + (p1[1]-y)**2)
            dists.append(d)
        if not dists:
            return None
        dists.sort()
        return dists[0]


    def __add_void(self, x, y):
        # Adds a new shape into the empty space centred at `x`, `y`.
        self.queue_draw()
        # Pick a nice size for the new shape, taking care not to
        # overlap any other shapes, at least initially.
        alloc = self.get_allocation()
        cx, cy = self.get_center(alloc=alloc)
        radius = self.get_radius(alloc=alloc)
        dx, dy = x-cx, y-cy
        r = math.sqrt(dx**2 + dy**2)
        d = self.__dist_to_nearest_shape(x, y)
        if d is None:
            d = radius
        size = min((radius - r), d) * 0.95
        minsize = radius * self.min_shape_size
        if size < minsize:
            return
        # Create a regular polygon with one of its edges facing the
        # middle of the wheel.
        shape = []
        nsides = 3 + len(self.get_mask())
        psi = math.atan2(dy, dx) + (math.pi/nsides)
        psi += math.pi
        for i in xrange(nsides):
            theta = 2.0 * math.pi * float(i)/nsides
            theta += psi
            px = int(x + size*math.cos(theta))
            py = int(y + size*math.sin(theta))
            col = self.get_color_at_position(px, py, ignore_mask=True)
            shape.append(col)
        mask = self.get_mask()
        mask.append(shape)
        self.set_mask(mask)


    def draw_mask_control_points(self, cr, wd, ht):
        # Draw active and inactive control points on the active shape.

        if self.__active_shape is None:
            return

        cr.save()
        active_rgb = 1, 1, 1
        normal_rgb = 0, 0, 0
        delete_rgb = 1, 0, 0
        cr.set_line_width(1.0)
        void = self.colors_to_mask_void(self.__active_shape)

        # Highlight the objects that would be directly or indirectly affected
        # if the shape were dragged, and how.
        min_size = self.get_radius(wd=wd, ht=ht) * self.min_shape_size
        void_rgb = normal_rgb
        if self._get_void_size(void) < min_size:
            # Shape will be deleted
            void_rgb = delete_rgb
        elif (  (self.__active_ctrlpoint is None) \
          and (self.__tmp_new_ctrlpoint is None) ):
            # The entire shape would be moved
            void_rgb = active_rgb
        # Outline the current shape
        cr.set_source_rgb(*void_rgb)
        for p_idx, p in enumerate(void):
            if p_idx == 0:
                cr.move_to(*p)
            else:
                cr.line_to(*p)
        cr.close_path()
        cr.stroke()

        # Control points
        colors = self.__active_shape
        for col_idx, col in enumerate(colors):
            px, py = self.get_pos_for_color(col)
            if (px, py) not in void:
                # not in convex hull (is it worth doing this fragile test?)
                continue
            point_rgb = void_rgb
            if col_idx == self.__active_ctrlpoint:
                point_rgb = active_rgb
            cr.set_source_rgb(*point_rgb)
            cr.arc(px, py, self.__ctrlpoint_radius, 0, 2*math.pi)
            cr.fill()
        if self.__tmp_new_ctrlpoint:
            px, py = self.get_pos_for_color(self.__tmp_new_ctrlpoint)
            cr.set_source_rgb(*active_rgb)
            cr.arc(px, py, self.__ctrlpoint_radius, 0, 2*math.pi)
            cr.fill()

        # Centroid
        cr.set_source_rgb(*void_rgb)
        cx, cy = geom.poly_centroid(void)
        cr.save()
        cr.set_line_cap(cairo.LINE_CAP_SQUARE)
        cr.set_line_width(0.5)
        cr.translate(int(cx)+0.5, int(cy)+0.5)
        cr.move_to(-2, 0)
        cr.line_to(2, 0)
        cr.stroke()
        cr.move_to(0, -2)
        cr.line_to(0, 2)
        cr.stroke()

        cr.restore()


    def paint_foreground_cb(self, cr, wd, ht):
        """Foreground drawing override.
        """
        self.draw_mask(cr, wd, ht)
        self.draw_mask_control_points(cr, wd, ht)



class HCYMaskPreview (MaskableWheelMixin,
                      HCYHueChromaWheelMixin,
                      HueSaturationWheelAdjuster):
    """Mask preview widget; not scrollable.

    These widgets can be used with `palette.Palette.load_via_dialog()` as
    preview widgets during mask selection.

    """

    def __init__(self, mask=None):
        MaskableWheelMixin.__init__(self)
        HueSaturationWheelAdjuster.__init__(self)
        self.set_app_paintable(True)
        self.set_has_window(False)
        self.set_mask(mask)
        self.mask_toggle.set_active(True)
        self.set_size_request(64, 64)

    def render_background_cb(self, cr, wd, ht):
        sup = HueSaturationWheelAdjuster
        sup.render_background_cb(self, cr, wd=wd, ht=ht)
        self.draw_mask(cr, wd=wd, ht=ht)

    def paint_foreground_cb(self, cr, wd, ht):
        pass

    def get_background_validity(self):
        return deepcopy(self.get_mask())

    def get_managed_color(self):
        return HCYColor(0, 0, 0.5)

    def set_palette(self, palette):
        # Compatibility with Palette.load_via_dialog()
        self.set_mask_from_palette(palette)


class HCYMaskTemplateDialog (gtk.Dialog):
    """Dialog for choosing a mask from a small set of templates.

    http://gurneyjourney.blogspot.co.uk/2008/02/shapes-of-color-schemes.html

    """

    @property
    def __templates(self):
        Y = 0.5
        H = 1-0.05
        # Reusable shapes...
        atmos_triad = [HCYColor( H, 0.95, Y),
                       HCYColor((  H+0.275)%1, 0.55, Y),
                       HCYColor((1+H-0.275)%1, 0.55, Y)]
        def __coffin(h):
            # Hexagonal coffin shape with the foot end at the centre
            # of the wheel.
            shape = []
            shape.append(HCYColor((h     + 0.25)%1, 0.03, Y))
            shape.append(HCYColor((h + 1 - 0.25)%1, 0.03, Y))
            shape.append(HCYColor((h     + 0.01)%1, 0.95, Y))
            shape.append(HCYColor((h + 1 - 0.01)%1, 0.95, Y))
            shape.append(HCYColor((h     + 0.04)%1, 0.70, Y))
            shape.append(HCYColor((h + 1 - 0.04)%1, 0.70, Y))
            return shape
        def __complement_blob(h):
            # Small pentagonal blob at the given hue, used for an organic-
            # looking dab of a complementary hue.
            shape = []
            shape.append(HCYColor((h+0.015)%1, 0.94, Y))
            shape.append(HCYColor((h+0.985)%1, 0.94, Y))
            shape.append(HCYColor((h+0.035)%1, 0.71, Y))
            shape.append(HCYColor((h+0.965)%1, 0.71, Y))
            shape.append(HCYColor((h      )%1, 0.54, Y))
            return shape
        templates = []
        templates.append((_("Atmospheric Triad"),
          _("Moody and subjective, defined by one dominant primary and two "
            "primaries which are less intense."),
          [ deepcopy(atmos_triad) ]))
        templates.append((_("Shifted Triad"),
          _("Weighted more strongly towards the dominant colour."),
          [[HCYColor( H, 0.95, Y),
            HCYColor((  H+0.35)%1, 0.4, Y),
            HCYColor((1+H-0.35)%1, 0.4, Y) ]] ))
        templates.append((_("Complementary"),
          _("Contrasting opposites, balanced by having central neutrals "
            "between them on the colour wheel."),
          [[HCYColor((H+0.005)%1,  0.9, Y),
            HCYColor((H+0.995)%1,  0.9, Y),
            HCYColor((H+0.25 )%1,  0.1, Y),
            HCYColor((H+0.75 )%1,  0.1, Y),
            HCYColor((H+0.505)%1,  0.9, Y),
            HCYColor((H+0.495)%1,  0.9, Y),
            ]] ))
        templates.append((_("Mood and Accent"),
          _("One main range of colors, with a complementary accent for "
            "variation and highlights."),
          [ deepcopy(atmos_triad),
            __complement_blob(H+0.5) ] ))
            #[HCYColor((H+0.483)%1, 0.95, Y),
            # HCYColor((H+0.517)%1, 0.95, Y),
            # HCYColor((H+0.52)%1, 0.725, Y),
            # HCYColor((H+0.48)%1, 0.725, Y) ]] ))
        templates.append((_("Split Complementary"),
          _("Two analogous colours and a complement to them, with no "
            "secondary colours between them."),
          [ __coffin(H+0.5), __coffin(1+H-0.1), __coffin(H+0.1) ] ))
        return templates


    def __init__(self, parent, target):
        gtk.Dialog.__init__(self, _("New gamut mask from template"), parent,
                            gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                            (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT))
        self.set_position(gtk.WIN_POS_MOUSE)
        self.target = target
        #self.vbox.set_spacing(6)
        size = 64
        for name, desc, mask in self.__templates:
            mask = deepcopy(mask)
            label = gtk.Label()
            label.set_markup("<b>%s</b>\n\n%s" % (name, desc))
            label.set_size_request(375, -1)
            label.set_line_wrap(True)
            label.set_alignment(0, 0.5)
            preview = HCYMaskPreview(deepcopy(mask))
            preview_frame = gtk.AspectFrame(obey_child=True)
            preview_frame.add(preview)
            preview_frame.set_shadow_type(gtk.SHADOW_NONE)
            hbox = gtk.HBox()
            hbox.set_spacing(6)
            hbox.pack_start(preview_frame, False, False)
            hbox.pack_start(label, True, True)
            button = gtk.Button()
            button.add(hbox)
            button.set_relief(gtk.RELIEF_NONE)
            button.connect("clicked", self.__button_clicked_cb, mask)
            self.vbox.pack_start(button, True, True)
        self.connect("response", self.__response_cb)
        self.connect("show", self.__show_cb)
        for w in self.vbox:
            w.show_all()


    def __button_clicked_cb(self, widget, mask):
        self.target.set_mask(mask)
        self.hide()


    def __show_cb(self, widget, *a):
        self.vbox.show_all()


    def __response_cb(self, widget, response_id):
        self.hide()
        return True


class HCYMaskPropertiesDialog (gtk.Dialog):
    """Dialog for choosing, editing, or enabling/disabling masks.
    """

    def __init__(self, parent, target):
        gtk.Dialog.__init__(self, _("Gamut mask editor"), parent,
                            gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                            (gtk.STOCK_HELP, gtk.RESPONSE_HELP,
                             gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                             gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        self.set_position(gtk.WIN_POS_MOUSE)
        self.target = target
        ed = HCYMaskEditorWheel()
        self.editor = ed
        ed.set_size_request(300, 300)
        ed.mask_toggle.set_active(True)
        self.mask_toggle_ctrl = gtk.CheckButton(_("Active"), use_underline=False)
        self.mask_toggle_ctrl.set_tooltip_text(ed.mask_toggle.get_tooltip())
        ed.mask_observers.append(self.__mask_changed_cb)

        hbox = gtk.HBox()
        hbox.set_spacing(3)

        # Sidebar buttonbox
        # On the right and packed to the top. This places its secondary
        # control, a mask toggle button, next to the "OK" button so it's less
        # likely to be missed.
        bbox = gtk.VButtonBox()
        new_btn = self.__new_button = gtk.Button(stock=gtk.STOCK_NEW)
        load_btn = self.__load_button = gtk.Button(stock=gtk.STOCK_OPEN)
        save_btn = self.__save_button = gtk.Button(stock=gtk.STOCK_SAVE)
        clear_btn = self.__clear_button = gtk.Button(stock=gtk.STOCK_CLEAR)

        new_btn.set_tooltip_text(_("Create mask from template"))
        load_btn.set_tooltip_text(_("Load mask from a GIMP palette file"))
        save_btn.set_tooltip_text(_("Save mask to a GIMP palette file"))
        clear_btn.set_tooltip_text(_("Erase the mask"))

        new_btn.connect("clicked", self.__new_clicked)
        save_btn.connect("clicked", self.__save_clicked)
        load_btn.connect("clicked", self.__load_clicked)
        clear_btn.connect("clicked", self.__clear_clicked)

        bbox.pack_start(new_btn)
        bbox.pack_start(load_btn)
        bbox.pack_start(save_btn)
        bbox.pack_start(clear_btn)
        bbox.pack_start(self.mask_toggle_ctrl)
        bbox.set_child_secondary(self.mask_toggle_ctrl, True)
        bbox.set_layout(gtk.BUTTONBOX_START)

        hbox.pack_start(ed, True, True)
        hbox.pack_start(bbox, False, False)
        hbox.set_border_width(9)

        self.vbox.pack_start(hbox, True, True)

        self.connect("response", self.__response_cb)
        self.connect("show", self.__show_cb)
        for w in self.vbox:
            w.show_all()


    def __mask_changed_cb(self):
        mask = self.editor.get_mask()
        empty = mask == []
        self.__save_button.set_sensitive(not empty)
        self.__clear_button.set_sensitive(not empty)

    def __new_clicked(self, widget):
        mask = self.editor.get_mask()
        dialog = HCYMaskTemplateDialog(self, self.editor)
        dialog.run()


    def __save_clicked(self, button):
        pal = Palette()
        mask = self.editor.get_mask()
        for i, shape in enumerate(mask):
            for j, col in enumerate(shape):
                col_name = "mask#%d primary#%d" % (i, j)  #NOT localised
                pal.append(col, col_name)
        preview = HCYMaskPreview()
        pal.save_via_dialog(
          title=_("Save mask as a Gimp palette"),
          parent=self,
          preview=preview)


    def __load_clicked(self, button):
        preview = HCYMaskPreview()
        preview.set_size_request(128, 128)
        pal = Palette.load_via_dialog(
          title=_("Load mask from a Gimp palette"),
          parent=self,
          preview=preview)
        if pal is None:
            return
        self.editor.set_mask_from_palette(pal)


    def __clear_clicked(self, widget):
        self.editor.set_mask([])


    def __show_cb(self, widget, *a):
        # When the dialog is shown, clone the target adjuster's mask for
        # editing. Assume the user wants to turn on the mask if there
        # is no mask on the target already (reduce the number of mouse clicks)
        active = True
        if self.target.get_mask():
            active = self.target.mask_toggle.get_active()
        self.mask_toggle_ctrl.set_active(active)
        mask = deepcopy(self.target.get_mask())
        self.editor.set_mask(mask)
        self.vbox.show_all()


    def __response_cb(self, widget, response_id):
        if response_id == gtk.RESPONSE_ACCEPT:
            self.target.set_mask(self.editor.get_mask())
            mask_active = self.mask_toggle_ctrl.get_active()
            self.target.mask_toggle.set_active(mask_active)
        if response_id == gtk.RESPONSE_HELP:
            # Sub-sub-sub dialog. Ugh. Still, we have a lot to say.
            dialog = gtk.MessageDialog(
              parent=self,
              flags=gtk.DIALOG_MODAL|gtk.DIALOG_DESTROY_WITH_PARENT,
              buttons=gtk.BUTTONS_CLOSE,  )
            markup_paras = re.split(r'\n[\040\t]*\n', MASK_EDITOR_HELP)
            markup = "\n\n".join([s.replace("\n", " ") for s in markup_paras])
            dialog.set_markup(markup)
            dialog.set_title(_("Gamut mask editor help"))
            dialog.connect("response", lambda *a: dialog.destroy())
            dialog.run()
        else:
            self.hide()
        return True


class HCYAdjusterPage (CombinedAdjusterPage):
    """Combined HCY adjuster.
    """

    __mask_dialog = None
    __hc_adj = None
    __y_adj = None
    __table = None

    def __init__(self):
        y_adj = HCYLumaSlider()
        y_adj.vertical = True
        hc_adj = HCYHueChromaWheel()

        table = gtk.Table(rows=2, columns=2)
        xopts = gtk.FILL|gtk.EXPAND
        yopts = gtk.FILL|gtk.EXPAND
        table.attach(y_adj, 0,1,  0,1,  gtk.FILL, yopts,  3, 3)
        table.attach(hc_adj, 1,2,  0,2,  xopts, yopts,  3, 3)

        self.__y_adj = y_adj
        self.__hc_adj = hc_adj
        self.__table = table

    @classmethod
    def get_properties_description(class_):
        return _("Set gamut mask")

    def show_properties(self):
        if self.__mask_dialog is None:
            toplevel = self.__hc_adj.get_toplevel()
            dia = HCYMaskPropertiesDialog(toplevel, self.__hc_adj)
            self.__mask_dialog = dia
        self.__mask_dialog.run()

    @classmethod
    def get_page_icon_name(class_):
        return 'mypaint-tool-hcywheel'

    @classmethod
    def get_page_title(class_):
        return _('HCY Wheel')

    @classmethod
    def get_page_description(class_):
        return _("Set the color using cylindrical hue/chroma/luma space. "
                 "The circular slices are equiluminant.")

    def get_page_widget(self):
        frame = gtk.AspectFrame(obey_child=True)
        frame.set_shadow_type(gtk.SHADOW_NONE)
        frame.add(self.__table)
        return frame

    def set_color_manager(self, manager):
        ColorAdjuster.set_color_manager(self, manager)
        self.__y_adj.set_property("color-manager", manager)
        self.__hc_adj.set_property("color-manager", manager)


if __name__ == '__main__':
    import os, sys
    from adjbases import ColorManager
    mgr = ColorManager()
    mgr.set_color(HSVColor(0.0, 0.0, 0.55))
    if len(sys.argv) > 1:
        # Generate icons
        wheel = HCYHueChromaWheel()
        wheel.set_color_manager(mgr)
        icon_name = HCYAdjusterPage.get_page_icon_name()
        for dir_name in sys.argv[1:]:
            wheel.save_icon_tree(dir_name, icon_name)
    else:
        # Interactive test
        page = HCYAdjusterPage()
        page.set_color_manager(mgr)
        window = gtk.Window()
        window.add(page.get_page_widget())
        window.set_title(os.path.basename(sys.argv[0]))
        window.set_border_width(6)
        window.connect("destroy", lambda *a: gtk.main_quit())
        window.show_all()
        gtk.main()

