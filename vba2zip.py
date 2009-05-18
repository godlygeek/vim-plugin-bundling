#!/usr/bin/env python

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

class ArchiveReader(object):
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

class ArchiveWriter(object):
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
  def __init__(self, archivepath):
    self.archive = gzip.open(archivepath, 'r')

class VimballWriter(ArchiveWriter):
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
  def __init__(self, archivepath):
    self.archive = gzip.open(archivepath, 'w')
    self.header_written = False

class ZipWriter(ArchiveWriter):
  """ Provide an ArchiveWriter for zip archives. """

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

def usage():
  print "usage" # FIXME
  sys.exit()

if __name__ == '__main__':
  argv = sys.argv

  if len(argv) != 3 and len(argv) != 4:
    usage()

  if len(argv) == 3:
    name = argv.pop(0)
    if name.endswith(".py"):
      name = name[:-3]
    name = os.path.basename(name)
  else:
    del argv[0]
    name = argv.pop(0)
    if name.startswith("--"):
      name = name[2:]

  split = name.partition("2")

  if split[1] != "2":
    usage()

  reader = None
  writer = None

  if split[0] == "vba":
    reader = VimballReader(argv[0])
  elif split[0] == "vba.gz":
    reader = GzippedVimballReader(argv[0])
  elif split[0] == "dir":
    reader = DirectoryReader(argv[0])
  else:
    raise NotImplementedError("No such reader: " + split[0])

  if split[2] == "zip":
    writer = ZipWriter(argv[1])
  elif split[2] == "dir":
    writer = DirectoryWriter(argv[1])
  elif split[2] == "vba":
    writer = VimballWriter(argv[1])
  elif split[2] == "vba.gz":
    writer = GzippedVimballWriter(argv[1])
  else:
    raise NotImplementedError("No such writer: " + split[2])

  archiveConvert(reader, writer)
