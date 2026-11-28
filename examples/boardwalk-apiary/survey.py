"""Print the boardwalk terrain survey from Stardew Valley Planner's tile layers."""
import argparse
from collections import deque
import json
from urllib.request import urlopen

LEGACY = ('https://raw.githubusercontent.com/hpeinar/stardewplanner/'
          'f6c8dd5fba513d78b95d491a8aa77d6532c55ee6/public/planner/js/data/layer-information')
CURRENT = 'https://stardew.info/planner/assets/dataLayers'

# Centerlines of visible stepping stones, bridges and stairs on the pinned Everfarm map.
# The water layer can contain "clear" cells offshore. Admit only surveyed crossings.
CROSSINGS = [
    (42, 88, 55, 88), (40, 100, 40, 114), (63, 127, 76, 127),
    (54, 6, 54, 11), (71, 11, 77, 11), (148, 10, 148, 16), (125, 25, 131, 25),
    (97, 32, 103, 32), (92, 36, 92, 41), (135, 41, 141, 41), (14, 37, 14, 42),
    (37, 34, 37, 39), (61, 73, 61, 78), (76, 61, 76, 67), (95, 57, 95, 63),
    (83, 75, 83, 80), (131, 69, 138, 69), (154, 62, 154, 67), (191, 75, 191, 80),
    (179, 115, 179, 120), (123, 114, 123, 119),
]


def rectangle(left, top, right, bottom):
    return {(x, y) for x in range(left, right+1) for y in range(top, bottom+1)}


def layer(farm, name, key):
    sources = [LEGACY, CURRENT] if farm == 'beach' else [LEGACY]
    surveys = []
    for source in sources:
        with urlopen(f'{source}/{farm}_{name}.json', timeout=30) as response:
            tiles = json.load(response)[f'{name}.{key}']['Tiles']
        surveys.append({tuple(map(int, tile.split(','))) for tile in tiles})
    return set.intersection(*surveys)


def survey(farm):
    clear = layer(farm, 'accessible', 'clear')
    build = clear & layer(farm, 'buildable', 'buildable')
    soil = build & layer(farm, 'tillable', 'tillable')
    if farm == 'everfarm':
        width, height, home = 200, 156, (183, 10)
        reserve = rectangle(165, 0, 199, 18) | rectangle(125, 86, 175, 120)
        for x, y in layer(farm, 'accessible', 'warp'):
            reserve.update(rectangle(x-2, y-2, x+2, y+2))
        floor = build | (clear & set().union(*(rectangle(*r) for r in CROSSINGS)))
    else:
        width, height, home = 110, 110, (64, 19)
        reserve = rectangle(23, 48, 46, 61) | rectangle(55, 0, 82, 20)
        floor = build - rectangle(24, 50, 44, 59)

    reached, queue = {home}, deque([home])
    while queue:
        x, y = queue.popleft()
        for p in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            if p in floor and p not in reached:
                reached.add(p)
                queue.append(p)
    tiles = dict.fromkeys(reached, 'W')
    tiles.update(dict.fromkeys((reached & build) - reserve, '.'))
    tiles.update(dict.fromkeys((reached & soil) - reserve, 'P'))
    tiles[home] = 'E'
    return [''.join(tiles.get((x, y), 'X') for x in range(width)) for y in range(height)]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('farm', choices=('beach', 'everfarm'))
    print('\n'.join(survey(parser.parse_args().farm)))
