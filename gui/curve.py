# This file is part of MyPaint.
# Copyright (C) 2007-2011 by Martin Renold <martinxyz@gmx.ch>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import pygtkcompat
import gtk
from gtk import gdk


RADIUS = 4
class CurveWidget(gtk.DrawingArea):
    """Widget for modifying a (restricted) nonlinear curve.
    """
    __gtype_name__ = 'CurveWidget'
    snapto = (0.0, 0.25, 0.5, 0.75, 1.0)
    ylock = {}

    def __init__(self, changed_cb=None, magnetic=True, npoints = None, ylockgroups = ()):
        gtk.DrawingArea.__init__(self)
        self.points = [(0.0, 0.2), (.25, .5), (.75, .75), (1.0, 1.0)] # doesn't matter
        self.npoints = npoints
        if ylockgroups:
            self.ylock = {}
        for items in ylockgroups:
            for thisitem in items:
                others = list(items)
                others.remove (thisitem)
                self.ylock[thisitem] = tuple(others)

        self.maxpoints = 8 if not npoints else npoints
        self.grabbed = None
        if changed_cb is None:
            self.changed_cb = lambda *a: None
        else:
            self.changed_cb = changed_cb
        self.magnetic = magnetic

        if pygtkcompat.USE_GTK3:
            self.connect("draw", self.draw_cb)
        else:
            self.connect("expose-event", self.expose_cb)

        self.connect("button-press-event", self.button_press_cb)
        self.connect("button-release-event", self.button_release_cb)
        self.connect("motion-notify-event", self.motion_notify_cb)
        self.set_events(gdk.EXPOSURE_MASK |
                        gdk.BUTTON_PRESS_MASK |
                        gdk.BUTTON_RELEASE_MASK |
                        gdk.POINTER_MOTION_MASK
                        )
        self.set_size_request(300, 200)

        self.graypoint = None

    def eventpoint(self, event_x, event_y):
        width, height = self.get_display_area()
        x, y = event_x, event_y
        x -= RADIUS
        y -= RADIUS
        x = float(x) / width
        y = float(y) / height
        return (x, y)

    def get_display_area(self):
        alloc = self.get_allocation()
        width, height = alloc.width, alloc.height
        width  -= 2*RADIUS
        height -= 2*RADIUS
        width  = width / 4 * 4
        height = height / 4 * 4
        return width, height

    def set_point (self, index, value):
        y = value[1]
        self.points[index] = value
        if index in self.ylock:
            for lockedto in self.ylock[index]:
                self.points[lockedto] = (self.points[lockedto][0], y)

    def button_press_cb(self, widget, event):
        if not event.button == 1: return
        x, y = self.eventpoint(event.x, event.y)
        nearest = None
        for i in range(len(self.points)):
            px, py = self.points[i]
            dist = abs(px - x) + 0.5*abs(py - y)
            if nearest is None or dist < mindist:
                mindist = dist
                nearest = i
        if not self.npoints and mindist > 0.05 and len(self.points) < self.maxpoints:
            insertpos = 0
            for i in range(len(self.points)):
                if self.points[i][0] < x:
                    insertpos = i + 1
            if insertpos > 0 and insertpos < len(self.points):
                if y > 1.0: y = 1.0
                if y < 0.0: y = 0.0
                self.points.insert(insertpos, (x, y))
                # XXX and update ylockgroups?
                #
                nearest = insertpos
                self.queue_draw()

        #if nearest == 0:
        #    # first point cannot be grabbed
        #    display = gdk.display_get_default()
        #    display.beep()
        #else:
        #assert self.grabbed is None # This did happen. I think it's save to ignore?
        # I guess it's because gtk can generate button press event without corresponding release.
        self.grabbed = nearest

    def button_release_cb(self, widget, event):
        if not event.button == 1: return
        if self.grabbed:
            i = self.grabbed
            if self.points[i] is None:
                self.points.pop(i)
        self.grabbed = None
        # notify user of the widget
        self.changed_cb(self)

    def motion_notify_cb(self, widget, event):
        if self.grabbed is None: return
        x, y = self.eventpoint(event.x, event.y)
        i = self.grabbed
        # XXX this may fail for non contiguous groups.
        if i in self.ylock:
            possiblei = None
            if x > self.points[max(self.ylock[i])][0]:
                possiblei = max ((i,) + self.ylock[i])
            elif x < self.points[min(self.ylock[i])][0]:
                possiblei = min ((i,) + self.ylock[i])
            if (possiblei != None and
               abs (self.points[i][0] - self.points[possiblei][0]) < 0.001):
                i = possiblei
        out = False # by default, the point cannot be removed by drawing it out
        if i == len(self.points)-1:
            # last point stays right
            leftbound = rightbound = 1.0
        elif i == 0:
            # first point stays left
            leftbound = rightbound = 0.0
        else:
            # other points can be dragged out
            if not self.npoints and (y > 1.1 or y < -0.1): out = True
            leftbound  = self.points[i-1][0]
            rightbound = self.points[i+1][0]
            if not self.npoints and (x <= leftbound - 0.02 or x >= rightbound + 0.02): out = True
        if out:
            self.points[i] = None
        else:
            if y > 1.0: y = 1.0
            if y < 0.0: y = 0.0
            if self.magnetic:
                xdiff = [abs(x - v) for v in self.snapto]
                ydiff = [abs(y - v) for v in self.snapto]
                if min (xdiff) < 0.015 and min (ydiff) < 0.015:
                    y = self.snapto[ydiff.index (min (ydiff))]
                    x = self.snapto[xdiff.index (min (xdiff))]
            if x < leftbound: x = leftbound
            if x > rightbound: x = rightbound
            self.set_point(i, (x, y))
        self.queue_draw()

    def expose_cb(self, widget, event):
        gdk_win = widget.get_window()
        cr = gdk_win.cairo_create()
        self.draw_cb(widget, cr)

    def draw_cb(self, widget, cr):

        def gtk2rgb(c):
            return [float(c)/65535 for c in (c.red, c.green, c.blue)]

        style = widget.get_style()
        state = widget.get_state()
        gray  = gtk2rgb(style.bg[state])
        dark  = gtk2rgb(style.dark[state])
        black = gtk2rgb(style.fg[state])

        width, height = self.get_display_area()
        if width <= 0 or height <= 0: return

        # 1-pixel width, align lines with pixels
        # (but filled rectangles are off by 0.5px now)
        cr.set_line_width(1.0)
        cr.translate(0.5, 0.5)

        # draw grid lines
        cr.set_source_rgb(*dark)
        for i in range(5):
            cr.move_to(RADIUS, i*height/4 + RADIUS)
            cr.line_to(width + RADIUS, i*height/4 + RADIUS)
            cr.move_to(i*width/4 + RADIUS, RADIUS)
            cr.line_to(i*width/4 + RADIUS, height + RADIUS)
            cr.stroke()

        if self.graypoint:
            x1, y1 = self.graypoint
            x1 = int(x1*width) + RADIUS
            y1 = int(y1*height) + RADIUS
            cr.rectangle(x1-RADIUS-1+0.5, y1-RADIUS-1+0.5, 2*RADIUS+1, 2*RADIUS+1)
            cr.fill()

        cr.set_source_rgb(*black)
        # draw points
        for p in self.points:
            if p is None: continue
            x1, y1 = p
            x1 = int(x1*width) + RADIUS
            y1 = int(y1*height) + RADIUS
            cr.rectangle(x1-RADIUS-1+0.5, y1-RADIUS-1+0.5, 2*RADIUS+1, 2*RADIUS+1)
            cr.fill()
            if p is not self.points[0]:
                cr.move_to(x0, y0)
                cr.line_to(x1, y1)
                cr.stroke()
            x0, y0 = x1, y1

        return True



if __name__ == '__main__':
    win = gtk.Window()
    curve = CurveWidget(ylockgroups = ((1,2),))
    win.add(curve)
    win.set_title("curve test")
    win.connect("destroy", lambda *a: gtk.main_quit())
    win.show_all()
    gtk.main()


