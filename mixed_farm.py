"""Check a mixed Ginger Island farm, including irrigation and a crop-free honey route."""
import argparse
from pathlib import Path

from apiary import AROUND, neighbors
from island import Island, read_grid
from island_route import check_walk, read_walk


def check_farm(terrain, layout):
    original = Island(terrain)
    if list(map(len, layout)) != list(map(len, terrain)):
        raise ValueError('layout and terrain dimensions differ')
    crops, sprinklers = set(), set()
    honey_rows = [list(row) for row in layout]
    for y, row in enumerate(layout):
        for x, tile in enumerate(row):
            if tile in 'C@':
                if original.base[x, y] != 'S':
                    raise ValueError(f'crop field extends beyond tillable soil at {(x, y)}')
                (crops if tile == 'C' else sprinklers).add((x, y))
                honey_rows[y][x] = 'S'
    irrigated = {(x+dx, y+dy) for x, y in sprinklers for dx in range(-2, 3)
                 for dy in range(-2, 3) if (dx, dy) != (0, 0)}
    if not crops or crops - irrigated:
        raise ValueError('every crop needs a standard iridium sprinkler within range')
    houses, roses = original.decode([''.join(row) for row in honey_rows])
    # Empty, walkable crop ground is the strict case for accidentally picking an exposed rose.
    original.verify(houses, roses)
    if roses & original.edge_beds:
        raise ValueError('a rose touches uncharted terrain')
    crop_access = original.flood(original.start, original.floor - houses - roses - sprinklers)
    if crops - crop_access:
        raise ValueError('a crop cannot be reached for harvest')

    # Exclude the entire crop field from honey collection. Mark its one-tile margin
    # and uncharted edges as ineligible for roses when re-optimizing this terrain.
    field = crops | sprinklers
    ineligible = original.edge_beds | {n for p in field for n in neighbors(p, AROUND)}
    masked = [list(row) for row in terrain]
    for x, y in ineligible & original.beds:
        masked[y][x] = '.'
    for x, y in field:
        masked[y][x] = 'X'
    honey = Island([''.join(row) for row in masked])
    honey.verify(houses, roses)
    return honey, houses, roses, crops, sprinklers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('terrain')
    parser.add_argument('layout', help='mixed grid with C for crop and @ for iridium sprinkler')
    parser.add_argument('--walk', help='replay a saved honey collection walk')
    parser.add_argument('--export', metavar='DIR', help='export the restricted terrain and layout for island.py')
    args = parser.parse_args()
    board, houses, roses, crops, sprinklers = check_farm(read_grid(args.terrain), read_grid(args.layout))
    print(f'{len(houses)} bee houses, {len(roses)} roses ({board.pots(roses)} potted), '
          f'{len(crops)} irrigated crops, {len(sprinklers)} sprinklers')
    if args.walk:
        walk = read_walk(board.start, Path(args.walk).read_text())
        check_walk(board, houses, roses, walk)
        print(f'Verified {len(walk)-1} steps, all pickups outside the crop field')
    if args.export:
        target = Path(args.export)
        target.mkdir(exist_ok=False, parents=True)
        (target / 'terrain.txt').write_text('\n'.join(board.rows) + '\n')
        (target / 'houses.txt').write_text('\n'.join(board.grid(houses, roses)) + '\n')


if __name__ == '__main__':
    main()
