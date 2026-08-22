//! The platform layer — pygame's replacement. Three independent pieces:
//!
//! - [`AudioMixer`]: cpal output stream + a software mixer whose channel
//!   model matches what the game actually used of pygame.mixer: numbered
//!   channels with `play`/gapless `queue`/`set_volume(l, r)`/`stop`/
//!   `fadeout`/`get_busy`, plus an auto-allocating fire-and-forget SFX
//!   voice pool (pygame's `Sound.play()`). Sounds are raw interleaved
//!   stereo f32 uploaded by Python (file IO and decode stay Python-side).
//!   A missing/failed audio device degrades to silent, exactly like the
//!   old `pygame.mixer.init` failure path.
//! - [`Window`]: winit window pumped from Python's own loop
//!   (`pump_app_events`), softbuffer CPU present of the internal RGB
//!   frame with integer nearest-neighbor scale + letterbox; pointer
//!   coordinates are mapped back into INTERNAL pixels before events
//!   reach Python.
//! - [`write_png`]: capture-frame encode (the record pipeline), GIL-free
//!   rust so a recording can never steal main-loop time again.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::num::NonZeroU32;
use std::sync::{Arc, Mutex};

// ---------------------------------------------------------------------------
// audio
// ---------------------------------------------------------------------------

const SAMPLE_RATE: u32 = 44_100;

struct Voice {
    sound: Arc<Vec<f32>>, // interleaved stereo
    pos: usize,           // frame index
    lvol: f32,
    rvol: f32,
}

struct Chan {
    current: Option<Voice>,
    queued: Option<Arc<Vec<f32>>>,
    loops: i32, // -1 = infinite for `current`
    lvol: f32,
    rvol: f32,
    // fadeout: remaining frames and per-frame volume step (linear, like
    // pygame's fadeout)
    fade_frames: Option<usize>,
    fade_total: usize,
}

#[derive(Default)]
struct MixState {
    sounds: HashMap<u32, Arc<Vec<f32>>>,
    channels: HashMap<u32, Chan>,
    sfx: Vec<Voice>,
    master: f32,
    // lifetime pool telemetry (sfx_stats)
    sfx_played: u64,
    sfx_stolen: u64,
    sfx_dropped: u64,
}

fn mix_into(state: &mut MixState, out: &mut [f32]) {
    for s in out.iter_mut() {
        *s = 0.0;
    }
    let frames = out.len() / 2;
    // SFX pool
    state.sfx.retain_mut(|v| {
        let total = v.sound.len() / 2;
        let n = frames.min(total - v.pos);
        for i in 0..n {
            out[i * 2] += v.sound[(v.pos + i) * 2] * v.lvol;
            out[i * 2 + 1] += v.sound[(v.pos + i) * 2 + 1] * v.rvol;
        }
        v.pos += n;
        v.pos < total
    });
    // numbered channels (music lanes, ambience, heartbeat)
    for ch in state.channels.values_mut() {
        let mut i = 0usize;
        while i < frames {
            let Some(v) = ch.current.as_mut() else { break };
            let total = v.sound.len() / 2;
            let left = total - v.pos;
            let n = (frames - i).min(left);
            let (mut fl, mut fr) = (ch.lvol, ch.rvol);
            for j in 0..n {
                if let Some(ff) = ch.fade_frames {
                    let k = ff.saturating_sub(1) as f32 / ch.fade_total.max(1) as f32;
                    fl = ch.lvol * k;
                    fr = ch.rvol * k;
                    ch.fade_frames = Some(ff.saturating_sub(1));
                }
                out[(i + j) * 2] += v.sound[(v.pos + j) * 2] * fl;
                out[(i + j) * 2 + 1] += v.sound[(v.pos + j) * 2 + 1] * fr;
            }
            v.pos += n;
            i += n;
            if ch.fade_frames == Some(0) {
                ch.current = None;
                ch.queued = None;
                ch.fade_frames = None;
                break;
            }
            if v.pos >= total {
                // chunk finished: gapless hand-off to the queued chunk,
                // else loop, else stop
                if let Some(next) = ch.queued.take() {
                    ch.current = Some(Voice {
                        sound: next,
                        pos: 0,
                        lvol: 1.0,
                        rvol: 1.0,
                    });
                } else if ch.loops != 0 {
                    if ch.loops > 0 {
                        ch.loops -= 1;
                    }
                    if let Some(v) = ch.current.as_mut() {
                        v.pos = 0;
                    }
                } else {
                    ch.current = None;
                }
            }
        }
    }
    let m = state.master;
    for s in out.iter_mut() {
        *s = (*s * m).clamp(-1.0, 1.0);
    }
}

#[pyclass(unsendable)]
pub struct AudioMixer {
    state: Arc<Mutex<MixState>>,
    // holds the cpal stream alive; None = no device, silent
    _stream: Option<cpal::Stream>,
    ready: bool,
}

#[pymethods]
impl AudioMixer {
    #[new]
    fn new() -> Self {
        use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
        let state = Arc::new(Mutex::new(MixState {
            master: 1.0,
            ..Default::default()
        }));
        let mut stream_out = None;
        let host = cpal::default_host();
        if let Some(device) = host.default_output_device() {
            let config = cpal::StreamConfig {
                channels: 2,
                sample_rate: cpal::SampleRate(SAMPLE_RATE),
                buffer_size: cpal::BufferSize::Default,
            };
            let st = state.clone();
            match device.build_output_stream(
                &config,
                move |out: &mut [f32], _| {
                    let mut s = st.lock().unwrap();
                    mix_into(&mut s, out);
                },
                |_err| {},
                None,
            ) {
                Ok(stream) => {
                    if stream.play().is_ok() {
                        stream_out = Some(stream);
                    }
                }
                Err(_) => {}
            }
        }
        let ready = stream_out.is_some();
        AudioMixer {
            state,
            _stream: stream_out,
            ready,
        }
    }

    #[getter]
    fn ready(&self) -> bool {
        self.ready
    }

    /// Upload interleaved STEREO f32 samples at 44100 Hz (bytes of f32 LE).
    fn load_sound(&self, id: u32, data: Vec<u8>) -> PyResult<()> {
        if data.len() % 8 != 0 {
            return Err(PyValueError::new_err(
                "load_sound: data must be interleaved stereo f32 pairs",
            ));
        }
        let mut samples = Vec::with_capacity(data.len() / 4);
        for c in data.chunks_exact(4) {
            samples.push(f32::from_le_bytes([c[0], c[1], c[2], c[3]]));
        }
        self.state
            .lock()
            .unwrap()
            .sounds
            .insert(id, Arc::new(samples));
        Ok(())
    }

    fn free_sound(&self, id: u32) {
        self.state.lock().unwrap().sounds.remove(&id);
    }

    /// Fire-and-forget SFX voice (pygame `Sound.play()` + channel pan).
    /// Capped at 24 concurrent voices. The cap exists because unbounded
    /// voices measured 2.3-3.7x full-scale peaks and hundreds of clip
    /// bursts per session (gate run 50); 24 (vs pygame's 12) because a
    /// busy fight sends ~27 audible sounds/s and at 12 even perfect
    /// arbitration voiced only 28% of enemy deaths (run-51 watch item,
    /// measured unmuted). Unlike pygame (which dropped the NEW sound),
    /// a full pool steals the quietest voice when the newcomer is
    /// louder — the audible mix keeps the loud event, not the early
    /// one. Returns true if the sound got a voice.
    fn sfx_play(&self, id: u32, lvol: f32, rvol: f32) -> bool {
        let mut s = self.state.lock().unwrap();
        let Some(snd) = s.sounds.get(&id).cloned() else {
            return false;
        };
        if s.sfx.len() >= 24 {
            let newcomer = lvol + rvol;
            let (qi, qv) = s
                .sfx
                .iter()
                .enumerate()
                .map(|(i, v)| (i, v.lvol + v.rvol))
                .min_by(|a, b| a.1.total_cmp(&b.1))
                .unwrap();
            if newcomer <= qv {
                s.sfx_dropped += 1;
                return false;
            }
            s.sfx.remove(qi);
            s.sfx_stolen += 1;
        }
        s.sfx.push(Voice {
            sound: snd,
            pos: 0,
            lvol,
            rvol,
        });
        s.sfx_played += 1;
        true
    }

    /// Live SFX voice count (test introspection for the pool cap).
    fn sfx_active(&self) -> usize {
        self.state.lock().unwrap().sfx.len()
    }

    /// Lifetime (played, stolen, dropped) counters for the SFX pool —
    /// the instrument run 51 asked for: the film's event tap fires
    /// before arbitration, so only these counters can say what a
    /// player actually heard.
    fn sfx_stats(&self) -> (u64, u64, u64) {
        let s = self.state.lock().unwrap();
        (s.sfx_played, s.sfx_stolen, s.sfx_dropped)
    }

    #[pyo3(signature = (ch, id, loops = 0))]
    fn ch_play(&self, ch: u32, id: u32, loops: i32) {
        let mut s = self.state.lock().unwrap();
        let Some(snd) = s.sounds.get(&id).cloned() else {
            return;
        };
        let entry = s.channels.entry(ch).or_insert_with(|| Chan {
            current: None,
            queued: None,
            loops: 0,
            lvol: 1.0,
            rvol: 1.0,
            fade_frames: None,
            fade_total: 0,
        });
        entry.current = Some(Voice {
            sound: snd,
            pos: 0,
            lvol: 1.0,
            rvol: 1.0,
        });
        entry.queued = None;
        entry.loops = loops;
        entry.fade_frames = None;
    }

    fn ch_queue(&self, ch: u32, id: u32) {
        let mut s = self.state.lock().unwrap();
        let Some(snd) = s.sounds.get(&id).cloned() else {
            return;
        };
        if let Some(entry) = s.channels.get_mut(&ch) {
            if entry.current.is_none() {
                // pygame parity: queue on an IDLE channel starts playing
                // immediately — without this, a stopped lane that only
                // ever queues (all of music.py) stays silent forever
                // (gate run 50: PRAYER died after mute->unmute)
                entry.current = Some(Voice {
                    sound: snd,
                    pos: 0,
                    lvol: 1.0,
                    rvol: 1.0,
                });
                entry.loops = 0;
                entry.fade_frames = None;
            } else {
                entry.queued = Some(snd);
            }
        } else {
            // queue to a never-touched channel: same start-now semantics
            s.channels.insert(
                ch,
                Chan {
                    current: Some(Voice {
                        sound: snd,
                        pos: 0,
                        lvol: 1.0,
                        rvol: 1.0,
                    }),
                    queued: None,
                    loops: 0,
                    lvol: 1.0,
                    rvol: 1.0,
                    fade_frames: None,
                    fade_total: 0,
                },
            );
        }
    }

    /// True if a chunk is queued behind the playing one (`get_queue()`
    /// is-None check in the lanes).
    fn ch_has_queue(&self, ch: u32) -> bool {
        self.state
            .lock()
            .unwrap()
            .channels
            .get(&ch)
            .map(|c| c.queued.is_some())
            .unwrap_or(false)
    }

    fn ch_set_volume(&self, ch: u32, l: f32, r: f32) {
        let mut s = self.state.lock().unwrap();
        let entry = s.channels.entry(ch).or_insert_with(|| Chan {
            current: None,
            queued: None,
            loops: 0,
            lvol: 1.0,
            rvol: 1.0,
            fade_frames: None,
            fade_total: 0,
        });
        entry.lvol = l;
        entry.rvol = r;
    }

    fn ch_stop(&self, ch: u32) {
        if let Some(entry) = self.state.lock().unwrap().channels.get_mut(&ch) {
            entry.current = None;
            entry.queued = None;
            entry.fade_frames = None;
        }
    }

    fn ch_fadeout(&self, ch: u32, ms: u32) {
        if let Some(entry) = self.state.lock().unwrap().channels.get_mut(&ch) {
            if entry.current.is_some() {
                let frames = (ms as usize * SAMPLE_RATE as usize) / 1000;
                entry.fade_frames = Some(frames.max(1));
                entry.fade_total = frames.max(1);
            }
        }
    }

    fn ch_busy(&self, ch: u32) -> bool {
        self.state
            .lock()
            .unwrap()
            .channels
            .get(&ch)
            .map(|c| c.current.is_some())
            .unwrap_or(false)
    }

    fn set_master(&self, v: f32) {
        self.state.lock().unwrap().master = v.clamp(0.0, 1.0);
    }

    fn stop_all(&self) {
        let mut s = self.state.lock().unwrap();
        s.sfx.clear();
        for c in s.channels.values_mut() {
            c.current = None;
            c.queued = None;
            c.fade_frames = None;
        }
    }
}

// ---------------------------------------------------------------------------
// window / present / events
// ---------------------------------------------------------------------------

use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, EventLoop};
use winit::platform::pump_events::EventLoopExtPumpEvents;
use winit::window::Window as WinitWindow;

#[derive(Default)]
struct App {
    window: Option<Arc<WinitWindow>>,
    events: Vec<PyEvent>,
    cursor: (i64, i64),
    title: String,
    start_w: u32,
    start_h: u32,
    fullscreen: bool,
}

/// (kind, a, b, c, name, text) — Python's uievent maps these:
/// kind 0=close 1=keydown(a=repeat) 2=keyup 3=motion(a=x, b=y)
/// 4=buttondown(a=button, b=x, c=y) 5=buttonup 6=wheel(a=dx, b=dy)
/// 7=resize(a=w, b=h). `name` is the winit PhysicalKey debug name
/// ("KeyW", "Escape", ...) — stable across builds, unlike discriminants.
type PyEvent = (u32, i64, i64, i64, String, String);

impl ApplicationHandler for App {
    fn resumed(&mut self, el: &ActiveEventLoop) {
        if self.window.is_none() {
            let mut attrs = WinitWindow::default_attributes()
                .with_title(self.title.clone())
                .with_inner_size(winit::dpi::PhysicalSize::new(self.start_w, self.start_h));
            if self.fullscreen {
                attrs = attrs.with_fullscreen(Some(winit::window::Fullscreen::Borderless(None)));
            }
            self.window = Some(Arc::new(el.create_window(attrs).expect("create window")));
        }
    }

    fn window_event(
        &mut self,
        _el: &ActiveEventLoop,
        _id: winit::window::WindowId,
        event: WindowEvent,
    ) {
        match event {
            WindowEvent::CloseRequested => {
                self.events.push((0, 0, 0, 0, String::new(), String::new()))
            }
            WindowEvent::KeyboardInput { event, .. } => {
                let kind = if event.state == ElementState::Pressed {
                    1
                } else {
                    2
                };
                let name = match event.physical_key {
                    winit::keyboard::PhysicalKey::Code(c) => format!("{c:?}"),
                    winit::keyboard::PhysicalKey::Unidentified(_) => String::new(),
                };
                let text = event.text.map(|t| t.to_string()).unwrap_or_default();
                let repeat = if event.repeat { 1 } else { 0 };
                self.events.push((kind, repeat, 0, 0, name, text));
            }
            WindowEvent::CursorMoved { position, .. } => {
                self.cursor = (position.x as i64, position.y as i64);
                self.events.push((
                    3,
                    position.x as i64,
                    position.y as i64,
                    0,
                    String::new(),
                    String::new(),
                ));
            }
            WindowEvent::MouseInput { state, button, .. } => {
                let kind = if state == ElementState::Pressed { 4 } else { 5 };
                let b = match button {
                    winit::event::MouseButton::Left => 1,
                    winit::event::MouseButton::Middle => 2,
                    winit::event::MouseButton::Right => 3,
                    winit::event::MouseButton::Back => 6,
                    winit::event::MouseButton::Forward => 7,
                    winit::event::MouseButton::Other(n) => 8 + n as i64,
                };
                self.events.push((
                    kind,
                    b,
                    self.cursor.0,
                    self.cursor.1,
                    String::new(),
                    String::new(),
                ));
            }
            WindowEvent::MouseWheel { delta, .. } => {
                let (dx, dy) = match delta {
                    MouseScrollDelta::LineDelta(x, y) => (x as i64, y as i64),
                    MouseScrollDelta::PixelDelta(p) => {
                        (p.x.signum() as i64, p.y.signum() as i64)
                    }
                };
                self.events.push((6, dx, dy, 0, String::new(), String::new()));
            }
            WindowEvent::Resized(size) => {
                self.events.push((
                    7,
                    size.width as i64,
                    size.height as i64,
                    0,
                    String::new(),
                    String::new(),
                ));
            }
            _ => {}
        }
    }
}

#[pyclass(unsendable)]
pub struct Window {
    event_loop: EventLoop<()>,
    app: App,
    context: Option<softbuffer::Context<Arc<WinitWindow>>>,
    surface: Option<softbuffer::Surface<Arc<WinitWindow>, Arc<WinitWindow>>>,
    // present mapping (window px -> internal px), updated per present
    scale: u32,
    off_x: u32,
    off_y: u32,
}

#[pymethods]
impl Window {
    #[new]
    #[pyo3(signature = (width, height, title = "PERIHELION", fullscreen = false))]
    fn new(width: u32, height: u32, title: &str, fullscreen: bool) -> PyResult<Self> {
        let event_loop = EventLoop::new()
            .map_err(|e| PyValueError::new_err(format!("winit event loop: {e}")))?;
        let app = App {
            title: title.to_string(),
            start_w: width,
            start_h: height,
            fullscreen,
            ..Default::default()
        };
        Ok(Window {
            event_loop,
            app,
            context: None,
            surface: None,
            scale: 1,
            off_x: 0,
            off_y: 0,
        })
    }

    /// Pump pending OS events; returns event tuples (see PyEvent). Pointer
    /// coordinates arrive in WINDOW pixels here and are mapped to internal
    /// pixels using the last present()'s scale/offset.
    fn pump(&mut self) -> Vec<PyEvent> {
        use std::time::Duration;
        let _ = self
            .event_loop
            .pump_app_events(Some(Duration::ZERO), &mut self.app);
        let mut out = std::mem::take(&mut self.app.events);
        let (s, ox, oy) = (self.scale.max(1) as i64, self.off_x as i64, self.off_y as i64);
        for ev in out.iter_mut() {
            if ev.0 == 3 {
                ev.1 = (ev.1 - ox).div_euclid(s);
                ev.2 = (ev.2 - oy).div_euclid(s);
            } else if ev.0 == 4 || ev.0 == 5 {
                ev.2 = (ev.2 - ox).div_euclid(s);
                ev.3 = (ev.3 - oy).div_euclid(s);
            }
        }
        out
    }

    /// Present the internal RGBA frame (row-major, w*h*4 — the
    /// renderer's own snapshot buffer, alpha ignored) scaled by the
    /// largest integer factor that fits, centered (letterboxed black).
    #[pyo3(signature = (rgb, w, h, shake_x = 0, shake_y = 0))]
    fn present(&mut self, rgb: Vec<u8>, w: u32, h: u32, shake_x: i64, shake_y: i64) -> PyResult<()> {
        let Some(window) = self.app.window.clone() else {
            return Ok(()); // window not created yet (pump once first)
        };
        if rgb.len() != (w * h * 4) as usize {
            return Err(PyValueError::new_err("present: rgba size mismatch"));
        }
        if self.context.is_none() {
            let ctx = softbuffer::Context::new(window.clone())
                .map_err(|e| PyValueError::new_err(format!("softbuffer: {e}")))?;
            let surface = softbuffer::Surface::new(&ctx, window.clone())
                .map_err(|e| PyValueError::new_err(format!("softbuffer surface: {e}")))?;
            self.context = Some(ctx);
            self.surface = Some(surface);
        }
        let size = window.inner_size();
        let (ww, wh) = (size.width.max(1), size.height.max(1));
        let surface = self.surface.as_mut().unwrap();
        surface
            .resize(NonZeroU32::new(ww).unwrap(), NonZeroU32::new(wh).unwrap())
            .map_err(|e| PyValueError::new_err(format!("surface resize: {e}")))?;
        let scale = (ww / w).min(wh / h).max(1);
        let (dw, dh) = (w * scale, h * scale);
        // shake rides the destination offset (the old blit-offset path),
        // scaled to window pixels and clamped so the frame stays on-surface
        let base_x = (ww.saturating_sub(dw)) as i64 / 2;
        let base_y = (wh.saturating_sub(dh)) as i64 / 2;
        let max_x = ww.saturating_sub(dw.min(ww)) as i64;
        let max_y = wh.saturating_sub(dh.min(wh)) as i64;
        let off_x = (base_x + shake_x * scale as i64).clamp(0, max_x) as u32;
        let off_y = (base_y + shake_y * scale as i64).clamp(0, max_y) as u32;
        self.scale = scale;
        self.off_x = off_x;
        self.off_y = off_y;
        let mut buf = surface
            .buffer_mut()
            .map_err(|e| PyValueError::new_err(format!("surface buffer: {e}")))?;
        buf.fill(0);
        for y in 0..dh.min(wh.saturating_sub(off_y)) {
            let sy = (y / scale) as usize;
            let dst_row = ((y + off_y) * ww + off_x) as usize;
            let src_row = sy * w as usize * 4;
            for x in 0..dw.min(ww.saturating_sub(off_x)) {
                let sx = (x / scale) as usize;
                let i = src_row + sx * 4;
                let px = ((rgb[i] as u32) << 16)
                    | ((rgb[i + 1] as u32) << 8)
                    | rgb[i + 2] as u32;
                buf[dst_row + x as usize] = px;
            }
        }
        buf.present()
            .map_err(|e| PyValueError::new_err(format!("present: {e}")))?;
        Ok(())
    }

    fn set_title(&self, title: &str) {
        if let Some(w) = &self.app.window {
            w.set_title(title);
        }
    }

    fn set_fullscreen(&self, on: bool) {
        if let Some(w) = &self.app.window {
            w.set_fullscreen(if on {
                Some(winit::window::Fullscreen::Borderless(None))
            } else {
                None
            });
        }
    }
}

// ---------------------------------------------------------------------------
// capture encode
// ---------------------------------------------------------------------------

/// Encode an RGB frame to a PNG file — GIL-free once the bytes are in.
#[pyfunction]
pub fn write_png(py: Python<'_>, path: &str, w: u32, h: u32, rgb: Vec<u8>) -> PyResult<()> {
    if rgb.len() != (w * h * 3) as usize {
        return Err(PyValueError::new_err("write_png: rgb size mismatch"));
    }
    let path = path.to_string();
    py.allow_threads(move || {
        let file = std::fs::File::create(&path)
            .map_err(|e| PyValueError::new_err(format!("write_png: {e}")))?;
        let wtr = std::io::BufWriter::new(file);
        let mut enc = png::Encoder::new(wtr, w, h);
        enc.set_color(png::ColorType::Rgb);
        enc.set_depth(png::BitDepth::Eight);
        let mut writer = enc
            .write_header()
            .map_err(|e| PyValueError::new_err(format!("write_png: {e}")))?;
        writer
            .write_image_data(&rgb)
            .map_err(|e| PyValueError::new_err(format!("write_png: {e}")))?;
        Ok(())
    })
}
