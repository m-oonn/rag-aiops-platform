"""Render the two Playwright snippets for a round.

The Playwright snippets need the round directory, the environment's login and
the run's thread id *inside the browser*, so they cannot read the filesystem
themselves.  This renders them from the committed templates:

    python scripts/aiops_round/render_browser.py --round-dir runtime/aiops-goal-051

``browser-start.js`` needs only the round directory (and the login, which comes
from the round's own ``login.json``); ``browser-refresh.js`` additionally needs
the ``thread_id`` produced by the run, so call it again with ``--thread`` after
the click.  Both write next to this script by default.
"""
import argparse
import json
import sys
from pathlib import Path

from rounddir import ROOT, round_dir

TEMPLATES = Path(__file__).resolve().parent


def render(name, *, directory, login, thread):
    template = (TEMPLATES / name).read_text(encoding='utf-8')
    text = template.replace('__ROUND_DIR__', json.dumps(str(directory)))
    text = text.replace('__USERNAME__', json.dumps(login['username']))
    text = text.replace('__PASSWORD__', json.dumps(login['password']))
    text = text.replace('__THREAD__', json.dumps(thread or ''))
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round-dir', help='round directory (default: newest that ran)')
    parser.add_argument('--thread', default='', help='run thread id for the refresh snippet')
    parser.add_argument('--out-dir', default=str(TEMPLATES), help='where to write the snippets')
    args = parser.parse_args(argv)

    directory = round_dir([] if args.round_dir is None else ['--round-dir', args.round_dir])
    login = json.loads((directory / 'login.json').read_text(encoding='utf-8'))
    out = Path(args.out_dir)

    start = out / 'browser-start.js'
    start.write_text(render('browser-start.template.js', directory=directory,
                            login=login, thread=args.thread),
                     encoding='utf-8', newline='\n')
    written = [str(start)]

    if args.thread:
        refresh = out / 'browser-refresh.js'
        refresh.write_text(render('browser-refresh.template.js', directory=directory,
                                  login=login, thread=args.thread),
                           encoding='utf-8', newline='\n')
        written.append(str(refresh))
    else:
        print('no --thread given, browser-refresh.js not rendered', file=sys.stderr)

    print(json.dumps({'round_dir': str(directory), 'written': written}, ensure_ascii=False))


if __name__ == '__main__':
    main()
