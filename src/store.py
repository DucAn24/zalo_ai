"""Business cache: build canonical tables once per business, keep them in memory and on disk."""
from __future__ import annotations

import collections
import hashlib
import logging
import os
import pickle
import threading
from typing import Optional

from .canon import Business, CanonOptions, build_business

log = logging.getLogger(__name__)

_SRC_FILES = ["loader.py", "parse.py", "mapping.py", "schema.py", "canon.py", "readme.py", "textnorm.py"]


def code_version() -> str:
    h = hashlib.sha1()
    here = os.path.dirname(os.path.abspath(__file__))
    for f in _SRC_FILES:
        with open(os.path.join(here, f), "rb") as fh:
            h.update(fh.read())
    h.update(os.environ.get("DATAMATE_IGNORE_README", "0").encode())
    mask = os.environ.get("DATAMATE_VOCAB_MASK")
    if mask and os.path.exists(mask):
        with open(mask, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:12]


def _dir_signature(path: str) -> str:
    h = hashlib.sha1(os.path.abspath(path).encode())
    for f in sorted(os.listdir(path)):
        p = os.path.join(path, f)
        if os.path.isfile(p):
            st = os.stat(p)
            h.update(f"{f}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:16]


class BusinessStore:
    def __init__(self, data_dir: str, cache_dir: Optional[str] = None, max_mem: int = 8,
                 opts: Optional[CanonOptions] = None):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.max_mem = max_mem
        self.opts = opts or CanonOptions()
        self._mem: "collections.OrderedDict[str, Business]" = collections.OrderedDict()
        self._lock = threading.Lock()
        self._building: dict[str, threading.Lock] = collections.defaultdict(threading.Lock)
        self._ver = code_version()
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, biz_id: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        sig = _dir_signature(os.path.join(self.data_dir, biz_id))
        return os.path.join(self.cache_dir, f"{biz_id}-{self._ver}-{sig}.pkl")

    def get(self, biz_id: str) -> Business:
        with self._lock:
            if biz_id in self._mem:
                self._mem.move_to_end(biz_id)
                return self._mem[biz_id]
        with self._building[biz_id]:
            with self._lock:
                if biz_id in self._mem:
                    return self._mem[biz_id]
            B = None
            cp = self._cache_path(biz_id)
            if cp and os.path.exists(cp):
                try:
                    with open(cp, "rb") as f:
                        B = pickle.load(f)
                except Exception as e:  # corrupted cache
                    log.warning("cache read failed %s: %s", cp, e)
            if B is None:
                B = build_business(os.path.join(self.data_dir, biz_id), self.opts)
                B.maps = None  # raw maps are large and not needed after build
                if cp:
                    tmp = cp + ".tmp"
                    with open(tmp, "wb") as f:
                        pickle.dump(B, f, protocol=pickle.HIGHEST_PROTOCOL)
                    os.replace(tmp, cp)
            with self._lock:
                self._mem[biz_id] = B
                while len(self._mem) > self.max_mem:
                    self._mem.popitem(last=False)
            return B
