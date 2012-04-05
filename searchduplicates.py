#! /usr/bin/python

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

parser.add_argument('--flat', '-f',
                    action='store_const',
                    dest='recursive',
                    const=False, default=True,
                    help='Do not step down into subdirectories')

parser.add_argument('--verbose', '-v',
                    action='store_const',
                    const=False, default=True,)

parser.add_argument('--exclude', '-x',
                    action='append',
                    type=str,
                    help='exclued files matching TEXT')

args = parser.parse_args()


if args.exclude is None:
    args.exclude = []

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
            if os.path.isdir(f):
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

def exclude_filter_fn(x):
    return not any([fnmatch.fnmatchcase(x, exclude) for exclude in args.exclude])
    
for x in args.paths:
    print >>sys.stderr, 'Scanning directory "%s"....' % x
    files_by_size(x,
                  filter_fn=exclude_filter_fn,
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
        dupes.append(sorted(outFiles, key=len, reverse=True))

i = 0
for d in dupes:
    original = d[0]
    print '# Original is %s' % original
    for f in d[1:]:
        i = i + 1
        print 'rm %s && ln -s %s %s' % (f, os.path.relpath(original, f), f)
