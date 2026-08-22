//! The nine-field signal substrate, engine-side — the exact port of
//! game/perihelion/signals.py's SignalField storage and math (that module
//! remains the typed facade; THIS is the one implementation).
//!
//! Determinism: no RNG, no wall clock, sorted iteration everywhere the
//! Python used sorted()/BTree order. Float operation ORDER is preserved
//! from the Python (spread flows applied in (chamber asc, door order),
//! interior gains applied in sorted-key order with insertion-order part
//! sums) so a replay is bit-identical across the port.
//!
//! Decay is EXPONENTIAL and analytic: every cell stores the tick it was
//! last materialized; a chamber that stops receiving updates fades at
//! exactly the same effective rate as one updated every tick. Spread runs
//! on a fixed global cadence (SPREAD_DT ticks) independent of sampling.

use std::collections::{BTreeMap, BTreeSet, HashMap};

pub const TICK_RATE: f64 = 60.0;
pub const SPREAD_DT: i64 = 15;
const EPS: f64 = 1e-5;
pub const NKINDS: usize = 9;

/// (half_life_seconds, spread_per_second, hop_gain), indexed by the facade's
/// SignalKind declaration order: DISTRESS, DANGER, NOISE, TRAIL, PATROL,
/// MUSTER, GARRISON_INTERIOR, GARRISON_REACH, KIN.
const SPEC: [(f64, f64, f64); NKINDS] = [
    (45.0, 0.12, 1.0),
    (180.0, 0.0, 1.0),
    (3.0, 1.20, 1.0),
    (12.0, 0.0, 1.0),
    (60.0, 0.0, 1.0),
    (1.0, 1.8, 0.35),
    (1.5, 0.9, 1.0),
    (2.0, 0.7, 1.0),
    (8.0, 0.45, 1.0),
];
const KIND_GARRISON_INTERIOR: usize = 6;
const KIND_GARRISON_REACH: usize = 7;

fn decay_per_tick(kind: usize) -> f64 {
    0.5f64.powf(1.0 / (SPEC[kind].0 * TICK_RATE))
}

pub struct SignalField {
    v: Vec<Vec<f64>>,
    t: Vec<Vec<i64>>,
    wet: BTreeSet<usize>,
    adj: Vec<Vec<usize>>,
    n: usize,
    last_spread: i64,
    decay: [f64; NKINDS],
    trail: HashMap<(usize, usize), (f64, i64)>,
}

const TRAIL_CAP: f64 = 8.0;
const TRAIL_HL_TICKS: f64 = 660.0;

impl SignalField {
    pub fn new(tick: i64) -> SignalField {
        let mut decay = [0.0; NKINDS];
        for (k, d) in decay.iter_mut().enumerate() {
            *d = decay_per_tick(k);
        }
        SignalField {
            v: vec![Vec::new(); NKINDS],
            t: vec![Vec::new(); NKINDS],
            wet: BTreeSet::new(),
            adj: Vec::new(),
            n: 0,
            last_spread: tick,
            decay,
            trail: HashMap::new(),
        }
    }

    /// Replace the adjacency (topology changed / chambers streamed in).
    /// Growing preserves cells; the facade passes each chamber's portal
    /// targets in edge order (float-order-critical for spread parity).
    pub fn set_adjacency(&mut self, adj: Vec<Vec<usize>>) {
        let n = adj.len();
        self.adj = adj;
        if n > self.n {
            for k in 0..NKINDS {
                self.v[k].resize(n, 0.0);
                self.t[k].resize(n, self.last_spread);
            }
        }
        self.n = self.n.max(n);
    }

    fn materialize(&mut self, kind: usize, polygon: usize, tick: i64) -> Result<(), String> {
        let dt = tick - self.t[kind][polygon];
        if dt < 0 {
            return Err(format!("time ran backwards for kind {kind} in {polygon}"));
        }
        if dt != 0 {
            let val = self.v[kind][polygon] * self.decay[kind].powf(dt as f64);
            self.v[kind][polygon] = if val < EPS { 0.0 } else { val };
            self.t[kind][polygon] = tick;
        }
        Ok(())
    }

    pub fn emit(&mut self, kind: usize, polygon: i64, amount: f64, tick: i64) -> Result<(), String> {
        if amount <= 0.0 || polygon < 0 || polygon as usize >= self.n {
            return Ok(());
        }
        let polygon = polygon as usize;
        self.materialize(kind, polygon, tick)?;
        self.v[kind][polygon] += amount;
        self.wet.insert(polygon);
        Ok(())
    }

    pub fn emit_many(&mut self, kind: usize, polygons: &[i64], amount: f64, tick: i64) -> Result<(), String> {
        if amount <= 0.0 {
            return Ok(());
        }
        for &polygon in polygons {
            self.emit(kind, polygon, amount, tick)?;
        }
        Ok(())
    }

    /// Raise the cell to at least `level`. Faithfully preserves the
    /// facade's quirk: the TIMESTAMP is not touched, so the next
    /// materialize decays the new level from the old stamp.
    pub fn emit_at_least(&mut self, kind: usize, polygon: i64, level: f64, tick: i64) -> Result<(), String> {
        if polygon < 0 || polygon as usize >= self.n {
            return Ok(());
        }
        let p = polygon as usize;
        let cur = self.sample(kind, p as i64, tick)?;
        if cur < level {
            self.v[kind][p] = level;
            self.wet.insert(p);
        }
        Ok(())
    }

    pub fn sample(&self, kind: usize, polygon: i64, tick: i64) -> Result<f64, String> {
        if polygon < 0 || polygon as usize >= self.n {
            return Err(format!("unknown chamber {polygon}"));
        }
        let p = polygon as usize;
        let dt = tick - self.t[kind][p];
        if dt < 0 {
            return Err(format!("time ran backwards for kind {kind} in {p}"));
        }
        let v = self.v[kind][p] * self.decay[kind].powf(dt as f64);
        Ok(if v < EPS { 0.0 } else { v })
    }

    pub fn sample_all(&self, polygon: i64, tick: i64) -> Result<[f64; NKINDS], String> {
        let mut out = [0.0; NKINDS];
        for (k, o) in out.iter_mut().enumerate() {
            *o = self.sample(k, polygon, tick)?;
        }
        Ok(out)
    }

    pub fn totals(&self, tick: i64) -> Result<[f64; NKINDS], String> {
        let mut out = [0.0; NKINDS];
        for (kind, o) in out.iter_mut().enumerate() {
            let mut tot = 0.0;
            for &r in &self.wet {
                let dt = tick - self.t[kind][r];
                if dt < 0 {
                    return Err(format!("time ran backwards for kind {kind} in {r}"));
                }
                let val = self.v[kind][r] * self.decay[kind].powf(dt as f64);
                if val >= EPS {
                    tot += val;
                }
            }
            *o = tot;
        }
        Ok(out)
    }

    pub fn deposit_doorway_trail(&mut self, polygon: usize, edge: usize, amount: f64, tick: i64) {
        if amount <= 0.0 {
            return;
        }
        let cur = self.doorway_trail(polygon, edge, tick);
        self.trail
            .insert((polygon, edge), ((cur + amount).min(TRAIL_CAP), tick));
    }

    pub fn doorway_trail(&self, polygon: usize, edge: usize, tick: i64) -> f64 {
        match self.trail.get(&(polygon, edge)) {
            None => 0.0,
            Some(&(v, t0)) => {
                let dt = (tick - t0) as f64;
                let v = v * 0.5f64.powf(dt / TRAIL_HL_TICKS);
                if v < EPS {
                    0.0
                } else {
                    v
                }
            }
        }
    }

    pub fn step_to(&mut self, tick: i64) -> Result<(), String> {
        while tick - self.last_spread >= SPREAD_DT {
            self.last_spread += SPREAD_DT;
            let t = self.last_spread;
            self.spread_chunk(t)?;
        }
        Ok(())
    }

    fn spread_chunk(&mut self, tick: i64) -> Result<(), String> {
        if self.wet.is_empty() {
            return Ok(());
        }
        // live = sorted(wet | neighbors-of-wet); BTreeSet iterates sorted
        let mut live_set: BTreeSet<usize> = self.wet.clone();
        for &r in &self.wet {
            if r < self.adj.len() {
                for &nb in &self.adj[r] {
                    live_set.insert(nb);
                }
            }
        }
        let live: Vec<usize> = live_set.into_iter().collect();
        let dt_s = SPREAD_DT as f64 / TICK_RATE;
        let mut new_wet: BTreeSet<usize> = BTreeSet::new();
        for kind in 0..NKINDS {
            let (_hl, rate, hop_gain) = SPEC[kind];
            if rate <= 0.0 {
                for &r in &live {
                    self.materialize(kind, r, tick)?;
                    if self.v[kind][r] > 0.0 {
                        new_wet.insert(r);
                    }
                }
                continue;
            }
            for &r in &live {
                self.materialize(kind, r, tick)?;
            }
            let frac = (rate * dt_s).min(0.45);
            if kind == KIND_GARRISON_INTERIOR {
                self.spread_interior(&live, frac, hop_gain, tick)?;
            } else {
                // per-door outflow from a SNAPSHOT (simultaneous update);
                // flows applied in (chamber asc, door order), verbatim
                let mut flows: Vec<(usize, usize, f64)> = Vec::new();
                for &r in &live {
                    let cur = self.v[kind][r];
                    if cur <= 0.0 {
                        continue;
                    }
                    let deg = self.adj[r].len();
                    if deg == 0 {
                        continue;
                    }
                    let per = cur * (frac * deg as f64).min(0.9) / deg as f64;
                    for &nb in &self.adj[r] {
                        flows.push((r, nb, per));
                    }
                }
                for (r, nb, per) in flows {
                    self.v[kind][r] -= per;
                    self.v[kind][nb] += per * hop_gain;
                }
            }
            for &r in &live {
                let v = self.v[kind][r];
                if v < EPS {
                    self.v[kind][r] = 0.0;
                } else {
                    new_wet.insert(r);
                }
            }
        }
        self.wet = new_wet;
        Ok(())
    }

    fn spread_interior(&mut self, live: &[usize], frac: f64, _hop_gain: f64, tick: i64) -> Result<(), String> {
        // two-front rule: >=2 distinct feeding neighbors -> Interior;
        // single-path reach converts to Garrison Reach instead
        let mut gains: BTreeMap<usize, Vec<f64>> = BTreeMap::new();
        let mut outflow: BTreeMap<usize, f64> = BTreeMap::new();
        for &r in live {
            let cur = self.v[KIND_GARRISON_INTERIOR][r];
            if cur <= 0.0 {
                continue;
            }
            let deg = self.adj[r].len();
            if deg == 0 {
                continue;
            }
            let per = cur * (frac * deg as f64).min(0.9) / deg as f64;
            outflow.insert(r, per * deg as f64);
            for &nb in &self.adj[r] {
                gains.entry(nb).or_default().push(per);
            }
        }
        for (&r, &out) in &outflow {
            self.v[KIND_GARRISON_INTERIOR][r] -= out;
        }
        for (&nb, parts) in &gains {
            let total: f64 = parts.iter().sum();
            if parts.len() >= 2 {
                self.v[KIND_GARRISON_INTERIOR][nb] += total;
            } else {
                self.materialize(KIND_GARRISON_REACH, nb, tick)?;
                self.v[KIND_GARRISON_REACH][nb] += total;
            }
        }
        Ok(())
    }

    /// Remove up to `capacity` signal-units TOTAL (all nine fields,
    /// weighted per chamber), proportionally to what is there. Weights
    /// iterate in sorted-chamber order, kinds in declaration order —
    /// the facade's exact pool construction. Returns what was removed.
    pub fn drain(&mut self, polygon_weights: &[(i64, f64)], capacity: f64, tick: i64) -> Result<f64, String> {
        let mut pool: Vec<(usize, usize, f64, f64)> = Vec::new();
        let mut sorted_w: Vec<(i64, f64)> = polygon_weights.to_vec();
        sorted_w.sort_by(|a, b| a.0.cmp(&b.0));
        for (r, wgt) in sorted_w {
            if r < 0 || r as usize >= self.n || wgt <= 0.0 {
                continue;
            }
            for k in 0..NKINDS {
                let v = self.sample(k, r, tick)?;
                if v > 0.0 {
                    pool.push((k, r as usize, v, wgt));
                }
            }
        }
        let weighted: f64 = pool.iter().map(|&(_, _, v, w)| v * w).sum();
        if weighted <= 0.0 || capacity <= 0.0 {
            return Ok(0.0);
        }
        let mut removed = 0.0;
        let scale = (capacity / weighted).min(1.0);
        for (k, r, v, wgt) in pool {
            self.materialize(k, r, tick)?;
            let cut = v * wgt * scale;
            self.v[k][r] = (self.v[k][r] - cut).max(0.0);
            removed += cut;
        }
        Ok(removed)
    }
}
