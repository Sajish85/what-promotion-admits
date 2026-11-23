#!/usr/bin/env python3
"""TCP proxy with a control port. usage: tcpproxy.py LISTEN_PORT TARGET_PORT CTL_PORT
Control (one line, TCP to CTL_PORT): 'pass' | 'stall' | 'status'.
stall = stop forwarding in both directions on every open connection (bytes stay unread in kernel
buffers), hold new connections without opening the upstream leg, defer close propagation.
pass  = resume: held bytes are forwarded, held connections are opened, deferred closes applied."""
import asyncio, sys, time
LP, TP, CP = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
mode = "pass"; sides = []; fwd = [0, 0]  # bytes forwarded client->up, up->client
resume_ev = None

class Side(asyncio.Protocol):
    def __init__(self, idx):
        self.idx = idx; self.peer = None; self.tr = None; self.held = []; self.pending_close = False; self.pre = []
    def connection_made(self, tr):
        self.tr = tr; sides.append(self)
    def data_received(self, data):
        if self.peer is None or self.peer.tr is None:
            self.pre.append(data); return
        if mode == "stall":
            self.held.append(data); return
        fwd[self.idx] += len(data); self.peer.tr.write(data)
    def flush(self):
        if self.peer is not None and self.peer.tr is not None:
            for d in self.pre + self.held:
                fwd[self.idx] += len(d); self.peer.tr.write(d)
            self.pre = []; self.held = []
    def connection_lost(self, exc):
        if self in sides: sides.remove(self)
        p = self.peer; self.tr = None
        if p is not None and p.tr is not None:
            if mode == "stall": p.pending_close = True
            else: p.tr.close()

class Client(Side):
    def connection_made(self, tr):
        super().connection_made(tr)
        asyncio.ensure_future(self.open_up())
    async def open_up(self):
        global resume_ev
        while mode == "stall":
            await resume_ev.wait()
            await asyncio.sleep(0)
        loop = asyncio.get_event_loop()
        up = Side(1)
        try:
            await loop.create_connection(lambda: up, "127.0.0.1", TP)
        except Exception:
            if self.tr: self.tr.close()
            return
        self.peer = up; up.peer = self
        self.flush()

async def ctl(reader, writer):
    global mode, resume_ev
    line = (await reader.readline()).decode().strip()
    if line == "stall":
        mode = "stall"; resume_ev.clear()
        for s in sides:
            if s.tr is not None: s.tr.pause_reading()
    elif line == "pass":
        mode = "pass"
        for s in list(sides):
            s.flush()
            if s.tr is not None:
                try: s.tr.resume_reading()
                except Exception: pass
            if s.pending_close and s.tr is not None:
                s.pending_close = False; s.tr.close()
        resume_ev.set()
    writer.write(f"{mode} conns={len(sides)} fwd_c2u={fwd[0]} fwd_u2c={fwd[1]}\n".encode())
    await writer.drain(); writer.close()

async def main():
    global resume_ev
    resume_ev = asyncio.Event(); resume_ev.set()
    loop = asyncio.get_event_loop()
    await loop.create_server(lambda: Client(0), "127.0.0.1", LP, backlog=128)
    await asyncio.start_server(ctl, "127.0.0.1", CP)
    await asyncio.Event().wait()
asyncio.run(main())
