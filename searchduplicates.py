#!/usr/bin/env python2
#! -*- encoding: utf-8 -*-

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
import md5
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

parser.add_argument('--exclude', '-x',
                    action='append',
                    type=str,
                    default=[],
                    help='exclude files matching TEXT')

# TODO: -x and -n behave differently:
# -x cares only for the 'basename', -n for the full name.
# Thus, -x .git behaves similarly to -n */.git

args = parser.parse_args()

filesBySize = {}

def files_by_size(path, filter_fn=(lambda x: True), min_size=100, follow_links=False, recursive=True, extend={}):
    if args.verbose:
        print >>sys.stderr, 'Stepping into directory "%s"....' % path
    files = filter(filter_fn, os.listdir(path))
    for f in files:
        f=os.path.join(path, f)
        try:
            if not follow_links and os.path.islink(f):
                continue
            if recursive and os.path.isdir(f):
                files_by_size(f, filter_fn, min_size, follow_links, True, extend)
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

for x in args.paths:
    print >>sys.stderr, 'Scanning directory "%s"....' % x
    files_by_size(x,
                  filter_fn=multi_match_filter_fn(),
                  recursive=args.recursive,
                  extend=filesBySize)

print >>sys.stderr, 'Finding potential dupes...'
potentialDupes = []
potentialCount = 0
trueType = type(True)
sizes = filesBySize.keys()
sizes.sort(reverse=True)
for k in sizes:
    inFiles = filesBySize[k]
    outFiles = []
    hashes = {}
    if len(inFiles) is 1: continue
    if args.verbose:
        print >>sys.stderr, 'Testing %d files of size %d...' % (len(inFiles), k)
    for fileName in inFiles:
        try:
            if not os.path.isfile(fileName):
                continue
            aFile = file(fileName, 'r')
            hasher = md5.new(aFile.read(1024))
            hashValue = hasher.digest()
            if hashes.has_key(hashValue):
                x = hashes[hashValue]
                if type(x) is not trueType:
                    outFiles.append(hashes[hashValue])
                    hashes[hashValue] = True
                outFiles.append(fileName)
            else:
                hashes[hashValue] = fileName
            aFile.close()
        except IOError:
            continue
    if len(outFiles):
        potentialDupes.append(outFiles)
        potentialCount = potentialCount + len(outFiles)
del filesBySize

print >>sys.stderr, 'Found %d sets of potential dupes...' % potentialCount
print >>sys.stderr, 'Scanning for real dupes...'

dupes = []
for aSet in potentialDupes:
    outFiles = []
    hashes = {}
    for fileName in aSet:
        try:
            if args.verbose:
                print >>sys.stderr, 'Scanning file "%s"...' % fileName
            aFile = file(fileName, 'r')
            hasher = md5.new()
            while True:
                r = aFile.read(4096)
                if not len(r):
                    break
                hasher.update(r)
            aFile.close()
            hashValue = hasher.digest()
            if hashes.has_key(hashValue):
                if not len(outFiles):
                    outFiles.append(hashes[hashValue])
                outFiles.append(fileName)
            else:
                hashes[hashValue] = fileName
        except IOError:
            continue
    if len(outFiles):
        if args.long is None:
            dupes.append(sorted(outFiles,
                key=multi_match_filter_fn(args.notoriginal), reverse=True))
        else:
            dupes.append(sorted(sorted(outFiles, key=len, reverse=args.long),
                key=multi_match_filter_fn(args.notoriginal), reverse=True))

for d in dupes:
    if args.script:
        original = d[0]
        print '# Assuming %s is the original.' % original
        for f in d[1:]:
            # The following line still has problems with literal “'” in file names.
            print "rm '%s' && ln -s '%s' '%s'" % (f, os.path.relpath(original, os.path.dirname(f)), f)
    else:
        print "===="
        print "\n".join(d)
