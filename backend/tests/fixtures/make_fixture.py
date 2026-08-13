"""Génère un parquet de test au format Databento MBO (GLBX.MDP3)."""
import pyarrow as pa
import pyarrow.parquet as pq

BASE = 1_700_000_000_000_000_000  # ns
def ns(off_ms): return BASE + off_ms * 1_000_000
PX = 1_000_000_000  # Databento : prix int64 en fixed-point 1e-9

rows = [
  # ts_event, action, side, price, size, order_id, sequence
  (ns(0),   'R', 'N', 0,            0,  0,   1),   # clear/snapshot start
  (ns(1),   'A', 'B', 5000_00*PX//100, 40, 101, 2),# add bid 5000.00 x40
  (ns(2),   'A', 'A', 5000_25*PX//100, 35, 102, 3),
  (ns(10),  'T', 'A', 5000_25*PX//100, 10, 0,   4),# trade agressif ask
  (ns(12),  'C', 'A', 5000_25*PX//100, 25, 102, 5),# cancel
  (ns(20),  'M', 'B', 4999_75*PX//100, 40, 101, 6),# modify
  (ns(30),  'T', 'B', 4999_75*PX//100, 15, 0,   7),# trade agressif bid
]
t = pa.table({
  'ts_event':   pa.array([r[0] for r in rows], pa.int64()),
  'ts_recv':    pa.array([r[0]+500 for r in rows], pa.int64()),
  'action':     pa.array([r[1] for r in rows], pa.string()),
  'side':       pa.array([r[2] for r in rows], pa.string()),
  'price':      pa.array([r[3] for r in rows], pa.int64()),
  'size':       pa.array([r[4] for r in rows], pa.uint32()),
  'order_id':   pa.array([r[5] for r in rows], pa.uint64()),
  'sequence':   pa.array([r[6] for r in rows], pa.uint32()),
  'symbol':     pa.array(['MESZ4']*len(rows), pa.string()),
})
pq.write_table(t, 'tests/fixtures/mbo_sample.parquet')

# Fichier corrompu : timestamps non monotones + NaN-like
bad = pa.table({
  'ts_event': pa.array([ns(5), ns(3), ns(9)], pa.int64()),   # recul
  'ts_recv':  pa.array([ns(5), ns(3), ns(9)], pa.int64()),
  'action':   pa.array(['A','A','X'], pa.string()),          # action inconnue
  'side':     pa.array(['B','A','B'], pa.string()),
  'price':    pa.array([5000*PX, 5000*PX, 5000*PX], pa.int64()),
  'size':     pa.array([10, 10, 10], pa.uint32()),
  'order_id': pa.array([1,2,3], pa.uint64()),
  'sequence': pa.array([1,2,3], pa.uint32()),
  'symbol':   pa.array(['MESZ4']*3, pa.string()),
})
pq.write_table(bad, 'tests/fixtures/mbo_corrupt.parquet')
print("fixtures written")
