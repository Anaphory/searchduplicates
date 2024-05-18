#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

import argparse
import fnmatch
import hashlib
import logging
import os
import shlex
import stat
import sys
import typing
import tqdm
from pathlib import Path

LICENSE = """Copyright (c) 2015, 2024, Gereon Kaiping <gereon.kaiping@gmail.com>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the
   distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
“AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."""


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find duplicate files.")
    parser.add_argument(
        "paths", metavar="PATH", nargs="+", type=Path, help="consider this path"
    )

    parser.add_argument(
        "--no-follow-links",
        "-L",
        action="store_const",
        dest="follow_links",
        const=False,
        default=True,
        help="Do not follow soft links.",
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

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_const",
        default=False,
        const=True,
    )

    parser.add_argument(
        "--script",
        "-c",
        action="store_const",
        dest="script",
        const=True,
        default=False,
        help="Generate a bash script that replaces copies of the original by symbolic links to the original.",
    )

    original = parser.add_argument_group(
        "Original/Copy sorting arguments",
        "File names are matched against the glob-style patterns in ORIGINAL and NOTORIGINAL, scoring one point for each ORIGINAL and minus one point for each NOTORIGINAL matched. The file with the highest score is assumed to be the original, for deletion and linking purposes.",
    )
    original.add_argument(
        "--longest",
        "-l",
        action="store_const",
        dest="long",
        const=True,
        default=None,
        help="Assume that the original file has the longest path",
    )
    original.add_argument(
        "--shortest",
        "-s",
        action="store_const",
        dest="long",
        const=False,
        help="Assume that the original file has the shortest path",
    )
    original.add_argument(
        "--original",
        "-o",
        action="append",
        type=str,
        default=[],
        help="assume that files matching ORIGINAL are originals",
    )
    original.add_argument(
        "--notoriginal",
        "-n",
        action="append",
        type=str,
        default=[],
        help="assume that files matching NOTORIGINAL are copies",
    )

    parser.add_argument(
        "--include",
        "-i",
        action="append",
        type=str,
        default=[],
        help="consider only files matching INCLUDE (in all directories)",
    )
    # Thus, -x .git behaves similarly to -n */.git
    parser.add_argument(
        "--exclude",
        "-x",
        action="append",
        type=str,
        default=[],
        help="exclude files matching EXCLUDE",
    )

    parser.add_argument(
        "--min-size",
        "-m",
        type=int,
        default=1,
        help="ignore files smaller than MIN_SIZE bytes",
    )

    return parser


def true(p: Path) -> bool:
    return True


def files_by_size(
    path: Path,
    min_size=100,
    follow_links=False,
    recursive=True,
    extend: typing.Optional[typing.DefaultDict[typing.Optional[int], set[Path]]] = None,
    include=true,
):
    if extend is None:
        extend = typing.DefaultDict(set)
    if args.verbose:
        logging.info('Stepping into directory "%s"....', path)
    for f in filter(include, path.iterdir()):
        try:
            if not follow_links and f.is_symlink():
                continue
            f = f.resolve(strict=True)
            if f in extend[None]:
                continue
            if recursive and f.is_dir():
                extend[None].add(f)
                try:
                    files_by_size(f, min_size, follow_links, True, extend, include)
                except (RecursionError, RuntimeError):
                    logging.warning(
                        "Exceeding recursion depth while visiting %s. Do you have a recursive file system?",
                        f,
                    )
                    continue
            if not f.is_file():
                continue
            size = f.stat().st_size
            if size < min_size:
                continue
            extend[size].add(f)
        except FileNotFoundError:
            # File got deleted between the scanning of the path and the scanning of itself
            pass
        except (IOError, OSError) as e:
            code, text = e.args
            logging.warning('Error %d reading "%s": %s', code, path, text)
            continue
    return extend


def make_filter(include, exclude) -> typing.Callable[[Path], bool]:
    def filter(p: Path) -> bool:
        return ((not include) or any(p.match(i) for i in include)) and not any(
            p.match(x) for x in exclude
        )

    return filter


def make_score(pro, contra):
    def score(p: Path) -> int:
        return sum(p.match(i) for i in contra) - sum(p.match(i) for i in pro)

    return score


def relpath_unless_via_root(
    path: Path, start: Path = Path("."), roots: list[Path] = [Path("/")]
):
    """Return the relative path from start to path, unless the relative
    path traverses via an element of roots, in which case return the
    absolute path."""
    path = path.resolve()
    try:
        relpath = path.relative_to(start.resolve())
        for root in roots:
            try:
                start.resolve().relative_to(root.resolve())
                # If the start is below this root, the relpath will also be.
                continue
            except ValueError:
                pass
            try:
                path.relative_to(root.resolve())
                # This path is below the root, but the start is not. Return the
                # absolute path.
                return path
            except ValueError:
                continue
    except ValueError:
        return path
    return relpath


if __name__ == "__main__":
    args = parser().parse_args()
    logging.basicConfig(level=logging.INFO)

    files_by_size_dict: typing.DefaultDict[
        typing.Optional[int], set[Path]
    ] = typing.DefaultDict(set)
    visited_directories = set()

    for x in args.paths:
        logging.info('Scanning directory "%s"....', x)
        files_by_size(
            x,
            min_size=args.min_size,
            recursive=args.recursive,
            extend=files_by_size_dict,
            include=make_filter(args.include, args.exclude),
            follow_links=args.follow_links,
        )

    logging.info("Finding potential dupes...")
    potentialDupes = []
    potentialCount = 0
    del files_by_size_dict[None]
    for k in tqdm.tqdm(sorted(files_by_size_dict.keys(), reverse=True)):
        inFiles = files_by_size_dict[k]
        hashes = typing.DefaultDict(list)
        if len(inFiles) == 1:
            continue
        logging.debug("Testing %d files of size %d...", len(inFiles), k)
        for filename in inFiles:
            if not filename.is_file():
                continue
            try:
                with filename.open("rb") as aFile:
                    hasher = hashlib.sha256(aFile.read(1024))
                    hashValue = hasher.digest()
                    hashes[hashValue].append(filename)
            except PermissionError:
                continue
        for outFiles in hashes.values():
            if len(outFiles) > 1:
                potentialDupes.append(outFiles)
                potentialCount = potentialCount + len(outFiles)
    del files_by_size_dict

    logging.info("Found %d sets of potential dupes...", potentialCount)
    logging.info("Scanning for real dupes...")

    dupes = []
    for aSet in tqdm.tqdm(potentialDupes):
        hashes = {}
        for filename in aSet:
            if args.verbose:
                logging.debug('Scanning file "%s"...' % filename, file=sys.stderr)
            try:
                with open(filename, "rb") as aFile:
                    hasher = hashlib.sha256()
                    while True:
                        r = aFile.read(4096)
                        if not len(r):
                            break
                        hasher.update(r)
                    hashValue = hasher.digest()
                    if hashValue in hashes:
                        hashes[hashValue].append(filename)
                    else:
                        hashes[hashValue] = [filename]
            except (IOError, OSError, PermissionError):
                continue
        for outFiles in list(hashes.values()):
            if len(outFiles) > 1:
                if args.long is not None:
                    outFiles.sort(
                        key=lambda p: (len(p.parts), len(str(p))), reverse=args.long
                    )
                dupes.append(
                    sorted(
                        outFiles, key=make_score(args.original, args.notoriginal)
                    )
                )

    for group in dupes:
        if args.script:
            original = group[0]
            try:
                print("# Assuming {:} is the original.".format(original))
                print("ORIGINAL={:s}".format(shlex.quote(str(original))))
                print("for FILE in \\\n    {:s}".format("\\\n    ".join([shlex.quote(str(p)) for p in group])))
            except UnicodeEncodeError:
                print("# Problem with encoding of file set {:s}".format(repr(original)))
                continue
            print("  do")
            print('  if [ "${FILE}" != "${ORIGINAL}" ]')
            print("  then")
            print('    rm "${FILE}"')
            print("  fi")
            print("done")
            for f in group[1:]:
                print(
                    "# ln -s {:s} {:s}".format(
                        shlex.quote(str(
                            relpath_unless_via_root(
                                original, f.parent, args.paths
                            )
                        )),
                        shlex.quote(str(f)),
                    )
                )
            print()
        else:
            try:
                for d in group:
                    print(d)
                print("====")
            except UnicodeEncodeError:
                print("#UnicodeEncodeError:")
                print("\n".join([repr(file) for file in group]), end="\n====\n")
