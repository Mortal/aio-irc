import sys
import asyncio
import contextlib


class DumbLine(bytes):
    def show(self):
        pass

    def hide(self):
        pass


class AsyncReadlinesDumb:
    def __init__(self, loop):
        self.loop = loop
        self.fp = sys.stdin.buffer
        self.buf = b''
        self.eof = object()
        self.queue = asyncio.Queue()

    def close(self):
        pass

    def on_readable(self):
        s = self.fp.read1(4096)
        if s == b'':
            self.queue.put_nowait(self.eof)
            self.loop.remove_reader(self.fp)
        else:
            self.buf += s
            linedata, nl, self.buf = self.buf.rpartition(b'\n')
            if nl:
                for line in linedata.split(b'\n'):
                    self.queue.put_nowait(line)

    def get_buffer(self):
        raise NotImplementedError()

    def set_buffer(self, s):
        raise NotImplementedError()

    def __aiter__(self):
        self.loop.add_reader(self.fp, self.on_readable)
        return self

    async def __anext__(self):
        try:
            o = await self.queue.get()
        except asyncio.CancelledError:
            raise StopAsyncIteration()
        if o is self.eof:
            raise StopAsyncIteration()
        return DumbLine(o)


class TermiosLine(bytes):
    def show(self):
        sys.stdout.buffer.write(b'\n')
        sys.stdout.buffer.flush()

    def hide(self):
        sys.stdout.buffer.write(b'\r\x1B[K')
        sys.stdout.buffer.flush()


class AsyncReadlinesTermios:
    def __init__(self, loop):
        self.loop = loop
        self.stack = None

        self.fp = sys.stdin.buffer
        self.buf = b''
        self.eof = object()
        self.queue = asyncio.Queue()

    def close(self):
        if self.stack:
            self.stack.close()
            self.stack = None

    def __del__(self):
        self.close()

    def __aiter__(self):
        self.loop.add_reader(self.fp, self.on_readable)
        with contextlib.ExitStack() as stack:
            stack.callback(lambda: self.loop.remove_reader(self.fp))
            stack.enter_context(self.setcbreak(0))
            stack.enter_context(self.wrap_write(sys.stdout))
            stack.enter_context(self.wrap_write(sys.stderr))
            self.stack = stack.pop_all()
        return self

    @contextlib.contextmanager
    def setcbreak(self, fd):
        old = termios.tcgetattr(0)
        new = termios.tcgetattr(0)
        new[tty.LFLAG] = new[tty.LFLAG] & ~(termios.ECHO | termios.ICANON)
        new[tty.CC][termios.VMIN] = 1
        new[tty.CC][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, new)

        try:
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    @contextlib.contextmanager
    def wrap_write(self, fp):
        old_write = fp.write
        write_buf = ''

        def write(s, *args, **kwargs):
            nonlocal write_buf
            write_buf += s
            lines, nl, write_buf = write_buf.rpartition('\n')
            if nl:
                if self.buf:
                    r = fp.buffer.write(
                        b'\r\x1B[K%s%s' % ((lines+nl).encode(), self.buf))
                    fp.buffer.flush()
                else:
                    r = old_write(lines+nl, *args, **kwargs)
                    fp.flush()
                return r

        fp.write = write
        try:
            yield
        finally:
            fp.write = old_write
            if write_buf:
                fp.write(write_buf)

    def get_buffer(self):
        return self.buf.decode('utf8', errors='replace')

    def set_buffer(self, s):
        if isinstance(s, str):
            s = s.encode('utf8')
        if not isinstance(s, bytes):
            raise TypeError(type(s))
        self.buf = s
        sys.stdout.buffer.write(b'\r\x1B[K' + self.buf)
        sys.stdout.buffer.flush()

    def on_readable(self):
        s = self.fp.read1(1)
        if s == b'' or (s == b'\x04' and not self.buf):  # CTRL-D
            self.queue.put_nowait(self.eof)
        elif s in (b'\x08', b'\x7F'):  # CTRL-H
            if self.buf:
                self.buf = self.buf[:-1]
                sys.stdout.buffer.write(b'\x08\x1B[K')
                sys.stdout.buffer.flush()
        elif s == b'\x15':  # CTRL-U
            if self.buf:
                self.buf = b''
                sys.stdout.buffer.write(b'\r\x1B[K')
                sys.stdout.buffer.flush()
        elif s == b'\x17':  # CTRL-W
            if self.buf:
                self.buf = self.buf.rstrip()
                self.buf = self.buf[:self.buf.rfind(b' ')+1]
                sys.stdout.buffer.write(b'\r\x1B[K' + self.buf)
                sys.stdout.buffer.flush()
        elif s == b'\n':
            self.queue.put_nowait(self.buf)
            self.buf = b''
        else:
            if s < b' ':
                s = b'^' + bytes([s[0] + 64])
            sys.stdout.buffer.write(s)
            sys.stdout.buffer.flush()
            self.buf += s

    async def __anext__(self):
        try:
            o = await self.queue.get()
        except asyncio.CancelledError:
            o = self.eof
        if o is self.eof:
            if self.stack:
                self.stack.close()
                self.stack = None
            raise StopAsyncIteration()
        return TermiosLine(o)


try:
    import termios  # noqa
    import tty  # noqa
except ImportError:
    async_readlines = AsyncReadlinesDumb
else:
    async_readlines = AsyncReadlinesTermios
