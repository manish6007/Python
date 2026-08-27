"""The thing someone double-clicks.

A person who wants to track their money should not have to meet Python,
npm, or a terminal. This starts the server, opens the browser at it, and
stays out of the way -- and says, in words, where their data is being kept,
because that is the first question anyone sensible asks.

Closing the window stops the app. Nothing keeps running in the background.
"""
import os
import socket
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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = free_port(int(os.environ.get("PORTFOLIO_PORT") or DEFAULT_PORT))

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
    if not os.path.isdir(paths.frontend_dist()):
        raise SystemExit(
            "The built frontend is missing (%s).\n"
            "From source, run:  cd frontend && npm install && npm run build"
            % paths.frontend_dist())
    main()
