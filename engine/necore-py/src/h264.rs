//! H.264 encode by driving x264 as a child process.
//!
//! **Why a separate process and not a linked library.** x264 is GPL, and
//! linking it would put the whole game under the GPL. Running it as its
//! own program, fed over a pipe, is the ordinary boundary: the GPL
//! covers that executable (ship its source and licence with it) and the
//! game stays a separate work.
//!
//! **Why x264 and not the AV1 encoder this replaced.** Telemetry means
//! recording ALL THE TIME, so the encoder has to run many times faster
//! than realtime or it is not an option at any quality. Measured on real
//! footage at the telemetry profile (854x480@20):
//!
//! | encoder                  | speed  | size       |
//! |--------------------------|--------|------------|
//! | x264 veryfast 4:4:4 cf30 | 14.0x  | 0.4 MB/min |
//! | x264 ultrafast 4:4:4     | 18.6x  | 1.5 MB/min |
//! | rav1e q150 speed 10      |  0.38x | 0.6 MB/min |
//!
//! AV1's one advantage was bytes and at this profile it does not even
//! have that, while being 37x too slow. One encoder with two profiles
//! beats two pipelines.
//!
//! 4:4:4 throughout, and not for purity: it measured FASTER than 4:2:0
//! (8.5x vs 3.3x at 720p60) because nothing has to subsample the chroma,
//! and it is the only way to hold a one-pixel saturated line on
//! near-black — which is this game's whole visual vocabulary.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::io::{Read, Write};
use std::process::{Child, Command, Stdio};

/// One encoded access unit.
pub struct Packet {
    pub data: Vec<u8>,
    pub is_key: bool,
}

pub struct H264Encoder {
    child: Option<Child>,
    width: usize,
    height: usize,
    /// Where x264 leaves the elementary stream. Read back at finish:
    /// x264 writes Annex B, which has to be cut into access units and
    /// have its parameter sets lifted out before it can be muxed.
    raw: std::path::PathBuf,
    y: Vec<u8>,
    u: Vec<u8>,
    v: Vec<u8>,
}

impl H264Encoder {
    pub fn new(
        width: u32,
        height: u32,
        fps: u32,
        crf: u8,
        preset: &str,
        raw: std::path::PathBuf,
    ) -> PyResult<Self> {
        const PRESETS: [&str; 10] = [
            "ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower",
            "veryslow", "placebo",
        ];
        if !PRESETS.contains(&preset) {
            return Err(PyValueError::new_err(format!(
                "H264Encoder: unknown x264 preset {preset:?}"
            )));
        }
        let (w, h) = (width as usize, height as usize);
        // y4m over stdin: x264 reads the header itself, so the geometry
        // and frame rate travel with the data instead of as flags that
        // could disagree with it.
        let child = Command::new("x264")
            .args([
                "--demuxer", "y4m",
                // Keep the chroma planes full size. Without this x264
                // defaults to I420 output and tries to DOWNCONVERT the
                // 4:4:4 input, which needs swscale — a build without it
                // dies with "resize [error]: not compiled with swscale
                // support" and the pipe simply breaks under you.
                "--output-csp", "i444",
                "--preset", preset,
                "--crf", &crf.to_string(),
                "--keyint", &(fps * 2).to_string(), // 2s, so a clip can be scrubbed
                // NO B-FRAMES, and this is correctness rather than
                // taste: reordered frames need a `ctts` box to carry
                // composition times, and x264's raw Annex B output
                // carries no timestamps to build one from, so the muxer
                // would be inventing them. Capture wants low latency
                // anyway, and a telemetry recorder that reorders frames
                // is buying compression with the one property the
                // recording exists to preserve — when things happened.
                "--bframes", "0",
                "--log-level", "none",
                "-o",
            ])
            .arg(&raw)
            .arg("-")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| {
                PyValueError::new_err(format!(
                    "H264Encoder: could not start x264 ({e}). It ships as a separate \
                     executable on purpose — see the module note on the GPL boundary."
                ))
            })?;
        let mut me = Self {
            child: Some(child),
            width: w,
            height: h,
            raw,
            y: vec![0; w * h],
            u: vec![0; w * h],
            v: vec![0; w * h],
        };
        let header = format!("YUV4MPEG2 W{w} H{h} F{fps}:1 Ip A1:1 C444\n");
        me.write_all(header.as_bytes())?;
        Ok(me)
    }

    fn write_all(&mut self, buf: &[u8]) -> PyResult<()> {
        let child = self
            .child
            .as_mut()
            .ok_or_else(|| PyValueError::new_err("H264Encoder: already finished"))?;
        let stdin = child
            .stdin
            .as_mut()
            .ok_or_else(|| PyValueError::new_err("H264Encoder: x264 stdin closed"))?;
        stdin
            .write_all(buf)
            .map_err(|e| PyValueError::new_err(format!("H264Encoder: writing to x264: {e}")))
    }

    /// Feed one RGB24 frame (`width * height * 3` bytes).
    pub fn encode(&mut self, rgb: &[u8]) -> PyResult<()> {
        let want = self.width * self.height * 3;
        if rgb.len() != want {
            return Err(PyValueError::new_err(format!(
                "H264Encoder.encode: expected {want} bytes for {}x{}, got {}",
                self.width,
                self.height,
                rgb.len()
            )));
        }
        // Full-range BT.601 RGB -> YUV, all three planes full size.
        for i in 0..self.width * self.height {
            let (r, g, b) = (
                f32::from(rgb[i * 3]),
                f32::from(rgb[i * 3 + 1]),
                f32::from(rgb[i * 3 + 2]),
            );
            let y = 0.299 * r + 0.587 * g + 0.114 * b;
            self.y[i] = y.round().clamp(0.0, 255.0) as u8;
            self.u[i] = ((b - y) * 0.564 + 128.0).round().clamp(0.0, 255.0) as u8;
            self.v[i] = ((r - y) * 0.713 + 128.0).round().clamp(0.0, 255.0) as u8;
        }
        self.write_all(b"FRAME\n")?;
        let (y, u, v) = (
            std::mem::take(&mut self.y),
            std::mem::take(&mut self.u),
            std::mem::take(&mut self.v),
        );
        let r = self
            .write_all(&y)
            .and_then(|_| self.write_all(&u))
            .and_then(|_| self.write_all(&v));
        self.y = y;
        self.u = u;
        self.v = v;
        r
    }

    /// Close x264's input, wait for it, and read back the access units
    /// plus the `avcC` record the muxer needs.
    pub fn finish(&mut self) -> PyResult<(Vec<Packet>, Vec<u8>)> {
        let mut child = self
            .child
            .take()
            .ok_or_else(|| PyValueError::new_err("H264Encoder: already finished"))?;
        drop(child.stdin.take()); // EOF: x264 flushes and exits
        let status = child
            .wait()
            .map_err(|e| PyValueError::new_err(format!("H264Encoder: waiting for x264: {e}")))?;
        if !status.success() {
            return Err(PyValueError::new_err(format!(
                "H264Encoder: x264 exited with {status}"
            )));
        }
        let mut buf = Vec::new();
        std::fs::File::open(&self.raw)
            .and_then(|mut f| f.read_to_end(&mut buf))
            .map_err(|e| PyValueError::new_err(format!("H264Encoder: reading x264 output: {e}")))?;
        let _ = std::fs::remove_file(&self.raw);
        Ok(split_annex_b(&buf))
    }
}

impl Drop for H264Encoder {
    fn drop(&mut self) {
        if let Some(mut c) = self.child.take() {
            drop(c.stdin.take());
            let _ = c.wait();
            let _ = std::fs::remove_file(&self.raw);
        }
    }
}

/// Cut an Annex B stream into access units and build the `avcC` record.
///
/// MP4 does not carry start codes: each sample is length-prefixed NAL
/// units, and the SPS/PPS travel in the sample entry rather than in the
/// stream. So the parameter sets are lifted out here and everything else
/// is regrouped into one sample per picture.
fn split_annex_b(buf: &[u8]) -> (Vec<Packet>, Vec<u8>) {
    let mut nals: Vec<&[u8]> = Vec::new();
    let mut i = 0usize;
    let mut start: Option<usize> = None;
    while i + 3 <= buf.len() {
        let three = buf[i] == 0 && buf[i + 1] == 0 && buf[i + 2] == 1;
        let four = i + 4 <= buf.len()
            && buf[i] == 0
            && buf[i + 1] == 0
            && buf[i + 2] == 0
            && buf[i + 3] == 1;
        if three || four {
            let sc = if four { 4 } else { 3 };
            if let Some(s) = start {
                nals.push(&buf[s..i]);
            }
            i += sc;
            start = Some(i);
        } else {
            i += 1;
        }
    }
    if let Some(s) = start {
        nals.push(&buf[s..]);
    }

    let (mut sps, mut pps) = (Vec::new(), Vec::new());
    let mut packets: Vec<Packet> = Vec::new();
    let mut current: Vec<u8> = Vec::new();
    let mut current_key = false;
    // Whether the unit being assembled already holds a picture. Without
    // this, the SEI that precedes the first IDR closes an access unit
    // that has no slice in it, and the clip comes out one sample longer
    // than the frame count — which `finish` rightly refuses to write.
    let mut has_vcl = false;
    for nal in nals {
        if nal.is_empty() {
            continue;
        }
        let kind = nal[0] & 0x1F;
        match kind {
            7 => {
                sps = nal.to_vec();
                continue;
            }
            8 => {
                pps = nal.to_vec();
                continue;
            }
            9 => continue, // access unit delimiter: not carried in MP4
            _ => {}
        }
        // VCL NAL types 1 and 5 each begin a picture.
        if (kind == 1 || kind == 5) && has_vcl {
            packets.push(Packet { data: std::mem::take(&mut current), is_key: current_key });
            current_key = false;
            has_vcl = false;
        }
        if kind == 1 || kind == 5 {
            has_vcl = true;
        }
        if kind == 5 {
            current_key = true;
        }
        current.extend_from_slice(&(nal.len() as u32).to_be_bytes());
        current.extend_from_slice(nal);
    }
    if !current.is_empty() {
        packets.push(Packet { data: current, is_key: current_key });
    }

    let mut avcc = Vec::new();
    if sps.len() >= 4 {
        avcc.push(1); // configurationVersion
        avcc.push(sps[1]); // AVCProfileIndication
        avcc.push(sps[2]); // profile_compatibility
        avcc.push(sps[3]); // AVCLevelIndication
        avcc.push(0xFF); // 6 bits reserved | lengthSizeMinusOne = 3
        avcc.push(0xE1); // 3 bits reserved | numOfSequenceParameterSets = 1
        avcc.extend_from_slice(&(sps.len() as u16).to_be_bytes());
        avcc.extend_from_slice(&sps);
        avcc.push(1); // numOfPictureParameterSets
        avcc.extend_from_slice(&(pps.len() as u16).to_be_bytes());
        avcc.extend_from_slice(&pps);
        // High 4:4:4 profiles carry three more fields; without them some
        // decoders assume 4:2:0 and render the chroma planes wrong.
        if matches!(sps[1], 100 | 110 | 122 | 244) {
            avcc.push(0xFC | 3); // reserved | chroma_format = 3 (4:4:4)
            avcc.push(0xF8); // reserved | bit_depth_luma_minus8 = 0
            avcc.push(0xF8); // reserved | bit_depth_chroma_minus8 = 0
            avcc.push(0); // numOfSequenceParameterSetExt
        }
    }
    (packets, avcc)
}
