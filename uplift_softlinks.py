import logging
import argparse
import typing as t
import shlex
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replace directories containing only compatible softlinks with a softlink to the other directory."
    )
    parser.add_argument(
        "paths",
        metavar="PATH",
        nargs="+",
        type=Path,
        help="Search for relevant directories in these locations.",
    )
    parser.add_argument(
        "--flat",
        "-f",
        action="store_const",
        dest="recursive",
        const=False,
        default=True,
        help="Do not step down into subdirectories",
    )
    return parser




def find_softlink_dirs(path: Path, recursive: bool = True):
    logging.info('Stepping into directory "%s"....', path)
    symlink_targets = set()
    symlinkable = True
    for f in path.iterdir():
        if f.is_symlink():
            target = f.resolve()
            if target.name != f.name:
                symlinkable = False
            else:
                symlink_targets.add(target.parent)
        elif recursive and f.is_dir():
            subdir_is_symlinkable = False
            for p, target in find_softlink_dirs(f, recursive):
                if f == p:
                    subdir_is_symlinkable = True
                    symlink_targets.add(target.parent)
                yield (p, target)
            if not subdir_is_symlinkable:
                symlinkable = False
                continue
        else:
            symlinkable = False
            continue
    else:
        if len(symlink_targets) == 1 and symlinkable:
            symlink_target = symlink_targets.pop()
            yield (path, symlink_target)
        else:
            return


if __name__ == "__main__":
    args = parser().parse_args()
    for x in args.paths:
        logging.info('Scanning directory "%s"....', x)
        for dir, target in find_softlink_dirs(
            x,
            recursive=args.recursive,
        ):
            print(f"rm -r {shlex.quote(str(dir))}; ln -s {shlex.quote(str(target))} {shlex.quote(str(dir))}")
