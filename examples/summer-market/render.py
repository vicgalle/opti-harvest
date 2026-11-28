"""Render the two market maps and printable construction sheets (optional Pillow)."""

import argparse
import json
from pathlib import Path
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from layout import HERE, TERRAINS, Farm, BUILDINGS, process

PLANNER = 'https://stardew.info/planner/assets'
SOURCES = {
    'sprites.png': f'{PLANNER}/tilesheets/sprites.png',
    'four-corners.png': f'{PLANNER}/farms/farm_fourcorners_summer.png',
    'everfarm.jpg': (
        'https://raw.githubusercontent.com/hpeinar/stardewplanner/'
        'f6c8dd5fba513d78b95d491a8aa77d6532c55ee6/public/planner/img/layouts/everfarm.jpg'
    ),
}
# Sprite atlas coordinates in original pixels.
SPRITES = {
    'c': (576, 1085, 16, 32),
    'b': (144, 1085, 16, 32),
    'h': (1136, 128, 16, 32),
    'p': (864, 1117, 16, 32),
    'I': (544, 1181, 16, 16),
    'S': (1152, 480, 16, 32),
    'L': (976, 1149, 16, 32),
    'F': (336, 736, 48, 80),
    'barn': (192, 336, 112, 112),
    'big-barn': (304, 336, 112, 112),
    'shed': (400, 0, 112, 128),
    'big-shed': (288, 192, 112, 128),
    'O': (96, 336, 48, 128),
    'house': (256, 0, 144, 144),
    'greenhouse': (0, 0, 128, 192),
    'bin': (1088, 160, 32, 32),
    'soil': (512, 1181, 16, 16),
    'brick': (320, 320, 16, 16),
}
PAPER, INK, MUTED, RULE = '#f8f4e8', '#193f35', '#4f6256', '#c9c5ae'
CROP = {'c': 'Coffee', 'p': 'Hot pepper', 'h': 'Hops', 'b': 'Blueberry'}
COLORS = {
    'c': '#477958',
    'p': '#b64832',
    'h': '#c5c875',
    'b': '#4d6294',
    'I': '#487889',
    'S': '#846136',
    'N': '#9f5e48',
    'D': '#99714e',
    'T': '#99714e',
    'O': '#a3a092',
    'L': '#c69e56',
    '+': '#e4ceb0',
    'K': '#79503a',
    'J': '#b5695b',
    'Q': '#ceac57',
    'E': '#90b097',
    'F': '#f0a678',
    '.': '#f2eadb',
    'X': '#dbdacf',
}


def font(size, style='regular'):
    choices = {
        'serif': ('Georgia Bold.ttf', 'DejaVuSerif-Bold.ttf'),
        'bold': ('Arial Bold.ttf', 'DejaVuSans-Bold.ttf'),
        'regular': ('Arial.ttf', 'DejaVuSans.ttf'),
    }[style]
    for file in (Path('/System/Library/Fonts/Supplemental') / choices[0], *choices):
        try:
            return ImageFont.truetype(str(file), size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def label(draw, x, y, text, size, service='regular', color=INK, anchor='lt'):
    draw.text((x, y), str(text), font=font(size, service), fill=color, anchor=anchor)


def bounds(points):
    return (
        min(x for x, y in points),
        min(y for x, y in points),
        max(x for x, y in points),
        max(y for x, y in points),
    )


def artwork(assets):
    sheet = Image.open(assets / 'sprites.png').convert('RGBA')
    return {k: sheet.crop((x, y, x + w, y + h)) for k, (x, y, w, h) in SPRITES.items()}


def marked(farm, rows):
    return {p: rows[p[1]][p[0]] for p, v in farm.base.items() if rows[p[1]][p[0]] != v}


def scene(name, assets, art, tiles):
    small = name == 'four-corners'
    image = Image.open(assets / ('four-corners.png' if small else 'everfarm.jpg')).convert('RGBA')
    objects = []
    for (x, y), c in tiles.items():
        if c in 'cbphI':
            image.alpha_composite(art['soil'], (x * 16, y * 16))
        if c == '+':
            image.alpha_composite(art['brick'], (x * 16, y * 16))
        if c in 'cbphISL':
            objects.append((y, x, c))
        elif c == 'F':
            objects.append((y, x - 1, c))
    buildings = {}
    for code in BUILDINGS:
        cells = [p for p, c in tiles.items() if c == code]
        if not cells:
            continue
        x, top, _, bottom = bounds(cells)
        sprite = {
            'N': 'barn' if small else 'big-barn',
            'D': 'shed' if small else 'big-shed',
            'T': 'big-shed',
            'O': 'O',
        }[code]
        objects.append((bottom, x, sprite))
        buildings[code] = (x, top)
    if small:
        objects += [(16, 59, 'house'), (36, 35, 'greenhouse'), (14, 71, 'bin')]
    for y, x, k in sorted(objects):
        sprite = art[k]
        image.alpha_composite(sprite, (16 * x, 16 * (y + 1) - sprite.height))
    return image.convert('RGB'), buildings


def showcase(name, assets, art, out):
    small = name == 'four-corners'
    plan = json.loads((out / f'{name}.json').read_text())
    _, walks = process(name, plan, out, False)
    farm = Farm(name)
    rows = (out / f'{name}-farm.txt').read_text().splitlines()
    tiles = marked(farm, rows)
    world, buildings = scene(name, assets, art, tiles)
    x0, y0, x1, y1 = bounds(set(tiles) | {farm.home})
    x0, y0 = max(0, x0 - 6), max(0, y0 - (11 if small else 9))
    x1, y1 = min(len(rows[0]), x1 + 6), min(len(rows), y1 + 5)
    crop = world.crop((x0 * 16, y0 * 16, x1 * 16, y1 * 16))
    scale = 26 if small else 20
    crop = crop.resize(((x1 - x0) * scale, (y1 - y0) * scale), Image.Resampling.NEAREST)
    left, top, side = 43, 111, 345
    W, H = left + crop.width + side + 42, max(top + crop.height + 57, 836)
    page = Image.new('RGB', (W, H), PAPER)
    d = ImageDraw.Draw(page)
    title = 'The farmhouse market' if small else 'Six gardens on Everfarm'
    label(
        d, left, 12, 'FOUR CORNERS  /  VANILLA' if small else 'EVERFARM  /  DRAYLON’S MAP', 17, 'bold', MUTED
    )
    label(d, left, 40, title, 46, 'serif')
    page.paste(crop, (left, top))
    d.rectangle((left - 1, top - 1, left + crop.width, top + crop.height), outline=RULE)
    for x in range((x0 + 4) // 5 * 5, x1, 5):
        px = left + (x - x0 + 0.5) * scale
        label(d, px, top - 4, x, 13, 'regular', MUTED, 'mb')
    for y in range((y0 + 4) // 5 * 5, y1, 5):
        label(d, left - 8, top + (y - y0 + 0.5) * scale, y, 13, 'regular', MUTED, 'rm')
    sx = left + crop.width + 26
    crew = plan['budget']['crew']
    label(d, sx, top, 'SUMMER 12–28', 16, 'bold', MUTED)
    label(d, sx, top + 29, f'{crew} Pepper Poppers', 27, 'serif')
    label(d, sx, top + 66, f'{crew*plan["budget"]["shots"]} Triple Shot Espressos', 23, 'serif')
    label(d, sx, top + 104, 'Packed each morning', 18, 'regular', MUTED)
    d.line((sx, top + 145, W - 24, top + 145), fill=RULE, width=2)
    label(d, sx, top + 163, f'{plan["gross"]:,}g', 39, 'serif')
    label(d, sx, top + 215, 'Summer sales after provisions', 18, 'regular', MUTED)
    y = top + 267
    for code, item in {**CROP, 'F': 'Peach trees'}.items():
        sprite = art[code].crop(art[code].getbbox())
        sprite.thumbnail((30, 34), Image.Resampling.NEAREST)
        page.paste(sprite, (sx + (30 - sprite.width) // 2, y + (19 - sprite.height) // 2), sprite)
        label(d, sx + 38, y, item, 20)
        label(d, W - 30, y, sum(c == code for c in tiles.values()), 20, 'bold', INK, 'rt')
        y += 39
    d.line((sx, y + 2, W - 24, y + 2), fill=RULE, width=2)
    label(d, sx, y + 22, 'Where to build', 23, 'serif')
    thumb = world.copy()
    thumb.thumbnail((side - 10, max(110, min(H - y - 186, 265))), Image.Resampling.LANCZOS)
    tx, ty = sx, y + 62
    page.paste(thumb, (tx, ty))
    px, py = thumb.width / world.width * 16, thumb.height / world.height * 16
    rx, ry, rr, rb = bounds(tiles)
    d.rectangle(
        (tx + rx * px, ty + ry * py, tx + (rr + 1) * px, ty + (rb + 1) * py), outline='#fff5b9', width=3
    )
    d.rectangle((tx, ty, tx + thumb.width, ty + thumb.height), outline=RULE)
    wy = ty + thumb.height + 20
    label(d, sx, wy, 'Inside the shed' if small else 'Across both big sheds', 21, 'serif')
    budget = plan['budget']
    label(
        d,
        sx,
        wy + 31,
        f'{budget["keg"]} kegs  ·  {budget["jar"]} jars  ·  {budget["press"]} presses',
        18,
        'regular',
        MUTED,
    )
    label(
        d,
        left,
        H - 30,
        f'{plan["budget"]["sprinklers"]} iridium sprinklers    ·    {plan["budget"]["cows"]} cows    ·    '
        f'{walks["full"]} steps for a full outdoor round',
        18,
        'regular',
        MUTED,
    )
    info = PngInfo()
    info.add_text(
        'Credit',
        'Stardew Valley by ConcernedApe. Everfarm by Draylon. Map and sprite atlas via Henrik Peinar. Layout and graphic by Opti-Harvest.',
    )
    page.quantize(256).save(out / f'{name}-map.png', pnginfo=info, optimize=True)
    return build_sheet(name, farm, tiles, buildings, out)


def build_sheet(name, farm, tiles, buildings, out):
    page = Image.new('RGB', (1550, 1120), PAPER)
    draw = ImageDraw.Draw(page)
    label(
        draw,
        50,
        31,
        ('Four Corners' if name == 'four-corners' else 'Everfarm') + ' planting and workshop plan',
        42,
        'serif',
    )
    label(
        draw,
        50,
        96,
        'Tile coordinates start at zero in the northwest. Each workshop grid includes its south entrance.',
        21,
        'regular',
        MUTED,
    )
    x0, y0, rr, bb = bounds(tiles)
    size = min(32, 950 // (rr - x0 + 1), 750 // (bb - y0 + 1))
    ox, oy = 55, 177
    for y in range(y0, bb + 1):
        for x in range(x0, rr + 1):
            c = tiles.get((x, y), '')
            a, b = ox + (x - x0) * size, oy + (y - y0) * size
            fill = COLORS.get(c, '#ece9d5' if (x, y) in farm.floor else '#c5c7bc')
            draw.rectangle((a, b, a + size - 1, b + size - 1), fill=fill, outline='#d2cbbb')
            if not c:
                continue
            if c in 'cbphISLF':
                label(
                    draw,
                    a + size / 2,
                    b + size / 2,
                    c,
                    size // 2 + 1,
                    'bold',
                    'white' if c in 'cbpI' else INK,
                    'mm',
                )
    for x in range(x0, rr + 1):
        if x % 5 == 0:
            label(draw, ox + (x - x0 + 0.5) * size, oy - 6, x, 15, 'bold', MUTED, 'mb')
    for y in range(y0, bb + 1):
        if y % 5 == 0:
            label(draw, ox - 8, oy + (y - y0 + 0.5) * size, y, 15, 'bold', MUTED, 'rm')
    for k, (x, y) in buildings.items():
        w, h = BUILDINGS[k]
        label(
            draw,
            ox + (x - x0 + w / 2) * size,
            oy + (y - y0 + h / 2) * size,
            {'N': 'Barn', 'D': 'D', 'T': 'T', 'O': 'Silo'}[k],
            17,
            'bold',
            'white',
            'mm',
        )
    legend = [
        ('c', 'Coffee'),
        ('p', 'Hot pepper'),
        ('h', 'Hops'),
        ('b', 'Blueberry'),
        ('F', 'Peach tree'),
        ('I', 'Iridium sprinkler'),
        ('S', 'Scarecrow'),
        ('L', 'Wood lamp-post'),
        ('+', 'Paving'),
    ]
    ly = oy + (bb - y0 + 1) * size + 35
    for i, (k, txt) in enumerate(legend):
        x, y = ox + (i % 5) * 195, ly + (i // 5) * 48
        draw.rectangle((x, y, x + 26, y + 26), fill=COLORS[k])
        label(draw, x + 13, y + 13, k, 16, 'bold', 'white' if k in 'cpbI' else INK, 'mm')
        label(draw, x + 35, y + 4, txt, 18)
    sx = 1055
    y = 156
    for hall in ('D', 'T'):
        if hall not in buildings:
            continue
        interior = (out / f'{name}-{hall}.txt').read_text().splitlines()
        # Keep the door position and left/right wall; remove unused top wall rows.
        interior = interior[next(i for i, r in enumerate(interior) if r.strip('X')) - 1 :]
        label(draw, sx, y, 'Workshop ' + hall, 25, 'serif')
        y += 38
        t = 19 if name == 'everfarm' else 27
        for v, row in enumerate(interior):
            for u, c in enumerate(row):
                x0p = sx + u * t
                y0p = y + v * t
                draw.rectangle((x0p, y0p, x0p + t - 1, y0p + t - 1), fill=COLORS[c], outline=PAPER)
                if c in 'KJQE':
                    label(
                        draw,
                        x0p + t / 2,
                        y0p + t / 2,
                        c,
                        t // 2 + 1,
                        'bold',
                        INK if c in 'QE' else 'white',
                        'mm',
                    )
        y += len(interior) * t + 16
        counts = {k: ''.join(interior).count(k) for k in 'KJQ'}
        label(
            draw,
            sx,
            y,
            '   ·   '.join(
                f'{counts[k]} {n}' for k, n in [('K', 'kegs'), ('J', 'jars'), ('Q', 'presses')] if counts[k]
            ),
            17,
            'regular',
            MUTED,
        )
        y += 49
    label(draw, sx, y + 12, 'K  Keg     J  Preserves Jar     Q  Cheese Press', 16, 'regular', MUTED)
    label(
        draw,
        50,
        1063,
        'Use the summer calendar for daily machine loads. Leave the marked travel lanes open.',
        21,
        'regular',
        MUTED,
    )
    return page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True, help='cache directory for the planner artwork')
    parser.add_argument(
        '--directory', type=Path, default=HERE, help='directory with both solved farms and calendars'
    )
    args = parser.parse_args()
    args.assets.mkdir(parents=True, exist_ok=True)
    for file, url in SOURCES.items():
        dest = args.assets / file
        if not dest.exists():
            with urlopen(url, timeout=30) as response:
                dest.write_bytes(response.read())
    art = artwork(args.assets)
    sheets = [showcase(name, args.assets, art, args.directory) for name in TERRAINS]
    sheets[0].save(
        args.directory / 'build-sheets.pdf', save_all=True, append_images=sheets[1:], resolution=145
    )


if __name__ == '__main__':
    main()
