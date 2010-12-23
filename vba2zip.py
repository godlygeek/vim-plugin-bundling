#!/usr/bin/env python
"""A simple Vimball converter.

Note: Conversions like dir2dir and vba2vba would be good for unit testing.

TODO: Rewrite the input to just detect headers.
"""

from zipfile import ZipFile,ZipInfo
import time
import os
import sys
import gzip

class ArchiveMember(object):
  """
  Represent the information for a member of an archive.

  The following attributes will be supported:
  name		Name of the member (must be provided)
  data		Contents of the member (default empty)
  mtime		Time of last modification (default current time)
  perm		Unix-style permissions for the member (default 0666)
  isdir		Checks the permissions to see if they have the directory bit
  """

  def __init__(self, name):
    """
    Construct an archive member with the given name.

    Note: Not thread safe, because of setting/resetting umask!
    """
    umask = os.umask(0)
    os.umask(umask)
    self.name = name
    self.data = None
    self.perm = 0666 & ~umask
    self.mtime = time.localtime(time.time())[:6]

  def __getattribute__(self, name):
    if name == "isdir":
      return object.__getattribute__(self, 'perm') & 040000 == 040000
    else:
      return object.__getattribute__(self, name)

  def __setattr__(self, name, value):
    if name == "isdir":
      # Toggle directory and executable bits appropriately
      if value:
        self.__dict__["perm"] = self.__dict__["perm"] | 040111
      else:
        self.__dict__["perm"] = self.__dict__["perm"] & ~040111
    else:
      self.__dict__[name] = value

class ArchiveInterface(object):
  """
  Provide a common interface for interacting with readers and writers.
  """
  ext = None

  @classmethod
  def id(cls):
    return cls.ext

class ArchiveReader(ArchiveInterface):
  """
  Provide an interface for iterating over the members of an archive.
  """
  def __init__(self, archivepath):
    """
    Prepare to read the members of the archive given by archivepath.
    """
    if self.__class__ is ArchiveReader:
      raise NotImplementedError

  def __iter__(self):
    """
    Generate an iterator over the members of this archive as ArchiveMembers.
    """
    raise NotImplementedError

class ArchiveWriter(ArchiveInterface):
  """
  Provide an interface for adding members to an archive.
  """
  def __init__(self, archivepath):
    """
    Prepare to write to the archive given by archivepath.
    """
    if self.__class__ is ArchiveWriter:
      raise NotImplementedError

  def add(self, member):
    """
    Add a new member to the archive
    """
    raise NotImplementedError

class VimballReader(ArchiveReader):
  """ Provide an ArchiveReader for Vimball archives. """
  ext = 'vba'

  def __init__(self, archivepath):
    self.archive = open(archivepath, "r")

  def __iter__(self):
    filemarker = "\t[[[1\n"
    files = {}
    dirs = []
    dirs_set = {}

    line = None
    while line != "" and line != "finish\n":
      line = self.archive.readline()

    while True:
      file = self.archive.readline()

      if file == '':
        break # All files handled

      if not file.endswith(filemarker):
        raise "FIXME Bad Vimball"
      file = file[:-len(filemarker)]

      numlines = self.archive.readline().rstrip("\n")
      if not numlines.isdigit():
        raise "FIXME Bad Vimball!"

      lines = ""
      for i in range(int(numlines)):
        line = self.archive.readline()
        if line == '':
          raise "FIXME Truncated Vimball"
        lines += line

      files[file] = lines

      dirs_set[os.path.dirname(file)] = None
    dirs = dirs_set.keys()
    dirs.sort()

    for dir in dirs:
      member = ArchiveMember(dir)
      member.isdir = True
      yield member

    for (file, data) in files.items():
      member = ArchiveMember(file)
      member.data = data
      yield member

class GzippedVimballReader(VimballReader):
  """ Extend the VimballReader to work on gzipped Vimballs. """
  ext = 'vba.gz'

  def __init__(self, archivepath):
    self.archive = gzip.open(archivepath, 'r')

class VimballWriter(ArchiveWriter):
  ext = 'vba'

  def __init__(self, archivepath):
    self.archive = open(archivepath, 'w')
    self.header_written = False

  def add(self, member):
    if not self.header_written:
      self.archive.write("\" Vimball Archiver by Charles E. Campbell, Jr., Ph.D.\n"
                         "UseVimball\n"
                         "finish\n")
      self.header_written = True
    if member.isdir:
      return # Can't create directories with a vimball
    self.archive.write(member.name + "\t[[[1\n")
    if member.data.endswith("\n"):
      data = member.data
    else:
      data = member.data + "\n"
    self.archive.write(str(data.count("\n")) + "\n")
    self.archive.write(data)

class GzippedVimballWriter(VimballWriter):
  ext = 'vba.gz'

  def __init__(self, archivepath):
    self.archive = gzip.open(archivepath, 'w')
    self.header_written = False

class ZipWriter(ArchiveWriter):
  """ Provide an ArchiveWriter for zip archives. """
  ext = 'zip'

  def __init__(self, archivepath):
    self.archive = ZipFile(archivepath, "w")

  def add(self, member):
    if (member.isdir):
      return # FIXME Should be able to add empty directories
    info = ZipInfo(member.name)
    info.date_time = member.mtime
    info.external_attr = member.perm << 16L
    self.archive.writestr(info, member.data)

class DirectoryReader(ArchiveReader):
  """ Provide an ArchiveReader for filesystem directories. """
  id  = classmethod(lambda cls : 'dir')

  def __init__(self, archivepath):
    self.archivepath = os.path.normpath(archivepath)
    self.filenames = []
    self.dirnames = []

    for tuple in os.walk(self.archivepath):
      dir = tuple[0][len(self.archivepath)+1:]
      for dirname in tuple[1]:
        self.dirnames.append(os.path.join(dir, dirname))
      for filename in tuple[2]:
        self.filenames.append(os.path.join(dir, filename))

  def __iter__(self):
    for directory in self.dirnames:
      name = os.path.join(self.archivepath, directory)
      statbuf = os.stat(name)

      member = ArchiveMember(directory)
      member.perm = statbuf.st_mode
      member.mtime = statbuf.st_mtime
      yield member
    for filename in self.filenames:
      name = os.path.join(self.archivepath, filename)
      statbuf = os.stat(name)

      member = ArchiveMember(filename)
      member.perm = statbuf.st_mode
      member.mtime = statbuf.st_mtime

      file = open(os.path.join(self.archivepath, filename), "rb")
      member.data = file.read()
      yield member

class DirectoryWriter(ArchiveWriter):
  """ Provide an ArchiveWriter for filesystem directories. """

  def __init__(self, archivepath):
    self.archivepath = os.path.normpath(archivepath)

    if os.path.exists(self.archivepath):
      raise IOError, "Directory exists!"

    os.mkdir(self.archivepath)

  def add(self, member):
    path = os.path.join(self.archivepath, member.name)
    if (member.isdir):
      os.mkdir(path, member.perm)
    else:
      file = open(path, "wb")
      file.write(member.data)
      file.close()

def archiveConvert(read_mgr, write_mgr):
  for member in read_mgr:
    write_mgr.add(member)

READERS = dict([
  (x.id(), x) for x in (
    DirectoryReader,
    VimballReader,
    GzippedVimballReader
  )])

WRITERS = dict([
  (x.id(), x) for x in (
    DirectoryWriter,
    VimballWriter,
    GzippedVimballWriter,
    ZipWriter
  )])

if __name__ == '__main__':
  valid_modes = dict([
    ('%s2%s' % (x, y), (READERS[x], WRITERS[y]))
    for x in READERS for y in WRITERS
    if x != y
  ])

  def _mode_default(parser):
    # Make it more HFS+/FAT/NTFS-friendly with .lower()
    mode = parser.get_prog_name().lower()
    return mode[:-3] if mode.endswith(".py") else mode

  from optparse import OptionParser
  parser = OptionParser(description="A simple Vimball converter",
    usage='%prog [options] <source file> <destination file>',
    epilog="Conversion modes can also be specified by naming this script")
  parser.add_option('-m', '--mode', action="store", dest="mode",
    type="choice", choices=valid_modes.keys(), default=_mode_default(parser),
    help="Specify a non-default conversion (eg. dir2vba)")
  parser.add_option('--list_mode', action="store_true", dest="list_modes",
    default=False, help="List supported conversion modes")

  opts, args = parser.parse_args()

  if opts.list_modes:
    print '\n'.join(valid_modes) + '\n'
    sys.exit()

  if not 0 < len(args) < 3:
    parser.print_help()
    sys.exit(1)

  if len(args) == 1:
    args.append(os.path.basename(args[0]))

  params = [cls(arg) for cls, arg in zip(valid_modes[opts.mode], args)]

  archiveConvert(*params)
