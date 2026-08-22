//! Capture encode — a real video codec in the engine.
//!
//! Before this, "recording" meant one PNG per frame plus an ffmpeg
//! invocation afterwards: thousands of files per session, a second pass
//! over all of them, and every tool that wanted a video had to know the
//! ffmpeg incantation. The frames were also the only artifact, so a
//! capture that was never assembled left a directory of stills nobody
//! could play.
//!
//! [`VideoRecorder`] takes RGB frames and writes a playable .mp4. AV1 at
//! 4:4:4 through rav1e (see `av1.rs` for the measurements that chose
//! it), AAC for sound, muxed by `mp4.rs`. The encode runs with the GIL
//! released, so a recording cannot steal main-loop time — the same rule
//! [`super::platform::write_png`] already follows.
//!
//! The recorder owns no timing. It writes the frames it is given at the
//! declared frame rate, so the caller decides what a frame means (see
//! the sim-clock record path: the app records on the sim's clock and
//! `--fps` is only a meter).

use crate::h264::H264Encoder;
use crate::mp4::{self, Sample, Track, TrackKind, VideoCodec};
use minimp4::enc::{BitRate, Encoder as AacEncoder, EncoderParams};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

fn enc_err<E: std::fmt::Display>(what: &str) -> impl FnOnce(E) -> PyErr + '_ {
    move |e| PyValueError::new_err(format!("VideoRecorder: {what}: {e}"))
}

/// Marks our top-level `uuid` box. Sixteen bytes, and readable in a hex
/// dump on purpose: "PERIHELIONRPLY01".
const SIDECAR_UUID: [u8; 16] = *b"PERIHELIONRPLY01";

/// The HQ profile: what a demo or a review clip is encoded at. Full
/// resolution and frame rate are the caller's to pass; this is the
/// quality end of the one dial that differs between profiles.
const HQ_CRF: u8 = 18;
const HQ_PRESET: &str = "veryfast";

/// The TELEMETRY profile: recording all the time, so it must stay many
/// times faster than realtime. Measured at 854x480@20 on real footage:
/// 14x realtime and 0.4 MB/min, against rav1e's 0.38x and 0.6 MB/min.
/// The resolution and frame rate belong to the caller — two thirds and
/// 20 Hz is the ratified setting — and this is the bitrate end of it.
const TELEMETRY_CRF: u8 = 30;
const TELEMETRY_PRESET: &str = "veryfast";

/// Audio bitrate per profile. This is NOT a detail: at 128 kbit/s the
/// soundtrack costs about 0.96 MB/min, against a telemetry video stream
/// of roughly 0.4 MB/min — the sound would be two and a half times the
/// picture, and the cheap profile would not be cheap. 48 kbit/s is
/// still plainly intelligible for working out what a player heard.
const HQ_AUDIO_BPS: u32 = 128_000;
const TELEMETRY_AUDIO_BPS: u32 = 48_000;

/// One AAC access unit covers 1024 samples per channel.
const AAC_FRAME: usize = 1024;

/// Walk the top-level boxes of an ISO-BMFF file, calling `f` with the
/// type and body of each. Sizes are the 32-bit form unless the box says
/// otherwise (`1` = 64-bit largesize, `0` = extends to end of file).
fn for_each_box(buf: &[u8], mut f: impl FnMut(&[u8; 4], &[u8])) {
    let mut off = 0usize;
    while off + 8 <= buf.len() {
        let size32 = u32::from_be_bytes([buf[off], buf[off + 1], buf[off + 2], buf[off + 3]]);
        let mut kind = [0u8; 4];
        kind.copy_from_slice(&buf[off + 4..off + 8]);
        let (header, size) = match size32 {
            0 => (8usize, buf.len() - off),
            1 => {
                if off + 16 > buf.len() {
                    return;
                }
                let mut s = [0u8; 8];
                s.copy_from_slice(&buf[off + 8..off + 16]);
                (16usize, u64::from_be_bytes(s) as usize)
            }
            n => (8usize, n as usize),
        };
        if size < header || off + size > buf.len() {
            return;
        }
        f(&kind, &buf[off + header..off + size]);
        off += size;
    }
}

/// An open recording. Frames in, one .mp4 out.
///
/// The whole stream is built in memory and flushed to disk by `finish`,
/// because the sample tables have to be written after the sample data
/// they describe. It also keeps a half-written file off disk if a
/// capture dies part way (gate run 64 truncated four captures at ~1700
/// of 2880 frames, and a partial PNG directory looks exactly like a
/// complete one).
#[pyclass]
pub struct VideoRecorder {
    encoder: Option<H264Encoder>,
    /// Encoded access units, one per frame.
    samples: Vec<Sample>,
    open: bool,
    path: PathBuf,
    width: u32,
    height: u32,
    fps: u32,
    frames: u64,
    audio_bps: u32,
    /// Interleaved signed-16-bit little-endian PCM for the whole
    /// recording. AAC is encoded in one pass at mux time, so this
    /// accumulates.
    pcm: Vec<u8>,
    audio_rate: u32,
    audio_channels: u32,
    /// `(name, bytes)` blobs written as top-level `uuid` boxes.
    sidecars: Vec<(String, Vec<u8>)>,
}

#[pymethods]
impl VideoRecorder {
    /// Open a recording. `width` and `height` must both be even — chroma
    /// is subsampled by two in most formats, and an odd dimension is a
    /// silent corruption rather than an error further down.
    ///
    /// `profile` is `"hq"` or `"telemetry"`. It sets the quality/speed
    /// end only — the caller still passes the resolution and frame rate,
    /// because a profile that silently rescaled its input would make the
    /// recorder disagree with the frames it was handed.
    #[new]
    #[pyo3(signature = (path, width, height, fps=60, profile="hq"))]
    fn new(
        path: &str,
        width: u32,
        height: u32,
        fps: u32,
        profile: &str,
    ) -> PyResult<Self> {
        let (crf, preset) = match profile {
            "hq" => (HQ_CRF, HQ_PRESET),
            "telemetry" => (TELEMETRY_CRF, TELEMETRY_PRESET),
            other => {
                return Err(PyValueError::new_err(format!(
                    "VideoRecorder: profile must be \"hq\" or \"telemetry\", got {other:?}"
                )))
            }
        };
        if width == 0 || height == 0 || width % 2 != 0 || height % 2 != 0 {
            return Err(PyValueError::new_err(format!(
                "VideoRecorder: width/height must be positive and even, got {width}x{height}"
            )));
        }
        if fps == 0 {
            return Err(PyValueError::new_err("VideoRecorder: fps must be > 0"));
        }
        let audio_bps = match profile {
            "telemetry" => TELEMETRY_AUDIO_BPS,
            _ => HQ_AUDIO_BPS,
        };
        let raw = PathBuf::from(path).with_extension("h264.tmp");
        let encoder = H264Encoder::new(width, height, fps, crf, preset, raw)?;
        Ok(Self {
            encoder: Some(encoder),
            samples: Vec::new(),
            open: true,
            path: PathBuf::from(path),
            width,
            height,
            fps,
            frames: 0,
            audio_bps,
            pcm: Vec::new(),
            audio_rate: 0,
            audio_channels: 0,
            sidecars: Vec::new(),
        })
    }

    /// Encode one RGB24 frame. `rgb` is `width * height * 3` bytes.
    fn add_frame(&mut self, py: Python<'_>, rgb: Vec<u8>) -> PyResult<()> {
        let want = (self.width as usize) * (self.height as usize) * 3;
        if rgb.len() != want {
            return Err(PyValueError::new_err(format!(
                "VideoRecorder.add_frame: expected {want} bytes for {}x{}, got {}",
                self.width,
                self.height,
                rgb.len()
            )));
        }
        let encoder = self
            .encoder
            .as_mut()
            .ok_or_else(|| PyValueError::new_err("VideoRecorder: already finished"))?;
        py.allow_threads(|| encoder.encode(&rgb))?;
        self.frames += 1;
        Ok(())
    }

    /// Give the recording a soundtrack: interleaved signed-16-bit
    /// little-endian PCM covering the whole clip. Call before `finish`.
    ///
    /// This is a set, not a feed, because the audio is encoded in one
    /// pass over the complete stream — pretending to stream it would
    /// just be this buffer with extra steps.
    #[pyo3(signature = (pcm, sample_rate=44100, channels=2))]
    fn set_audio(&mut self, pcm: Vec<u8>, sample_rate: u32, channels: u32) -> PyResult<()> {
        if channels != 1 && channels != 2 {
            return Err(PyValueError::new_err(format!(
                "VideoRecorder.set_audio: channels must be 1 or 2, got {channels}"
            )));
        }
        if sample_rate == 0 {
            return Err(PyValueError::new_err(
                "VideoRecorder.set_audio: sample_rate must be > 0",
            ));
        }
        let frame = 2 * channels as usize;
        if pcm.len() % frame != 0 {
            return Err(PyValueError::new_err(format!(
                "VideoRecorder.set_audio: {} bytes is not a whole number of \
                 {channels}-channel i16 samples",
                pcm.len()
            )));
        }
        self.pcm = pcm;
        self.audio_rate = sample_rate;
        self.audio_channels = channels;
        Ok(())
    }

    /// Attach an arbitrary named blob to the file.
    ///
    /// It rides along as a top-level `uuid` box, which is ISO-BMFF's own
    /// extension point: every player walks the top-level boxes and skips
    /// the types it does not know, so the file stays an ordinary .mp4 that
    /// opens anywhere, while carrying enough of the run to rebuild the
    /// scene it shows. Compression is the caller's business — keeping it
    /// out here is what lets the engine stay dependency-free.
    fn set_sidecar(&mut self, name: &str, data: Vec<u8>) -> PyResult<()> {
        if name.is_empty() || name.len() > 255 {
            return Err(PyValueError::new_err(
                "VideoRecorder.set_sidecar: name must be 1..=255 bytes",
            ));
        }
        self.sidecars.retain(|(n, _)| n != name);
        self.sidecars.push((name.to_string(), data));
        Ok(())
    }

    /// Close the stream and write the file. Safe to call more than once.
    fn finish(&mut self, py: Python<'_>) -> PyResult<()> {
        if !self.open {
            return Ok(());
        }
        self.open = false;
        let mut encoder = match self.encoder.take() {
            Some(e) => e,
            None => return Ok(()),
        };
        let (packets, config) = encoder.finish()?;
        for p in packets {
            self.samples.push(Sample { data: p.data, is_sync: p.is_key });
        }
        // The clip must be exactly as long as the tick stream it claims
        // to document. A capture that quietly holds back a frame slides
        // every later event earlier in time, which is how a judge ends
        // up measuring the wrong tick.
        if self.samples.len() as u64 != self.frames {
            return Err(PyValueError::new_err(format!(
                "VideoRecorder: encoder returned {} packets for {} frames — \
                 refusing to write a clip that disagrees with its input",
                self.samples.len(),
                self.frames
            )));
        }
        let samples = std::mem::take(&mut self.samples);
        let pcm = std::mem::take(&mut self.pcm);
        let sidecars = std::mem::take(&mut self.sidecars);
        let (w, h, fps) = (self.width as u16, self.height as u16, self.fps);
        let (rate, channels) = (self.audio_rate, self.audio_channels);
        let audio_bps = self.audio_bps;
        let path = self.path.clone();

        py.allow_threads(move || -> PyResult<()> {
            let mut tracks = vec![Track {
                samples,
                timescale: fps,
                sample_delta: 1,
                kind: TrackKind::Video {
                    width: w,
                    height: h,
                    config,
                    codec: VideoCodec::H264,
                },
            }];
            if !pcm.is_empty() {
                tracks.push(aac_track(&pcm, rate, channels, audio_bps)?);
            }
            let mut bytes = mp4::write(&tracks);
            for (name, data) in &sidecars {
                let body_len = 4 + name.len() + 8 + data.len();
                let size = 8 + 16 + body_len;
                let size32: u32 = size.try_into().map_err(|_| {
                    PyValueError::new_err(format!(
                        "VideoRecorder: sidecar {name:?} is too large for one box ({size} bytes)"
                    ))
                })?;
                bytes.extend_from_slice(&size32.to_be_bytes());
                bytes.extend_from_slice(b"uuid");
                bytes.extend_from_slice(&SIDECAR_UUID);
                bytes.extend_from_slice(&(name.len() as u32).to_be_bytes());
                bytes.extend_from_slice(name.as_bytes());
                bytes.extend_from_slice(&(data.len() as u64).to_be_bytes());
                bytes.extend_from_slice(data);
            }
            if let Some(dir) = path.parent() {
                std::fs::create_dir_all(dir).map_err(enc_err("create output directory"))?;
            }
            let mut file = File::create(&path).map_err(enc_err("create output file"))?;
            file.write_all(&bytes).map_err(enc_err("write output file"))?;
            file.flush().map_err(enc_err("flush output file"))?;
            Ok(())
        })
    }

    /// The number of frames encoded so far.
    #[getter]
    fn frames(&self) -> u64 {
        self.frames
    }

    #[getter]
    fn width(&self) -> u32 {
        self.width
    }

    #[getter]
    fn height(&self) -> u32 {
        self.height
    }

    #[getter]
    fn fps(&self) -> u32 {
        self.fps
    }

    /// Context-manager support, so a capture cannot leave the file
    /// unwritten when the caller raises part way through.
    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    #[pyo3(signature = (_exc_type=None, _exc=None, _tb=None))]
    fn __exit__(
        &mut self,
        py: Python<'_>,
        _exc_type: Option<PyObject>,
        _exc: Option<PyObject>,
        _tb: Option<PyObject>,
    ) -> PyResult<bool> {
        self.finish(py)?;
        Ok(false)
    }
}

/// Encode the whole PCM buffer to AAC-LC and describe it as a track.
///
/// The encoder is minimp4's vendored fdk-AAC driven directly rather than
/// through its muxer, which only knows how to attach audio to an H.264
/// stream. Transport is raw (no ADTS headers): MP4 carries the setup in
/// the sample entry, and a stream with ADTS headers inside it plays as
/// noise in some players and not at all in others.
fn aac_track(pcm: &[u8], rate: u32, channels: u32, bps: u32) -> PyResult<Track> {
    let enc = AacEncoder::new(EncoderParams {
        bit_rate: BitRate::Cbr(bps),
        sample_rate: rate,
        channel_count: channels,
    })
    .map_err(|e| PyValueError::new_err(format!("VideoRecorder: aac init: {e:?}")))?;
    let info = enc
        .info()
        .map_err(|e| PyValueError::new_err(format!("VideoRecorder: aac info: {e:?}")))?;
    let asc = info.confBuf[..info.confSize as usize].to_vec();

    let per_frame = AAC_FRAME * channels as usize;
    let total = pcm.len() / 2;
    let mut pcm16 = vec![0i16; total];
    for (i, out) in pcm16.iter_mut().enumerate() {
        *out = i16::from_le_bytes([pcm[i * 2], pcm[i * 2 + 1]]);
    }
    let mut samples = Vec::new();
    let mut out = vec![0u8; per_frame * 2 + 1024];
    let mut at = 0usize;
    while at < pcm16.len() {
        let end = (at + per_frame).min(pcm16.len());
        let mut chunk = pcm16[at..end].to_vec();
        chunk.resize(per_frame, 0); // pad the tail rather than drop it
        let got = enc
            .encode(&chunk, &mut out)
            .map_err(|e| PyValueError::new_err(format!("VideoRecorder: aac encode: {e:?}")))?;
        if got.output_size > 0 {
            samples.push(Sample { data: out[..got.output_size].to_vec(), is_sync: true });
        }
        at = end;
    }
    Ok(Track {
        samples,
        timescale: rate,
        sample_delta: AAC_FRAME as u32,
        kind: TrackKind::Audio { channels: channels as u16, sample_rate: rate, config: asc },
    })
}

/// Every sidecar blob in `path`, as `(name, bytes)`, in write order.
///
/// The counterpart to [`VideoRecorder::set_sidecar`]: this is what makes
/// a recording a replay rather than a picture of one.
#[pyfunction]
pub fn read_sidecars(py: Python<'_>, path: &str) -> PyResult<Vec<(String, Vec<u8>)>> {
    let path = PathBuf::from(path);
    py.allow_threads(move || {
        let buf = std::fs::read(&path).map_err(enc_err("read file"))?;
        let mut found = Vec::new();
        for_each_box(&buf, |kind, body| {
            if kind != b"uuid" || body.len() < 16 + 4 || body[..16] != SIDECAR_UUID {
                return;
            }
            let body = &body[16..];
            let nlen = u32::from_be_bytes([body[0], body[1], body[2], body[3]]) as usize;
            if body.len() < 4 + nlen + 8 {
                return;
            }
            let name = match std::str::from_utf8(&body[4..4 + nlen]) {
                Ok(s) => s.to_string(),
                Err(_) => return,
            };
            let rest = &body[4 + nlen..];
            let mut dl = [0u8; 8];
            dl.copy_from_slice(&rest[..8]);
            let dlen = u64::from_be_bytes(dl) as usize;
            if rest.len() < 8 + dlen {
                return;
            }
            found.push((name, rest[8..8 + dlen].to_vec()));
        });
        Ok(found)
    })
}
