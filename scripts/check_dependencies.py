"""Verify the installed Python dependency closure against a reviewed exact lock."""
import argparse
import importlib.metadata
import re
from pathlib import Path


def check(path):
    expected = {}
    normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s;]+)', line)
        if not match:
            raise ValueError('Lock must contain exact package==version entries only')
        key = normalize(match[1])
        if key in expected:
            raise ValueError('Duplicate locked distribution')
        expected[key] = match[2]
    actual = {normalize(d.metadata['Name']): d.version for d in importlib.metadata.distributions()}
    # pip bootstraps the environment; it is bounded separately in setup/Docker.
    actual.pop('pip', None)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])
        raise ValueError(f'Dependency drift: missing={missing}, extra={extra}, changed={changed}')
    print(f'{len(expected)} installed distributions match {path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', required=True, type=Path)
    check(parser.parse_args().lock)
