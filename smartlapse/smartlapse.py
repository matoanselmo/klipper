#!/usr/bin/env python3
"""smartlapse - per-layer timelapse that picks the best frame, no gcode changes.

Streams the camera continuously, reconstructs the exact toolhead position at
each frame's capture time from Klipper's trapq history, and keeps the frame of
each layer where the nozzle was farthest from the camera (and the bed closest
to a reference Y).  Frames are written as /tmp/timelapse/frameNNNNNN.jpg so the
moonraker-timelapse plugin cleans up and renders them as usual.
"""
import argparse
import asyncio
import bisect
import collections
import configparser
import json
import logging
import logging.handlers
import os
import statistics
import time
import urllib.parse

DEFAULTS = {
    'klippy_socket': '~/printer_data/comms/klippy.sock',
    'stream_url': 'http://127.0.0.1:8080/?action=stream',
    'frame_path': '/tmp/timelapse/',
    'log_file': '~/printer_data/logs/smartlapse.log',
    'camera_x': '200',        # X of the camera in printer coordinates
    'y_ref_default': '65',    # used when the gcode defines no objects
    'y_weight': '1.0',        # penalty per mm away from the reference Y
    'speed_weight': '0.0',    # penalty per mm/s of toolhead speed
    'sample_fps': '10',
    'latency_offset': '0.0',  # seconds added to camera capture timestamps
    'process_lag': '1.5',     # seconds to wait for trapq data to arrive
    'min_layer_step': '0.05',
    'debug': 'false',
}

log = logging.getLogger('smartlapse')


class Trapq:
    """Rows: (time, duration, start_v, accel, start_pos, direction)."""

    def __init__(self):
        self.segs = []
        self.starts = []

    def add(self, rows):
        for r in rows:
            t = r[0]
            if self.starts and t <= self.starts[-1]:
                continue
            self.segs.append(r)
            self.starts.append(t)

    def prune(self, before):
        n = 0
        while n < len(self.segs) - 1 and self.segs[n][0] + self.segs[n][1] < before:
            n += 1
        if n:
            del self.segs[:n]
            del self.starts[:n]

    def find(self, pt):
        i = bisect.bisect_right(self.starts, pt) - 1
        return self.segs[i] if i >= 0 else None

    def position(self, pt):
        seg = self.find(pt)
        if seg is None:
            return None, 0.
        t, dur, v, a, sp, dr = seg
        rel = max(0., min(dur, pt - t))
        d = (v + .5 * a * rel) * rel
        speed = v + a * rel if pt - t <= dur else 0.
        return tuple(sp[i] + dr[i] * d for i in range(3)), speed

    def moving_forward(self, pt):
        seg = self.find(pt)
        if seg is None:
            return False
        t, dur, v, a, sp, dr = seg
        rel = pt - t
        return rel <= dur and dr[0] > 0. and (v + a * rel) > 0.


class SmartLapse:
    def __init__(self, cfg, calibrate_dir=None):
        self.cfg = cfg
        self.calibrate_dir = calibrate_dir
        self.frame_path = os.path.expanduser(cfg['frame_path'])
        self.camera_x = float(cfg['camera_x'])
        self.y_ref_default = float(cfg['y_ref_default'])
        self.y_weight = float(cfg['y_weight'])
        self.speed_weight = float(cfg['speed_weight'])
        self.sample_period = 1. / float(cfg['sample_fps'])
        self.latency_offset = float(cfg['latency_offset'])
        self.process_lag = float(cfg['process_lag'])
        self.min_layer_step = float(cfg['min_layer_step'])
        self.debug = cfg.getboolean('debug')
        # Klipper state
        self.writer = None
        self.next_id = 1
        self.pending = {}
        self.async_handlers = {}
        self.offsets = collections.deque(maxlen=15)  # print_time - wall
        self.print_state = 'standby'
        self.y_ref = self.y_ref_default
        self.mesh = None          # (matrix, min_xy, max_xy) from bed_mesh
        self.mesh_cfg = {}
        self.fade_target = 0.
        self.toolhead = Trapq()
        self.extruder = Trapq()
        # Frames: (print_time, jpeg)
        self.frames = collections.deque()
        self.last_frame_wall = 0.
        self.reset_print()

    # ---- print bookkeeping -------------------------------------------------
    def reset_print(self):
        self.print_start_pt = None  # set by process() once the clock is synced
        self.seg_cursor = float('inf')
        self.layer_z = None
        self.layers = []          # (start_pt, layer_number)
        self.frame_no = None      # number of the frame file being written
        self.frame_layer = None   # layer the current frame file belongs to
        self.best_score = None
        self.frames.clear()

    def wall_to_pt(self, wall):
        if not self.offsets:
            return None
        return wall + statistics.median(self.offsets)

    # ---- bed mesh --------------------------------------------------------
    # The trapq holds Z after bed_mesh compensation, which wanders within a
    # layer.  Undo it (same math as klippy/extras/bed_mesh.py) so layer
    # detection sees the gcode Z.
    def set_mesh(self, bm):
        tbl = bm.get('mesh_matrix') or [[]]
        if not tbl[0]:
            self.mesh = None
            self.fade_target = 0.
            return
        self.mesh = (tbl, bm['mesh_min'], bm['mesh_max'])
        fs = float(self.mesh_cfg.get('fade_start', 1.))
        fe = float(self.mesh_cfg.get('fade_end', 0.))
        flat = [z for row in tbl for z in row]
        if fe <= fs:
            self.fade_target = 0.
        elif self.mesh_cfg.get('fade_target') is not None:
            self.fade_target = float(self.mesh_cfg['fade_target'])
        else:
            self.fade_target = round(sum(flat) / len(flat), 2)
        if fe > fs and fe - fs <= max(abs(min(flat)), abs(max(flat))):
            self.fade_target = 0.
        log.info('bed mesh %dx%d loaded, fade_target %.2f',
                 len(tbl[0]), len(tbl), self.fade_target)

    def mesh_z(self, x, y):
        tbl, mn, mx = self.mesh

        def index(v, axis, count):
            step = (mx[axis] - mn[axis]) / (count - 1)
            if step <= 0.:
                return 0., 0
            v = max(mn[axis], min(mx[axis], v))
            idx = min(int((v - mn[axis]) / step), count - 2)
            return max(0., min(1., (v - (mn[axis] + idx * step)) / step)), idx

        tx, xi = index(x, 0, len(tbl[0]))
        ty, yi = index(y, 1, len(tbl))
        z0 = tbl[yi][xi] + tx * (tbl[yi][xi + 1] - tbl[yi][xi])
        z1 = tbl[yi + 1][xi] + tx * (tbl[yi + 1][xi + 1] - tbl[yi + 1][xi])
        return z0 + ty * (z1 - z0)

    def gcode_z(self, x, y, z):
        if self.mesh is None:
            return z - self.fade_target
        fs = float(self.mesh_cfg.get('fade_start', 1.))
        fe = float(self.mesh_cfg.get('fade_end', 0.))
        adj = self.mesh_z(x, y) - self.fade_target
        g = z - self.fade_target - adj
        if fe > fs:
            for _ in range(4):
                f = 1. if g < fs else (0. if g >= fe else (fe - g) / (fe - fs))
                g = z - self.fade_target - f * adj
        return g

    # ---- Klipper API -------------------------------------------------------
    async def request(self, method, params=None, async_cb=None):
        msg_id = self.next_id
        self.next_id += 1
        params = dict(params or {})
        if async_cb is not None:
            params['response_template'] = {'q': msg_id}
            self.async_handlers[msg_id] = async_cb
        fut = asyncio.get_running_loop().create_future()
        self.pending[msg_id] = fut
        data = json.dumps({'id': msg_id, 'method': method, 'params': params},
                          separators=(',', ':')).encode()
        self.writer.write(data + b'\x03')
        await self.writer.drain()
        resp = await asyncio.wait_for(fut, 10.)
        if 'error' in resp:
            raise RuntimeError('%s: %s' % (method, resp['error']))
        return resp['result']

    async def klippy_reader(self, reader):
        buf = b''
        while True:
            data = await reader.read(65536)
            if not data:
                raise ConnectionError('klippy socket closed')
            parts = (buf + data).split(b'\x03')
            buf = parts.pop()
            for part in parts:
                msg = json.loads(part)
                q = msg.get('q')
                if q is not None:
                    hdl = self.async_handlers.get(q)
                    if hdl is not None:
                        hdl(msg.get('params', {}))
                    continue
                fut = self.pending.pop(msg.get('id'), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)

    def handle_status(self, status):
        ps = status.get('print_stats', {})
        if 'state' in ps:
            new = ps['state']
            if new == 'printing' and self.print_state != 'paused':
                log.info('print started')
                self.reset_print()
            elif new != self.print_state:
                log.info('print state: %s', new)
            self.print_state = new
        if 'bed_mesh' in status:
            bm = {}
            if self.mesh is not None:
                bm = {'mesh_matrix': self.mesh[0], 'mesh_min': self.mesh[1],
                      'mesh_max': self.mesh[2]}
            bm.update(status['bed_mesh'])
            self.set_mesh(bm)
        eo = status.get('exclude_object', {})
        if 'objects' in eo:
            ys = [p[1] for o in eo['objects'] for p in (o.get('polygon') or [])]
            self.y_ref = (min(ys) + max(ys)) / 2. if ys else self.y_ref_default
            log.info('reference Y = %.1f', self.y_ref)

    async def sync_clock(self):
        while True:
            t0 = time.time()
            res = await self.request('objects/query',
                                     {'objects': {'toolhead': ['estimated_print_time']}})
            t1 = time.time()
            ept = res['status']['toolhead']['estimated_print_time']
            self.offsets.append(ept - (t0 + t1) / 2.)
            await asyncio.sleep(2.)

    async def klippy_session(self):
        path = os.path.expanduser(self.cfg['klippy_socket'])
        reader, self.writer = await asyncio.open_unix_connection(path, limit=1 << 22)
        self.pending.clear()
        self.async_handlers.clear()
        self.offsets.clear()
        self.toolhead, self.extruder = Trapq(), Trapq()
        self.reset_print()
        rtask = asyncio.create_task(self.klippy_reader(reader))
        try:
            while (await self.request('info'))['state'] != 'ready':
                await asyncio.sleep(2.)
            log.info('connected to klipper')
            sync = asyncio.create_task(self.sync_clock())
            await self.request('motion_report/dump_trapq', {'name': 'toolhead'},
                               lambda p: self.toolhead.add(p.get('data', [])))
            await self.request('motion_report/dump_trapq', {'name': 'extruder'},
                               lambda p: self.extruder.add(p.get('data', [])))
            res = await self.request('objects/query',
                                     {'objects': {'configfile': ['settings']}})
            self.mesh_cfg = res['status']['configfile']['settings'].get('bed_mesh', {})
            res = await self.request(
                'objects/subscribe',
                {'objects': {'print_stats': ['state'], 'exclude_object': ['objects'],
                             'bed_mesh': ['mesh_matrix', 'mesh_min', 'mesh_max']}},
                lambda p: self.handle_status(p.get('status', {})))
            self.print_state = res['status']['print_stats']['state']
            self.handle_status({'exclude_object': res['status']['exclude_object'],
                                'bed_mesh': res['status']['bed_mesh']})
            log.info('print state: %s', self.print_state)
            await asyncio.wait([rtask, sync], return_when=asyncio.FIRST_EXCEPTION)
            for t in (rtask, sync):
                if t.done() and t.exception():
                    raise t.exception()
        finally:
            rtask.cancel()
            self.writer.close()

    # ---- camera ------------------------------------------------------------
    async def camera_session(self):
        url = urllib.parse.urlsplit(self.cfg['stream_url'])
        reader, writer = await asyncio.open_connection(url.hostname, url.port or 80,
                                                       limit=1 << 22)
        path = url.path + ('?' + url.query if url.query else '')
        writer.write(('GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n'
                      % (path, url.hostname)).encode())
        await writer.drain()
        try:
            status = await reader.readline()
            if b' 200 ' not in status:
                raise ConnectionError('camera: %r' % status)
            while (await reader.readline()).strip():
                pass
            log.info('camera stream connected')
            while True:
                headers = {}
                while True:
                    line = await asyncio.wait_for(reader.readline(), 10.)
                    if not line:
                        raise ConnectionError('camera stream closed')
                    line = line.strip()
                    if not line:
                        if headers:
                            break
                        continue
                    if b':' in line:
                        k, v = line.split(b':', 1)
                        headers[k.strip().lower()] = v.strip()
                length = int(headers[b'content-length'])
                jpeg = await reader.readexactly(length)
                ts = float(headers.get(b'x-timestamp', time.time()))
                self.add_frame(ts, jpeg)
        finally:
            writer.close()

    def add_frame(self, ts, jpeg):
        if ts - self.last_frame_wall < self.sample_period:
            return
        if self.print_state != 'printing' and not self.calibrate_dir:
            return
        pt = self.wall_to_pt(ts + self.latency_offset)
        if pt is None:
            return
        self.last_frame_wall = ts
        self.frames.append((pt, jpeg))
        while self.frames and pt - self.frames[0][0] > 10.:
            self.frames.popleft()

    # ---- processing --------------------------------------------------------
    def detect_layers(self, until):
        th = self.toolhead
        i = bisect.bisect_left(th.starts, self.seg_cursor)
        while i < len(th.segs):
            t, dur, v, a, sp, dr = th.segs[i]
            mid = t + dur / 2.
            if mid > until:
                break
            self.seg_cursor = t + 1e-9
            i += 1
            if dur <= 0. or abs(dr[0]) + abs(dr[1]) < .5:
                continue
            if not self.extruder.moving_forward(mid):
                continue
            pos, _ = th.position(mid)
            z = self.gcode_z(*pos)
            if self.layer_z is None or z >= self.layer_z + self.min_layer_step:
                self.layer_z = z
                self.layers.append((t, len(self.layers) + 1))
                if self.debug:
                    log.debug('layer %d at z=%.3f', len(self.layers), z)

    def layer_at(self, pt):
        i = bisect.bisect_right(self.layers, (pt, float('inf'))) - 1
        return self.layers[i][1] if i >= 0 else None

    def score(self, pos, speed):
        return ((self.camera_x - pos[0]) - self.y_weight * abs(pos[1] - self.y_ref)
                - self.speed_weight * abs(speed))

    def write_frame(self, name, jpeg):
        os.makedirs(self.frame_path, exist_ok=True)
        tmp = os.path.join(self.frame_path, '.smartlapse.tmp')
        with open(tmp, 'wb') as f:
            f.write(jpeg)
        os.replace(tmp, os.path.join(self.frame_path, name))

    def process(self):
        now = self.wall_to_pt(time.time())
        if now is None:
            return
        until = now - self.process_lag
        if self.calibrate_dir:
            self.process_calibrate(until)
            return
        if self.print_state == 'printing' and self.print_start_pt is None:
            self.print_start_pt = self.seg_cursor = now
        if self.print_start_pt is not None:
            self.detect_layers(until)
        while self.frames and self.frames[0][0] <= until:
            pt, jpeg = self.frames.popleft()
            if self.print_start_pt is None or pt < self.print_start_pt:
                continue
            layer = self.layer_at(pt)
            pos, speed = self.toolhead.position(pt)
            if layer is None or pos is None:
                continue
            if layer != self.frame_layer:
                if self.frame_no is None:
                    # Continue after frames already on disk (service restarted
                    # mid-print); the timelapse plugin empties the folder when
                    # a new print is selected.
                    self.frame_no = len([f for f in os.listdir(self.frame_path)
                                         if f.startswith('frame') and f.endswith('.jpg')]
                                        ) if os.path.isdir(self.frame_path) else 0
                self.frame_layer = layer
                self.frame_no += 1
                self.best_score = None
            s = self.score(pos, speed)
            if self.best_score is None or s > self.best_score:
                self.best_score = s
                self.write_frame('frame%06d.jpg' % self.frame_no, jpeg)
                if self.debug:
                    log.debug('frame %d (layer %d): pt=%.3f pos=%.1f,%.1f,%.2f '
                              'v=%.0f score=%.1f', self.frame_no, layer, pt,
                              pos[0], pos[1], pos[2], speed, s)
        keep = min(until, self.seg_cursor) - 5.
        self.toolhead.prune(keep)
        self.extruder.prune(keep)

    def process_calibrate(self, until):
        while self.frames and self.frames[0][0] <= until:
            pt, jpeg = self.frames.popleft()
            pos, speed = self.toolhead.position(pt)
            if pos is None:
                continue
            name = 'pt%.3f_x%06.1f_y%06.1f_v%03.0f.jpg' % (pt, pos[0], pos[1], speed)
            with open(os.path.join(self.calibrate_dir, name), 'wb') as f:
                f.write(jpeg)
        self.toolhead.prune(until - 5.)

    # ---- main --------------------------------------------------------------
    async def run_forever(self, coro_fn, name):
        delay = 1.
        while True:
            start = time.monotonic()
            try:
                await coro_fn()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning('%s: %s', name, e)
            if time.monotonic() - start > 30.:
                delay = 1.
            await asyncio.sleep(delay)
            delay = min(delay * 2., 30.)

    async def process_loop(self):
        while True:
            await asyncio.sleep(.2)
            try:
                self.process()
            except Exception:
                log.exception('processing error')

    async def main(self):
        await asyncio.gather(self.run_forever(self.klippy_session, 'klippy'),
                             self.run_forever(self.camera_session, 'camera'),
                             self.process_loop())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('-c', '--config',
                    default='~/printer_data/config/smartlapse.conf')
    ap.add_argument('--calibrate', metavar='DIR',
                    help='save every sampled frame with its computed position')
    args = ap.parse_args()
    cp = configparser.ConfigParser()
    cp.read_dict({'smartlapse': DEFAULTS})
    cp.read(os.path.expanduser(args.config))
    cfg = cp['smartlapse']
    debug = cfg.getboolean('debug')
    handlers = [logging.StreamHandler()]
    if cfg['log_file'] and not args.calibrate:
        handlers.append(logging.handlers.RotatingFileHandler(
            os.path.expanduser(cfg['log_file']), maxBytes=2 << 20, backupCount=2))
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s',
                        handlers=handlers)
    if args.calibrate:
        os.makedirs(args.calibrate, exist_ok=True)
    try:
        asyncio.run(SmartLapse(cfg, args.calibrate).main())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
