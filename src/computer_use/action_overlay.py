"""Render input feedback at native pixel scale, without changing coordinate space."""
from .contracts import PointerFeedback


COLORS = {'click': '#ffca28', 'scroll': '#ffca28', 'start': '#00e5ff', 'end': '#ff8a65'}
RULER_STEP = 10
RULER_LENGTH = 50


def annotate_action(image, rect, feedback: PointerFeedback):
    from PIL import ImageDraw, ImageFont
    # Never mutate the backend's frame; annotations exist only in the returned PNG.
    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    font = ImageFont.load_default()
    ruler = _draw_ruler(draw, font, image.width, image.height)
    points = []
    for point in feedback.points:
        x, y = point.screen_x - rect[0], point.screen_y - rect[1]
        visible = 0 <= x < image.width and 0 <= y < image.height
        points.append({'role': point.role, 'screen_x': point.screen_x,
                       'screen_y': point.screen_y, 'x': x, 'y': y, 'visible': visible})
        if not visible:
            continue  # Do not clamp a point to an unrelated edge pixel.
        color = COLORS[point.role]
        label = f'{point.role} ({x},{y})'
        box = draw.textbbox((0, 0), label, font=font)
        label_width, label_height = box[2] - box[0], box[3] - box[1]
        # Labels may be moved to fit; the X center is never moved.
        lx = max(0, min(x + 10, image.width - label_width - 4))
        ly = y + 10 if y + label_height + 16 < image.height else max(0, y - label_height - 12)
        draw.rectangle((lx, ly, lx + label_width + 3, ly + label_height + 3), fill='black')
        draw.text((lx + 1 - box[0], ly + 1 - box[1]), label, font=font, fill=color)
    # Draw centers last so neither a label nor a ruler can hide the dispatched point.
    for point in points:
        if point['visible']:
            x, y = point['x'], point['y']
            for width, ink in ((3, 'black'), (1, COLORS[point['role']])):
                draw.line((x - 4, y - 4, x + 4, y + 4), fill=ink, width=width)
                draw.line((x - 4, y + 4, x + 4, y - 4), fill=ink, width=width)
    return marked, {'kind': 'dispatched_pointer', 'points': points, 'ruler': ruler,
                    'coordinate_space': 'window_pixels', 'image_scale': 1,
                    'meaning': 'X marks historical screen positions sent to input, not verified hits. '
                               'Content may move after input. Ruler ticks are 10 original image pixels. '
                               'Labels/ruler are tool overlays, not application content.'}


def _draw_ruler(draw, font, width, height):
    ruler = {'tick_spacing_px': RULER_STEP, 'length_px': RULER_LENGTH,
             'drawn': width >= 100 and height >= 100}
    if ruler['drawn']:
        # One two-axis ruler, with exact 10-original-pixel tick spacing.
        ox, oy = 10, height - 12
        ruler.update(origin_x=ox, origin_y=oy)
        for width, color in ((3, 'black'), (1, 'white')):
            draw.line((ox, oy, ox + RULER_LENGTH, oy), fill=color, width=width)
            draw.line((ox, oy, ox, oy - RULER_LENGTH), fill=color, width=width)
            for delta in range(0, RULER_LENGTH + 1, RULER_STEP):
                draw.line((ox + delta, oy - 3, ox + delta, oy + 3), fill=color, width=width)
                draw.line((ox - 3, oy - delta, ox + 3, oy - delta), fill=color, width=width)
        draw.text((ox + 8, oy - 48), '10 px/tick', font=font, fill='white',
                  stroke_width=1, stroke_fill='black')
    else:
        ruler['omitted_reason'] = 'Image is too small for the 50 px two-axis ruler and label.'
    return ruler
