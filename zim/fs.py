# -*- coding: utf-8 -*-

# Copyright 2008 Jaap Karssenberg <pardus@cpan.org>

'''Module with basic filesystem objects.

Used as a base library for most other zim modules.
'''

# TODO - use weakref ?

# From the python doc: If you're starting with a Python file object f, first
# do f.flush(), and then do os.fsync(f.fileno()), to ensure that all internal
# buffers associated with f are written to disk. Availability: Unix, and
# Windows starting in 2.2.3.
#
# (Remember the ext4 issue with truncated files in case of failure within
# 60s after write. This way of working should prevent that kind of issue.)

import os
import shutil
import errno
import codecs
import logging
from StringIO import StringIO

__all__ = ['Dir', 'File']

logger = logging.getLogger('zim.fs')


def get_tmpdir():
	import tempfile
	return tempfile.gettempdir()
	# TODO make path specific for user / process ...


class PathLookupError(Exception):
	'''FIXME'''


class OverWriteError(Exception):
	'''FIXME'''


class UnixPath(object):
	'''Parent class for Dir and File objects'''

	def __init__(self, path):
		# TODO keep link to parent dir if first arg is Dir object
		#      but only if there is no '../' after that arg
		if isinstance(path, (list, tuple)):
			path = map(str, path)
				# Any path objects in list will also be flattened
			path = os.path.sep.join(path)
				# os.path.join is too intelligent for it's own good
				# just join with the path seperator..
		elif isinstance(path, Path):
			path = path.path

		if path.startswith('file:/'):
			path = self._parse_uri(path)
		elif path.startswith('~'):
			path = os.path.expanduser(path)

		self.path = os.path.abspath(path)

	@staticmethod
	def _parse_uri(uri):
		# Spec is file:/// or file://host/
		# But file:/ is sometimes used by non-compliant apps
		# Windows uses file:///C:/ which is compliant
		if uri.startswith('file:///'): return uri[7:]
		elif uri.startswith('file://localhost/'): return uri[16:]
		elif uri.startswith('file://'): assert False, 'Can not handle non-local file uris'
		elif uri.startswith('file:/'): return uri[5:]
		else: assert False, 'Not a file uri: %s' % uri

	def __iter__(self):
		parts = self.split()
		for i in range(1, len(parts)+1):
			path = os.path.join(*parts[0:i])
			yield path

	def __str__(self):
		return self.path

	def __repr__(self):
		return '<%s: %s>' % (self.__class__.__name__, self.path)

	def __add__(self, other):
		'''Concatonates paths, only creates objects of the same class. See
		Dir.file() and Dir.subdir() instead to create other objects.
		'''
		return self.__class__((self, other))

	def __eq__(self, other):
		return self.path == other.path

	def __ne__(self, other):
		return not self.__eq__(other)

	@property
	def basename(self):
		'''Basename property'''
		return os.path.basename(self.path)

	@property
	def uri(self):
		'''File uri property'''
		return 'file://'+self.path

	@property
	def dir(self):
		'''FIXME'''
		path = os.path.dirname(self.path)
		# TODO make this persistent - weakref ?
		return Dir(path)

	def exists(self):
		'''Abstract method'''
		raise NotImplementedError

	def iswritable(self):
		if self.exists():
			statinfo = os.stat(self.path)
			return bool(statinfo.st_mode & 0200)
		else:
			return self.dir.iswritable() # recurs
		
	def mtime(self):
		stat_result = os.stat(self.path)
		return stat_result.st_mtime

	def split(self):
		'''FIXME'''
		drive, path = os.path.splitdrive(self.path)
		parts = path.replace('\\', '/').strip('/').split('/')
		parts[0] = drive + os.path.sep + parts[0]
		return parts

	def rename(self, newpath):
		logger.info('Rename %s to %s', self, newpath)
		os.renames(self.path, newpath.path)

	def ischild(self, parent):
		return self.path.startswith(parent.path + os.path.sep)

	def get_mimetype(self):
		import xdg.Mime
		return xdg.Mime.get_type(self.path, name_pri=80)

class WindowsPath(UnixPath):

    @property
    def uri(self):
        '''File uri property with win32 logic'''
        # win32 paths do not start with '/', so add another one
        return 'file:///'+self.canonpath

    @property
    def canonpath(self):
        path = self.path.replace('\\', '/')
        return path


# Determine which base class to use for classes below
if os.name == 'posix':
	Path = UnixPath
elif os.name == 'nt':
	Path = WindowsPath
else:
	import logging
	logger = logging.getLogger('zim')
	logger.critical('os name "%s" unknown, falling back to posix', os.name)
	Path = UnixPath


class Dir(Path):
	'''OO wrapper for directories'''

	def __eq__(self, other):
		if isinstance(other, Dir):
			return self.path == other.path
		else:
			return False

	def exists(self):
		'''Returns True if the dir exists and is actually a dir'''
		return os.path.isdir(self.path)

	def list(self):
		'''FIXME'''
		# TODO check notes on handling encodings in os.listdir
		if self.exists():
			files = [f.decode('utf-8')
				for f in os.listdir(self.path) if not f.startswith('.')]
			files.sort()
			return files
		else:
			return []

	def touch(self):
		'''FIXME'''
		try:
			os.makedirs(self.path)
		except OSError, e:
			if e.errno != errno.EEXIST:
				raise

	def remove(self):
		'''Remove this dir, fails if dir is non-empty.'''
		logger.info('Remove dir: %s', self)
		os.rmdir(self.path)

	def cleanup(self):
		'''Removes this dir and any empty parent dirs.

		Ignores if dir does not exist. Fails silently if dir is not empty.
		Returns boolean for success (so False means dir still exists).
		'''
		if not self.exists():
			return True

		try:
			os.removedirs(self.path)
		except OSError:
			return False # probably dir not empty
		else:
			return True

	def remove_children(self):
		'''Remove everything below this dir.

		WARNING: This is quite powerful and recursive, so make sure to double
		check the dir is actually what you think it is before calling this.
		'''
		assert self.path and self.path != '/' # FIXME more checks here ?
		logger.info('Remove file tree: %s', self)
		for root, dirs, files in os.walk(self.path, topdown=False):
			for name in files:
				os.remove(os.path.join(root, name))
			for name in dirs:
				os.rmdir(os.path.join(root, name))


	def file(self, path):
		'''FIXME'''
		assert isinstance(path, (File, basestring, list, tuple))
		if isinstance(path, File):
			file = path
		elif isinstance(path, basestring):
			file = File((self.path, path))
		else:
			file = File((self.path,) + tuple(path))
		if not file.path.startswith(self.path):
			raise PathLookupError, '%s is not below %s' % (file, self)
		# TODO set parent dir on file
		return file

	def subdir(self, path):
		'''FIXME'''
		assert isinstance(path, (File, basestring, list, tuple))
		if isinstance(path, Dir):
			dir = path
		elif isinstance(path, basestring):
			dir = Dir((self.path, path))
		else:
			dir = Dir((self.path,) + tuple(path))
		if not dir.path.startswith(self.path):
			raise PathLookupError, '%s is not below %s' % (dir, self)
		# TODO set parent dir on file
		return dir


class File(Path):
	'''OO wrapper for files. Implements more complex logic than
	the default python file objects. On writing we first write to a
	temporary files, then flush and sync and finally replace the file we
	intended to write with the temporary file. This makes it much more
	difficult to loose file contents when something goes wrong during
	the writing.

	When 'checkoverwrite' this class checks mtime to prevent overwriting a
	file that was changed on disk, if mtime fails MD5 sums are used to verify
	before raising an exception. However this check only works when using
	read(), readlines(), write() or writelines(), but not when calling open()
	directly. Unfortunately this logic is not atomic, so your mileage may vary.
	'''

	def __init__(self, path, checkoverwrite=False):
		Path.__init__(self, path)
		self.checkoverwrite = checkoverwrite
		self._mtime = None

	def __eq__(self, other):
		if isinstance(other, File):
			return self.path == other.path
		else:
			return False

	def exists(self):
		'''Returns True if the file exists and is actually a file'''
		return os.path.isfile(self.path)

	def open(self, mode='r', encoding='utf-8'):
		'''Returns an io object for reading or writing.
		Opening a non-exisiting file for writing will cause the whole path
		to this file to be created on the fly.
		To open the raw file specify 'encoding=None'.
		'''
		assert mode in ('r', 'w')
		if mode == 'w':
			if not self.iswritable():
				raise OverWriteError, 'File is not writable'
			elif not self.exists():
				self.dir.touch()
			else:
				pass # exists and writable

		if encoding:
			mode += 'b'

		if mode in ('w', 'wb'):
			tmp = self.path + '.zim.new~'
			fh = FileHandle(tmp, mode=mode, on_close=self._on_write)
		else:
			fh = open(self.path, mode=mode)

		if encoding:
			# code copied from codecs.open() to wrap our FileHandle objects
			info = codecs.lookup(encoding)
			srw = codecs.StreamReaderWriter(
				fh, info.streamreader, info.streamwriter, 'strict')
			srw.encoding = encoding
			return srw
		else:
			return fh

	def _on_write(self):
		# flush and sync are already done before close()
		tmp = self.path + '.zim.new~'
		assert os.path.isfile(tmp)
		if isinstance(self, WindowsPath):
			# On Windows, if dst already exists, OSError will be raised
			# and no atomic operation to rename the file :(
			if os.path.isfile(self.path):
				back = self.path + '~'
				if os.path.isfile(back):
					os.remove(back)
				os.rename(self.path, back)
				os.rename(tmp, self.path)
				os.remove(back)
			else:
				os.rename(tmp, self.path)
		else:
			# On UNix, dst already exists it is replaced in an atomic operation
			os.rename(tmp, self.path)
		logger.debug('Wrote %s', self)

	def read(self, encoding='utf-8'):
		if not self.exists():
			return ''
		else:
			file = self.open('r', encoding)
			content = file.read()
			self._checkoverwrite(content)
			return content

	def readlines(self):
		if not self.exists():
			return []
		else:
			file = self.open('r')
			content = file.readlines()
			self._checkoverwrite(content)
			return content

	def write(self, text):
		self._assertoverwrite()
		file = self.open('w')
		file.write(text)
		file.close()
		self._checkoverwrite(text)

	def writelines(self, lines):
		self._assertoverwrite()
		file = self.open('w')
		file.writelines(lines)
		file.close()
		self._checkoverwrite(lines)

	def _checkoverwrite(self, content):
		if self.checkoverwrite:
			self._mtime = self.mtime()
			self._content = content

	def _assertoverwrite(self):
		# do not prohibit writing without reading first

		def md5(content):
			import hashlib
			m = hashlib.md5()
			if isinstance(content, basestring):
				m.update(content)
			else:
				for l in content:
					m.update(l)
			return m.digest()

		if self._mtime and self._mtime != self.mtime():
			logger.warn('mtime check failed for %s, trying md5', self.path)
			if md5(self._content) != md5(self.open('r').read()):
				raise OverWriteError, 'File changed on disk: %s' % self.path

	def touch(self):
		'''FIXME'''
		if self.exists():
			return
		else:
			io = self.open('w')
			io.write('')
			io.close()

	def remove(self):
		'''Remove this file and any related temporary files we made.
		Ignores if page did not exist in the first place.
		'''
		logger.info('Remove file: %s', self)
		if os.path.isfile(self.path):
			os.remove(self.path)

		tmp = self.path + '.zim.new~'
		if os.path.isfile(tmp):
			os.remove(tmp)

	def cleanup(self):
		'''Remove this file and deletes any empty parent directories.'''
		self.remove()
		self.dir.cleanup()

	def copyto(self, dest):
		'''Copy this file to 'dest'. 'dest can be either a file or a dir'''
		assert isinstance(dest, (File, Dir))
		logger.info('Copy %s to %s', self, dest)
		if isinstance(dest, Dir):
			dest.touch()
		else:
			dest.dir.touch()
		shutil.copy(self.path, dest.path)


class TmpFile(File):

	def __init__(self, name, unique=True, checkoverwrite=False):
		'''Create a file object under the tmp dir.
		If 'unique' is True a random key will be inserted in the name
		before the file extension.
		'''
		if unique:
			print 'TODO: support unique tmp files'
		path = (get_tmpdir(), name)
		File.__init__(self, path, checkoverwrite)


class FileHandle(file):
	'''Subclass of builtin file type that uses flush and fsync on close
	and supports a callback'''

	def __init__(self, path, on_close=None, **opts):
		file.__init__(self, path, **opts)
		self.on_close = on_close

	def close(self):
		self.flush()
		os.fsync(self.fileno())
		file.close(self)
		if not self.on_close is None:
			self.on_close()