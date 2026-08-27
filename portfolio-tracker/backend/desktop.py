"""The thing someone double-clicks.

A person who wants to track their money should not have to meet Python,
npm, or a terminal. This starts the server, opens the browser at it, and
stays out of the way -- and says, in words, where their data is being kept,
because that is the first question anyone sensible asks.

Closing the window stops the app. Nothing keeps running in the background.
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import paths

DEFAULT_PORT = 8765          # not 8000: too many other things want 8000
HOST = "127.0.0.1"           # never 0.0.0.0 -- this serves the machine it is on


def free_port(preferred=DEFAULT_PORT, tries=20):
    """The first port nothing else is using, starting at the preferred one.

    A second copy of the app, or any other server on that port, should not
    produce a stack trace on a stranger's screen.
    """
    for offset in range(tries):
        port = preferred + offset
        with socket.socket() as probe:
            # Bind *and* listen, with no SO_REUSEADDR: the probe has to be
            # exactly as strict as the real server, or it reports a port
            # free and uvicorn then fails with "address already in use".
            try:
                probe.bind((HOST, port))
                probe.listen(1)
                return port
            except OSError:
                continue
    raise SystemExit("Could not find a free port between %d and %d."
                     % (preferred, preferred + tries - 1))


def wait_until_serving(port, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def announce(port, data_dir):
    """Say it, and flush it.

    A console app that buffers its output shows a stranger a blank window
    while the thing they need -- the address to open -- sits unwritten.
    """
    print()
    print("  Portfolio Tracker is running.")
    print()
    print("  Open it at   http://%s:%d" % (HOST, port))
    print("  Your data is %s" % data_dir)
    print()
    print("  Nothing leaves this machine except mutual-fund and share prices.")
    print("  Back up the folder above and you have backed up everything.")
    print()
    print("  Close this window to stop the app.")
    print(flush=True)


def npm():
    """The npm executable, or "" when Node is not installed."""
    return shutil.which("npm") or shutil.which("npm.cmd") or ""


def build_frontend():
    """Rebuild the interface when it is older than the code it comes from.

    Doing this only when the folder is missing was the bug: after a pull the
    folder is still there, so months-old HTML gets served against today's
    API and whole pages are simply absent. It is checked every start now,
    and a rebuild takes a few seconds.
    """
    if paths.is_frozen() or not paths.frontend_is_stale():
        return True
    frontend = os.path.join(paths.bundle_dir(), "frontend")
    tool = npm()
    if not tool:
        print("  The interface needs rebuilding but Node is not installed.",
              flush=True)
        print("  Install Node 18+ and run this again, or download the "
              "ready-made app.", flush=True)
        return os.path.isdir(paths.frontend_dist())
    if not os.path.isdir(os.path.join(frontend, "node_modules")):
        print("  Installing the interface's dependencies (first run only)...",
              flush=True)
        if subprocess.call([tool, "install"], cwd=frontend) != 0:
            return os.path.isdir(paths.frontend_dist())
    print("  Building the interface (a few seconds)...", flush=True)
    if subprocess.call([tool, "run", "build"], cwd=frontend) != 0:
        print("  That build failed. The app will start with whatever was "
              "built last, which may be out of date.", flush=True)
    return os.path.isdir(paths.frontend_dist())


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = free_port(int(os.environ.get("PORTFOLIO_PORT") or DEFAULT_PORT))

    if not build_frontend():
        raise SystemExit(
            "The interface could not be built and none was found at %s."
            % paths.frontend_dist())

    import config
    os.makedirs(config.data_dir(), exist_ok=True)
    announce(port, config.data_dir())

    if "--no-browser" not in argv:
        threading.Thread(
            target=lambda: (wait_until_serving(port)
                            and webbrowser.open("http://%s:%d" % (HOST, port))),
            daemon=True).start()

    import uvicorn
    from main import app
    try:
        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    except KeyboardInterrupt:            # Ctrl-C is a normal way to stop
        pass
    print("Stopped. Your data is still in %s" % config.data_dir(),
          flush=True)


if __name__ == "__main__":
    main()
