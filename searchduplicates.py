#!/usr/bin/env python3
# -*- encoding: utf-8 -*-

LICENSE = """Copyright (c) 2012, Gereon Kaiping <anaphory@yahoo.de>
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

import os, os.path
import sys
import stat
import shlex
import hashlib
import fnmatch
import argparse

parser = argparse.ArgumentParser(description='Find duplicate files.')
parser.add_argument('paths', metavar='PATH',
                    nargs="+",
                    type=str,
                    help='consider this path')

parser.add_argument('--longest', '-l',
                    action='store_const',
                    dest='long',
                    const=True, default=None,
                    help='Assume that the original file has the longest path')

parser.add_argument('--shortest', '-s',
                    action='store_const',
                    dest='long',
                    const=False,
                    help='Assume that the original file has the shortest path')

parser.add_argument('--script', '-c',
                    action='store_const',
                    dest='script',
                    const=True, default=False,
                    help='Generate a bash script that replaces copies of the original by symbolic links to the original.')

parser.add_argument('--flat', '-f',
                    action='store_const',
                    dest='recursive',
                    const=False, default=True,
                    help='Do not step down into subdirectories')

parser.add_argument('--verbose', '-v',
                    action='store_const',
                    default=False, const=True,)

parser.add_argument('--notoriginal', '-n',
                    action='append',
                    type=str,
                    default=[],
                    help='assume that files matching TEXT are copies')

parser.add_argument('--include', '-i',
                    action='append',
                    type=str,
                    default=[],
                    help='consider only files matching TEXT (in all directories)')

parser.add_argument('--exclude', '-x',
                    action='append',
                    type=str,
                    default=[],
                    help='exclude files matching TEXT')

parser.add_argument('--min-size', '-m',
                    type=int,
                    default=1,
                    help='ignore files smaller than MIN_SIZE')


# Thus, -x .git behaves similarly to -n */.git

args = parser.parse_args()

filesBySize = {}

def files_by_size(path, min_size=100, follow_links=False, recursive=True, extend=None,
                  exclude_filter_fn=(lambda x: True), no_include_filter_fn=(lambda x: False)):
    if extend is None:
        extend = {}
    if args.verbose:
        print('Stepping into directory "%s"....' % path, file=sys.stderr)
    files = filter(exclude_filter_fn, os.listdir(path))
    for f in files:
        f=os.path.join(path, f)
        try:
            if recursive and os.path.isdir(f):
                files_by_size(f, min_size, follow_links, True, extend,
                              exclude_filter_fn, no_include_filter_fn)
            if no_include_filter_fn(f):
                continue
            if not follow_links and os.path.islink(f):
                continue
            if not os.path.isfile(f):
                continue
            size = os.stat(f)[stat.ST_SIZE]
            if size < min_size:
                continue
            try:
                extend[size].append(f)
            except KeyError:
                extend[size] = [f]
        except (IOError, OSError):
            continue
    return extend

def multi_match_filter_fn(match=args.exclude):
    return lambda x: not any([fnmatch.fnmatchcase(x, exclude) for exclude in match])

def notoriginal_penalty(match=args.notoriginal):
    return lambda x: sum(fnmatch.fnmatchcase(x, exclude) for exclude in match)    

def relpath_unless_via_root(path, start=".", roots=["/"]):
    relpath = os.path.relpath(path, start)
    for root in roots:
        if os.path.relpath(path, root) in relpath:
            return os.path.abspath(path)
    return relpath

for x in args.paths:
    print('Scanning directory "%s"....' % x, file=sys.stderr)
    files_by_size(x,
                  min_size=args.min_size,
                  recursive=args.recursive,
                  extend=filesBySize,
                  exclude_filter_fn=multi_match_filter_fn(),
                  no_include_filter_fn=multi_match_filter_fn(args.include))

print('Finding potential dupes...', file=sys.stderr)
potentialDupes = []
potentialCount = 0
trueType = type(True)
sizes = list(filesBySize.keys())
sizes.sort(reverse=True)
for k in sizes:
    inFiles = filesBySize[k]
    hashes = {}
    if len(inFiles) is 1: continue
    if args.verbose:
        print('Testing %d files of size %d...' % (len(inFiles), k), file=sys.stderr)
    for fileName in inFiles:
        if not os.path.isfile(fileName):
            continue
        try:
            with open(fileName, 'rb') as aFile:
                hasher = hashlib.sha256(aFile.read(1024))
                hashValue = hasher.digest()
                if hashValue in hashes:
                    hashes[hashValue].append(fileName)
                else:
                    hashes[hashValue] = [fileName]
        except PermissionError:
            continue
    for outFiles in list(hashes.values()):
        if len(outFiles)>1:
            potentialDupes.append(outFiles)
            potentialCount = potentialCount + len(outFiles)
del filesBySize

print('Found %d sets of potential dupes...' % potentialCount, file=sys.stderr)
print('Scanning for real dupes...', file=sys.stderr)

dupes = []
for aSet in potentialDupes:
    hashes = {}
    for fileName in aSet:
        if args.verbose:
            print('Scanning file "%s"...' % fileName, file=sys.stderr)
        try:
            with open(fileName, 'rb') as aFile:
                hasher = hashlib.sha256()
                while True:
                    r = aFile.read(4096)
                    if not len(r):
                        break
                    hasher.update(r)
                hashValue = hasher.digest()
                if hashValue in hashes:
                    hashes[hashValue].append(fileName)
                else:
                    hashes[hashValue] = [fileName]
        except (IOError, OSError, PermissionError):
            continue
    for outFiles in list(hashes.values()):
        if len(outFiles)>1:
            if args.long is not None:
                outFiles.sort(key=len, reverse=args.long)
            dupes.append(sorted(outFiles,
                                key=notoriginal_penalty(args.notoriginal)))

for d in dupes:
    if args.script:
        original = d[0]
        try:
            print('# Assuming {:s} is the original.'.format(repr(original)))
            print('ORIGINAL={:s}'.format(shlex.quote(original)))
            print('for FILE in {:s}'.format(" ".join(map(shlex.quote, d))))
        except UnicodeEncodeError:
            print('# Problem with encoding of file set {:s}'.format(repr(original)))
            continue
        print('  do')
        print('  if [ "$FILE" != "$ORIGINAL" ]')
        print('  then')
        print('    rm "$FILE"')
        print('  fi')
        print('done')
        for f in d[1:]:
            print('# ln -s {:s} {:s}'.format(
                shlex.quote(
                    relpath_unless_via_root(
                        original,
                        os.path.dirname(f),
                        args.paths)),
                f))
        print()
    else:
        try:
            print("\n".join(d), end="\n====\n")
        except UnicodeEncodeError:
            print("#UnicodeEncodeError:")
            print("\n".join([repr(file) for file in d]), end="\n====\n")

