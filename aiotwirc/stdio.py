import sys
import asyncio
import contextlib


class DumbLine(bytes):
    def show(self):
        pass

    def hide(self):
        pass


async def async_readlines_dumb(loop):
    fp = sys.stdin.buffer

    buf = b''
    eof = object()
    queue = asyncio.Queue()

    def on_readable():
        s = fp.read1(4096)
        if s == b'':
            queue.put_nowait(eof)
            loop.remove_reader(fp)
        else:
            nonlocal buf
            buf += s
            linedata, nl, buf = buf.rpartition(b'\n')
            if nl:
                for line in linedata.split(b'\n'):
                    queue.put_nowait(line)

    loop.add_reader(fp, on_readable)
    while True:
        try:
            o = await queue.get()
        except asyncio.CancelledError:
            break
        if o is eof:
            break
        yield DumbLine(o)


class TermiosLine(bytes):
    def show(self):
        sys.stdout.buffer.write(b'\n')
        sys.stdout.buffer.flush()

    def hide(self):
        sys.stdout.buffer.write(b'\r\x1B[K')
        sys.stdout.buffer.flush()


async def async_readlines_termios(loop):
    @contextlib.contextmanager
    def setcbreak(fd):
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
    def wrap_write(fp):
        old_write = fp.write
        write_buf = ''

        def write(s, *args, **kwargs):
            nonlocal write_buf
            write_buf += s
            lines, nl, write_buf = write_buf.rpartition('\n')
            if nl:
                if buf:
                    r = fp.buffer.write(
                        b'\r\x1B[K%s%s' % ((lines+nl).encode(), buf))
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

    fp = sys.stdin.buffer

    buf = b''
    eof = object()
    queue = asyncio.Queue()

    def on_readable():
        nonlocal buf
        s = fp.read1(1)
        if s == b'' or (s == b'\x04' and not buf):  # CTRL-D
            queue.put_nowait(eof)
            loop.remove_reader(fp)
        elif s in (b'\x08', b'\x7F'):  # CTRL-H
            if buf:
                buf = buf[:-1]
                sys.stdout.buffer.write(b'\x08\x1B[K')
                sys.stdout.buffer.flush()
        elif s == b'\x15':  # CTRL-U
            if buf:
                buf = b''
                sys.stdout.buffer.write(b'\r\x1B[K')
                sys.stdout.buffer.flush()
        elif s == b'\x17':  # CTRL-W
            if buf:
                buf = buf.rstrip()
                buf = buf[:buf.rfind(b' ')+1]
                sys.stdout.buffer.write(b'\r\x1B[K' + buf)
                sys.stdout.buffer.flush()
        elif s == b'\n':
            queue.put_nowait(buf)
            buf = b''
        else:
            if s < b' ':
                s = b'^' + bytes([s[0] + 64])
            sys.stdout.buffer.write(s)
            sys.stdout.buffer.flush()
            buf += s

    loop.add_reader(fp, on_readable)
    with contextlib.ExitStack() as stack:
        stack.enter_context(setcbreak(0))
        stack.enter_context(wrap_write(sys.stdout))
        stack.enter_context(wrap_write(sys.stderr))
        while True:
            try:
                o = await queue.get()
            except asyncio.CancelledError:
                break
            if o is eof:
                break
            yield TermiosLine(o)


try:
    import termios  # noqa
    import tty  # noqa
except ImportError:
    async_readlines = async_readlines_dumb
else:
    async_readlines = async_readlines_termios
