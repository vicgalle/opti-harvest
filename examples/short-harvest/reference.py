"""Replay the 571-house source and certify shortest full tours for the three comparison maps."""
import argparse
from collections import defaultdict
from functools import cache
from pathlib import Path

from compare import ROOT, Island, bridge_blocks, necessary_bridges, read_grid
from island_route import check_walk, read_walk


def compulsory_tour(board, block, sites):
    """Shortest round trip through the required tiles inside one bridge-free component."""
    sites = sorted(sites)
    distances = []
    for site in sites:
        steps = {site: 0}
        queue = [site]
        for p in queue:
            for q in board.sides[p] & block:
                if q not in steps:
                    steps[q] = steps[p] + 1
                    queue.append(q)
        distances.append([steps[q] for q in sites])

    @cache
    def remaining(last, unseen):
        if not unseen:
            return distances[last][0]
        return min(distances[last][i] + remaining(i, unseen ^ (1 << i))
                   for i in range(1, len(sites)) if unseen & (1 << i))

    return remaining(0, (1 << len(sites)) - 2)


def certify(board, houses, flowers, directions):
    board.verify(houses, flowers)
    walk = read_walk(board.start, directions)
    check_walk(board, houses, flowers, walk)
    ground = board.flood(board.start, board.floor - houses - flowers)
    bridges, block = bridge_blocks(board, ground)
    forced = necessary_bridges(board, ground, houses, len(houses), bridges, block)
    must_visit = {board.start} | {p for endpoints in forced for p in endpoints}
    for p in houses:
        stands = board.stands[p] & ground
        if len(stands) == 1:
            must_visit.update(stands)
    terminals = defaultdict(set)
    for p in must_visit:
        terminals[block[p]].add(p)
    internal = []
    for group, sites in terminals.items():
        if len(sites) > 1:
            area = {p for p in ground if block[p] == group}
            internal.append(compulsory_tour(board, area, sites))
    lower = 2 * len(forced) + sum(internal)
    steps = len(walk) - 1
    if steps != lower:
        raise ValueError(f'walk takes {steps} steps, required links and local tours account for {lower}')
    segment_costs = ' + '.join(map(str, sorted(internal, reverse=True)))
    print(f'{len(houses)} houses from {board.start} have an exact {steps}-step tour. '
          f'{len(forced)} forced links × 2 + {segment_costs} = {lower}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent
    parser.add_argument('layout', type=Path, nargs='?', default=here / 'reference-571.txt',
                        help='override the copy of the 571-house grid decoded from the published PNG')
    args = parser.parse_args()
    rows = read_grid(ROOT / 'examples/ginger-island/terrain.txt')
    board = Island(rows)
    houses, flowers = board.decode(read_grid(args.layout))
    if len(houses) != 571:
        parser.error('use the decoded 571-house reference grid')
    for name, gate in [('north', board.start), ('east', (36, 24))]:
        board.start = gate
        certify(board, houses, flowers, (here / f'reference-{name}-walk.txt').read_text())

    board.start = (36, 24)
    published = read_walk(board.start, (here / 'published-walk.txt').read_text())
    check_walk(board, houses, flowers, published)
    moves = [(b[0]-a[0], b[1]-a[1]) for a, b in zip(published, published[1:])]
    turns = sum(a != b for a, b in zip(moves, moves[1:]))
    if (len(moves), turns) != (742, 336):
        raise ValueError('published reconstruction disagrees with the original image caption')
    print(f'The published route replays in {len(moves)} steps and {turns} turns from {board.start}.')

    west = ROOT / 'examples/ginger-island'
    comparisons = [(False, west / '600-houses.txt', here / '600-shortest-walk.txt'),
                   (True, west / 'side-only/545-houses.txt', west / 'side-only/harvest-walk.txt'),
                   (False, here / 'shorter-600.txt', here / 'shorter-600-walk.txt')]
    for side_only, layout, route in comparisons:
        board = Island(rows, side_only=side_only)
        houses, flowers = board.decode(read_grid(layout))
        certify(board, houses, flowers, route.read_text())


if __name__ == '__main__':
    main()
