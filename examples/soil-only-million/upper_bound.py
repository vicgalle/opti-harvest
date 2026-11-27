"""Geometric upper bounds for the surveyed, protected, zero-pot island farm."""

from itertools import product
from pathlib import Path


TERRAIN = Path(__file__).resolve().parents[1] / 'mixed-farm' / 'terrain.txt'
KING = tuple(product(range(-1, 2), repeat=2))
BLOOM = tuple((dx, dy) for dx, dy in product(range(-5, 6), repeat=2)
              if abs(dx) + abs(dy) <= 5)


def expanded(cells, offsets):
    return {(x + dx, y + dy) for x, y in cells for dx, dy in offsets}


def area_counts(terrain, field):
    floor = {p for p, tile in terrain.items() if tile in '.PSEW'}
    build = {p for p in floor if terrain[p] in '.PS'}
    soil = {p for p in floor if terrain[p] == 'S'}
    reserved = floor - build | field
    # A protected flower cannot border uncharted, compulsory-open or crop ground.
    possible_roses = {p for p in soil - field if all(
        terrain.get(q, ' ') != ' ' and q not in reserved for q in expanded([p], KING))}
    area = (build - field) & expanded(possible_roses, BLOOM)
    exterior = floor - field - area
    interior = area - expanded(exterior, KING)
    return len(area), len(interior), len(soil - field - area)


def house_bound(terrain, field):
    area, interior, _ = area_counts(terrain, field)
    # About each visited tile, allow all eight pickups. A cardinal step can bring
    # at most three new cells into this 3-by-3 square. Each flower serves ≤48 houses.
    return max(houses for houses in range(area + 1)
               if 3 * houses + 2 * ((houses + 47) // 48) <= 3 * area - interior)


def main():
    rows = [line for line in TERRAIN.read_text().splitlines() if not line.startswith('#')]
    terrain = {(x, y): symbol for y, row in enumerate(rows) for x, symbol in enumerate(row)}
    houses = 1051
    area, interior, exterior_soil = area_counts(terrain, set())
    flowers = (houses + 47) // 48
    field_budget = (3 * (area - houses) - interior - 2 * flowers) // 2 + exterior_soil
    crop_limit = field_budget * 24 // 25
    print(f'{area} eligible cells, {interior} interior cells, {exterior_soil} other soil cells')
    print(f'At {houses} houses: at most {field_budget} crop and sprinkler tiles, '
          f'at most {crop_limit} irrigated plants')

    soil = {p for p in terrain if terrain[p] == 'S'}
    rectangles = {}
    for x, y in soil:
        rectangle = {(x + dx, y + dy) for dx in range(25) for dy in range(20)}
        if rectangle <= soil:
            rectangles[x, y] = house_bound(terrain, rectangle)
    print(f'With the published 25×20 field: at most {rectangles[52, 13]} houses')
    print(f'Across {len(rectangles)} legal 25×20 positions: at most {max(rectangles.values())} houses')


if __name__ == '__main__':
    main()
