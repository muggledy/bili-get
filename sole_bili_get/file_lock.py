import platform

if platform.system() == 'Windows':
    import msvcrt
else:
    import fcntl

__all__ = ['LockedFile',]

class LockedFile: #copy from https://github.com/google/gtest-parallel/blob/master/gtest_parallel.py
    def __init__(self, filename, mode):
        self._filename = filename
        self._mode = mode
        self._fo = None

    def __enter__(self):
        self._fo = open(self._filename, self._mode)

        # Regardless of opening mode we always seek to the beginning of file.
        # This simplifies code working with LockedFile and also ensures that
        # we lock (and unlock below) always the same region in file on win32.
        # See https://docs.python.org/3/library/msvcrt.html
        self._fo.seek(0)

        try:
            if platform.system() == 'Windows':
                # We are locking here fixed location in file to use it as
                # an exclusive lock on entire file.
                msvcrt.locking(self._fo.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(self._fo.fileno(), fcntl.LOCK_EX)
        except IOError:
            self._fo.close()
            raise

        return self._fo

    def __exit__(self, exc_type, exc_value, traceback):
        # Flush any buffered data to disk. This is needed to prevent race
        # condition which happens from the moment of releasing file lock
        # till closing the file.
        self._fo.flush()

        try:
            if platform.system() == 'Windows':
                self._fo.seek(0)
                msvcrt.locking(self._fo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._fo.fileno(), fcntl.LOCK_UN)
        finally:
            self._fo.close()

        return exc_value is None

if __name__ == '__main__':
    pass