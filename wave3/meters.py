"""Peak level readers.

One capture per metered node. pw-cat/pw-record in 1.0.5 have no raw-stream
mode (file output only), so this uses `parecord --raw`. Each reader is 8 kHz
mono s16 on its own thread and publishes only a float, so the GTK side polls
without locking.
"""

import math
import struct
import subprocess
import threading
import time

RATE = 8000
CHUNK_BYTES = 512

# parecord defaults to roughly a two second buffer and delivers one burst per
# buffer; requesting a short latency is what makes the stream continuous.
LATENCY_MS = 30
RESTART_DELAY = 1.0
SILENCE_DB = -90.0

# An idle PipeWire sink stops handing chunks to the recorder, which freezes
# the meter at its last reading. Anything older than STALE_AFTER is faded out.
STALE_AFTER = 0.15
STALE_FADE = 0.4


def amplitude_to_db(amplitude):
    return SILENCE_DB if amplitude <= 0.0 else max(SILENCE_DB, 20.0 * math.log10(amplitude))


class PeakReader:
    """Continuously reports the peak level of one PipeWire node."""

    def __init__(self, device):
        self.device = device
        self.peak = 0.0
        self._updated = 0.0
        self._proc = None
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        # Each run owns its event. Clearing a shared one would revive a thread
        # that stop() had already told to exit, leaving two recorders on the
        # same node with only one of them reachable through self._proc.
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(self._stop,),
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout=3.0):
        self._stop.set()
        proc = self._proc
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        self._thread = None
        self._proc = None
        self.peak = 0.0
        self._updated = 0.0

    def _spawn(self):
        return subprocess.Popen(
            ["parecord", "--raw", "-d", self.device,
             "--format=s16le", f"--rate={RATE}", "--channels=1",
             f"--latency-msec={LATENCY_MS}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        )

    def _run(self, stop):
        """Read peaks, restarting the recorder if it exits.

        A recorder exits when its source disappears or suspends; without a
        restart the meter would read -90 for the rest of the session.
        """
        while not stop.is_set():
            try:
                proc = self._spawn()
            except OSError:
                return
            if stop.is_set():
                proc.terminate()
                return
            self._proc = proc

            stream = proc.stdout
            while not stop.is_set():
                data = stream.read(CHUNK_BYTES)
                if not data:
                    break
                count = len(data) // 2
                if count == 0:
                    continue
                samples = struct.unpack(f"<{count}h", data[: count * 2])
                self.peak = max(abs(s) for s in samples) / 32768.0
                self._updated = time.monotonic()

            if stop.wait(RESTART_DELAY):
                return

    @property
    def db(self):
        """Peak in dBFS, faded out once readings go stale."""
        if self._updated == 0.0:
            return SILENCE_DB
        age = time.monotonic() - self._updated
        if age <= STALE_AFTER:
            return amplitude_to_db(self.peak)
        if age >= STALE_AFTER + STALE_FADE:
            return SILENCE_DB
        fade = (age - STALE_AFTER) / STALE_FADE
        return amplitude_to_db(self.peak) * (1.0 - fade) + SILENCE_DB * fade


class MeterBank:
    """Owns every reader so the UI starts and stops them as one."""

    def __init__(self):
        self.readers = {}

    def add(self, key, device):
        if key in self.readers:
            return self.readers[key]
        reader = PeakReader(device)
        self.readers[key] = reader
        return reader

    def start(self):
        for reader in self.readers.values():
            reader.start()

    def stop(self):
        for reader in self.readers.values():
            reader.stop()

    def db(self, key):
        reader = self.readers.get(key)
        return reader.db if reader else SILENCE_DB
