import argparse
import json
from pathlib import Path
import sys
from .core import Invalid, build_bundle, dumps, loads, new_review, read_directory, write_fresh, LIMITS
from .demo import create_demo
from .runtime import deadline
from .validate import validate_bundle

def main(argv=None):
    p = argparse.ArgumentParser(description='Offline trace review. Never executes recorded actions.')
    sub = p.add_subparsers(dest='command', required=True)
    d = sub.add_parser('demo', help='create reproducible synthetic input and a synthetic-only example review')
    d.add_argument('destination')
    ins = sub.add_parser('inspect', help='validate input and report source-bound hashes')
    ins.add_argument('source')
    rev = sub.add_parser('review', help='create an unconfirmed review specification')
    rev.add_argument('source'); rev.add_argument('destination')
    exp = sub.add_parser('export', help='export a reviewed source to a fresh directory')
    exp.add_argument('source'); exp.add_argument('review'); exp.add_argument('destination')
    val = sub.add_parser('validate', help='independently validate exported bundle integrity')
    val.add_argument('bundle')
    srv = sub.add_parser('serve', help='open loopback-only workbench; Ctrl+C stops and discards memory')
    srv.add_argument('source', nargs='?'); srv.add_argument('--port', type=int, default=8765)
    args = p.parse_args(argv)
    try:
        if args.command == 'serve':
            from .server import serve
            serve(args.source, args.port)
            return 0
        with deadline():
            if args.command == 'demo':
                create_demo(args.destination)
                print('Created synthetic demo. example-review.json is for this planted fixture only.')
            elif args.command == 'validate':
                print(json.dumps(validate_bundle(args.bundle), sort_keys=True))
            else:
                source = read_directory(args.source)
                if args.command == 'inspect':
                    print(json.dumps({'source':source.digest, 'hashes':source.hashes, 'actions':len(source.actions),
                                      'images':len(source.images), 'synthetic':source.trace['synthetic'], 'limits':LIMITS}, sort_keys=True))
                elif args.command == 'review':
                    with open(args.destination, 'xb') as f:
                        f.write(dumps(new_review(source)))
                else:
                    with open(args.review, 'rb') as f:
                        review = loads(f.read(LIMITS['json_bytes']+1))
                    write_fresh(build_bundle(source, review), args.destination)
                    print('Exported reviewed bundle. Manual review does not guarantee de-identification.')
        return 0
    except KeyboardInterrupt:
        print('Cancelled', file=sys.stderr)
        return 130
    except (Invalid, ValueError, OSError) as e:
        print(f'Error: {e}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
