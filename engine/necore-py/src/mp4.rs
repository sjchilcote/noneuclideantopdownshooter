//! A minimal ISO-BMFF writer — enough to put AV1 and AAC in an .mp4.
//!
//! This exists because minimp4, which muxed the H.264 path, speaks only
//! H.264 and HEVC: there is no `av01` sample entry in it, and AV1 was
//! worth about 9 dB and a third of the bytes on this game's footage
//! (see `av1.rs`). The sidecar code already hand-wrote ISO-BMFF boxes,
//! so the box plumbing was groundwork rather than new ground.
//!
//! Layout is `ftyp / mdat / moov`, i.e. sample data BEFORE the tables
//! that point at it, so every chunk offset is known by the time the
//! tables are built and nothing has to be patched afterwards. Samples
//! are written as one chunk per track. That is not the interleaving a
//! streaming server would want and is exactly right for a local clip.

/// Wrap a body in a box header. Everything here is built child-first and
/// then wrapped, so no size is ever written twice or patched later.
fn bx(kind: &[u8; 4], body: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(body.len() + 8);
    out.extend_from_slice(&((body.len() + 8) as u32).to_be_bytes());
    out.extend_from_slice(kind);
    out.extend_from_slice(body);
    out
}

fn full(version: u8, flags: u32, body: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(body.len() + 4);
    out.push(version);
    out.extend_from_slice(&flags.to_be_bytes()[1..]);
    out.extend_from_slice(body);
    out
}

fn u16b(v: u16) -> [u8; 2] {
    v.to_be_bytes()
}
fn u32b(v: u32) -> [u8; 4] {
    v.to_be_bytes()
}

/// The unity display matrix, as every muxer writes it.
const UNITY: [u32; 9] = [0x0001_0000, 0, 0, 0, 0x0001_0000, 0, 0, 0, 0x4000_0000];

/// Which video codec a track carries. The sample entry and the
/// configuration box are named for it.
#[derive(Clone, Copy, PartialEq)]
pub enum VideoCodec {
    Av1,
    H264,
}

impl VideoCodec {
    fn sample_entry(self) -> &'static [u8; 4] {
        match self {
            VideoCodec::Av1 => b"av01",
            VideoCodec::H264 => b"avc1",
        }
    }
    fn config_box(self) -> &'static [u8; 4] {
        match self {
            VideoCodec::Av1 => b"av1C",
            VideoCodec::H264 => b"avcC",
        }
    }
    fn brand(self) -> &'static [u8; 4] {
        match self {
            VideoCodec::Av1 => b"av01",
            VideoCodec::H264 => b"avc1",
        }
    }
}

/// One sample: its bytes, and whether a player may start decoding here.
pub struct Sample {
    pub data: Vec<u8>,
    pub is_sync: bool,
}

pub struct Track {
    pub samples: Vec<Sample>,
    /// Ticks per second for this track's media clock.
    pub timescale: u32,
    /// Duration of one sample in those ticks.
    pub sample_delta: u32,
    pub kind: TrackKind,
}

pub enum TrackKind {
    Video {
        width: u16,
        height: u16,
        /// The codec's decoder-configuration record — `av1C` for AV1,
        /// `avcC` for H.264. A player cannot set a decoder up from the
        /// samples alone; the parameter sets travel in the track
        /// description.
        config: Vec<u8>,
        codec: VideoCodec,
    },
    Audio {
        channels: u16,
        sample_rate: u32,
        /// The AudioSpecificConfig, for the `esds` descriptor.
        config: Vec<u8>,
    },
}

fn stbl(track: &Track, offset: u64) -> Vec<u8> {
    let n = track.samples.len() as u32;

    let stsd_entry = match &track.kind {
        TrackKind::Video { width, height, config, codec } => {
            let mut e = Vec::new();
            e.extend_from_slice(&[0; 6]); // reserved
            e.extend_from_slice(&u16b(1)); // data_reference_index
            e.extend_from_slice(&[0; 16]); // pre_defined / reserved
            e.extend_from_slice(&u16b(*width));
            e.extend_from_slice(&u16b(*height));
            e.extend_from_slice(&u32b(0x0048_0000)); // 72 dpi
            e.extend_from_slice(&u32b(0x0048_0000));
            e.extend_from_slice(&u32b(0)); // reserved
            e.extend_from_slice(&u16b(1)); // frame_count
            e.extend_from_slice(&[0; 32]); // compressorname
            e.extend_from_slice(&u16b(0x0018)); // depth
            e.extend_from_slice(&(-1i16).to_be_bytes()); // pre_defined
            e.extend_from_slice(&bx(codec.config_box(), config));
            bx(codec.sample_entry(), &e)
        }
        TrackKind::Audio { channels, sample_rate, config } => {
            let mut e = Vec::new();
            e.extend_from_slice(&[0; 6]);
            e.extend_from_slice(&u16b(1)); // data_reference_index
            e.extend_from_slice(&[0; 8]); // reserved
            e.extend_from_slice(&u16b(*channels));
            e.extend_from_slice(&u16b(16)); // sample size
            e.extend_from_slice(&u32b(0)); // pre_defined + reserved
            // 16.16 fixed; the field is 16-bit, so rates above 65535 are
            // carried by mdhd's timescale, which is what players read.
            e.extend_from_slice(&u16b(*sample_rate.min(&65535) as u16));
            e.extend_from_slice(&u16b(0));
            e.extend_from_slice(&bx(b"esds", &esds(config)));
            bx(b"mp4a", &e)
        }
    };
    let mut sd = Vec::new();
    sd.extend_from_slice(&u32b(1)); // entry_count
    sd.extend_from_slice(&stsd_entry);
    let stsd = bx(b"stsd", &full(0, 0, &sd));

    let mut tt = Vec::new();
    tt.extend_from_slice(&u32b(1)); // one run
    tt.extend_from_slice(&u32b(n));
    tt.extend_from_slice(&u32b(track.sample_delta));
    let stts = bx(b"stts", &full(0, 0, &tt));

    let mut sc = Vec::new();
    sc.extend_from_slice(&u32b(1)); // one chunk
    sc.extend_from_slice(&u32b(1)); // first_chunk
    sc.extend_from_slice(&u32b(n)); // samples_per_chunk
    sc.extend_from_slice(&u32b(1)); // sample_description_index
    let stsc = bx(b"stsc", &full(0, 0, &sc));

    let mut sz = Vec::new();
    sz.extend_from_slice(&u32b(0)); // sample_size 0 => per-sample table
    sz.extend_from_slice(&u32b(n));
    for s in &track.samples {
        sz.extend_from_slice(&u32b(s.data.len() as u32));
    }
    let stsz = bx(b"stsz", &full(0, 0, &sz));

    // 64-bit offsets: mdat comes first and a long capture can push the
    // tables past 4 GiB, where a 32-bit `stco` would silently wrap.
    let mut co = Vec::new();
    co.extend_from_slice(&u32b(1));
    co.extend_from_slice(&offset.to_be_bytes());
    let co64 = bx(b"co64", &full(0, 0, &co));

    let mut out = Vec::new();
    out.extend_from_slice(&stsd);
    out.extend_from_slice(&stts);
    // Only list sync samples when some frames are NOT sync — an absent
    // `stss` means "every sample is a random access point", which is
    // true for audio and would be a lie for video.
    let syncs: Vec<u32> = track
        .samples
        .iter()
        .enumerate()
        .filter(|(_, s)| s.is_sync)
        .map(|(i, _)| i as u32 + 1)
        .collect();
    if syncs.len() != track.samples.len() {
        let mut ss = Vec::new();
        ss.extend_from_slice(&u32b(syncs.len() as u32));
        for i in &syncs {
            ss.extend_from_slice(&u32b(*i));
        }
        out.extend_from_slice(&bx(b"stss", &full(0, 0, &ss)));
    }
    out.extend_from_slice(&stsc);
    out.extend_from_slice(&stsz);
    out.extend_from_slice(&co64);
    bx(b"stbl", &out)
}

/// The `esds` descriptor chain that tells a decoder this is AAC-LC and
/// hands it the AudioSpecificConfig.
fn esds(asc: &[u8]) -> Vec<u8> {
    fn desc(tag: u8, body: &[u8]) -> Vec<u8> {
        // Lengths use the 4-byte extended form throughout: legal, and it
        // keeps the encoding fixed-width instead of size-dependent.
        let mut out = vec![tag];
        let n = body.len() as u32;
        out.push(0x80 | ((n >> 21) & 0x7F) as u8);
        out.push(0x80 | ((n >> 14) & 0x7F) as u8);
        out.push(0x80 | ((n >> 7) & 0x7F) as u8);
        out.push((n & 0x7F) as u8);
        out.extend_from_slice(body);
        out
    }
    let dsi = desc(0x05, asc);
    let mut dcd = Vec::new();
    dcd.push(0x40); // MPEG-4 audio
    dcd.push(0x15); // audio stream
    dcd.extend_from_slice(&[0, 0, 0]); // bufferSizeDB
    dcd.extend_from_slice(&u32b(0)); // maxBitrate
    dcd.extend_from_slice(&u32b(0)); // avgBitrate
    dcd.extend_from_slice(&dsi);
    let dcd = desc(0x04, &dcd);
    let sl = desc(0x06, &[0x02]);

    let mut es = Vec::new();
    es.extend_from_slice(&u16b(1)); // ES_ID
    es.push(0); // flags
    es.extend_from_slice(&dcd);
    es.extend_from_slice(&sl);
    full(0, 0, &desc(0x03, &es))
}

fn trak(track: &Track, id: u32, movie_timescale: u32, offset: u64) -> Vec<u8> {
    let n = track.samples.len() as u64;
    let media_dur = n * u64::from(track.sample_delta);
    let movie_dur = media_dur * u64::from(movie_timescale) / u64::from(track.timescale).max(1);

    let mut tk = Vec::new();
    tk.extend_from_slice(&u32b(0)); // creation
    tk.extend_from_slice(&u32b(0)); // modification
    tk.extend_from_slice(&u32b(id));
    tk.extend_from_slice(&u32b(0)); // reserved
    tk.extend_from_slice(&u32b(movie_dur as u32));
    tk.extend_from_slice(&[0; 8]); // reserved
    tk.extend_from_slice(&u16b(0)); // layer
    tk.extend_from_slice(&u16b(0)); // alternate_group
    let vol: u16 = match track.kind {
        TrackKind::Audio { .. } => 0x0100,
        _ => 0,
    };
    tk.extend_from_slice(&u16b(vol));
    tk.extend_from_slice(&u16b(0)); // reserved
    for m in UNITY {
        tk.extend_from_slice(&u32b(m));
    }
    let (w, h) = match &track.kind {
        TrackKind::Video { width, height, .. } => (u32::from(*width), u32::from(*height)),
        TrackKind::Audio { .. } => (0, 0),
    };
    tk.extend_from_slice(&u32b(w << 16));
    tk.extend_from_slice(&u32b(h << 16));
    // flags 3 = track_enabled | track_in_movie
    let tkhd = bx(b"tkhd", &full(0, 3, &tk));

    let mut md = Vec::new();
    md.extend_from_slice(&u32b(0));
    md.extend_from_slice(&u32b(0));
    md.extend_from_slice(&u32b(track.timescale));
    md.extend_from_slice(&u32b(media_dur as u32));
    md.extend_from_slice(&u16b(0x55C4)); // 'und'
    md.extend_from_slice(&u16b(0));
    let mdhd = bx(b"mdhd", &full(0, 0, &md));

    let (handler, name): (&[u8; 4], &str) = match track.kind {
        TrackKind::Video { .. } => (b"vide", "VideoHandler"),
        TrackKind::Audio { .. } => (b"soun", "SoundHandler"),
    };
    let mut hd = Vec::new();
    hd.extend_from_slice(&u32b(0)); // pre_defined
    hd.extend_from_slice(handler);
    hd.extend_from_slice(&[0; 12]); // reserved
    hd.extend_from_slice(name.as_bytes());
    hd.push(0);
    let hdlr = bx(b"hdlr", &full(0, 0, &hd));

    let media_header = match track.kind {
        TrackKind::Video { .. } => bx(b"vmhd", &full(0, 1, &[0; 8])),
        TrackKind::Audio { .. } => bx(b"smhd", &full(0, 0, &[0; 4])),
    };
    let dref = {
        let mut d = Vec::new();
        d.extend_from_slice(&u32b(1));
        // flags 1 = the data is in this very file
        d.extend_from_slice(&bx(b"url ", &full(0, 1, &[])));
        bx(b"dref", &full(0, 0, &d))
    };
    let dinf = bx(b"dinf", &dref);

    let mut mi = Vec::new();
    mi.extend_from_slice(&media_header);
    mi.extend_from_slice(&dinf);
    mi.extend_from_slice(&stbl(track, offset));
    let minf = bx(b"minf", &mi);

    let mut mv = Vec::new();
    mv.extend_from_slice(&mdhd);
    mv.extend_from_slice(&hdlr);
    mv.extend_from_slice(&minf);
    let mdia = bx(b"mdia", &mv);

    let mut t = Vec::new();
    t.extend_from_slice(&tkhd);
    t.extend_from_slice(&mdia);
    bx(b"trak", &t)
}

/// Mux the given tracks into a complete file.
pub fn write(tracks: &[Track]) -> Vec<u8> {
    let movie_timescale = 1000u32;

    let codec = tracks
        .iter()
        .find_map(|t| match t.kind {
            TrackKind::Video { codec, .. } => Some(codec),
            _ => None,
        })
        .unwrap_or(VideoCodec::H264);
    let mut ft = Vec::new();
    ft.extend_from_slice(b"isom");
    ft.extend_from_slice(&u32b(0x200));
    for brand in [b"isom", b"iso2", codec.brand(), b"mp41"] {
        ft.extend_from_slice(brand);
    }
    let ftyp = bx(b"ftyp", &ft);

    // Lay the sample data out first so the tables can point at it.
    let mut mdat_body = Vec::new();
    let mut offsets = Vec::new();
    let base = ftyp.len() as u64 + 8; // + mdat header
    for t in tracks {
        offsets.push(base + mdat_body.len() as u64);
        for s in &t.samples {
            mdat_body.extend_from_slice(&s.data);
        }
    }
    let mdat = bx(b"mdat", &mdat_body);

    let longest = tracks
        .iter()
        .map(|t| {
            t.samples.len() as u64 * u64::from(t.sample_delta) * u64::from(movie_timescale)
                / u64::from(t.timescale).max(1)
        })
        .max()
        .unwrap_or(0);

    let mut mv = Vec::new();
    mv.extend_from_slice(&u32b(0)); // creation
    mv.extend_from_slice(&u32b(0)); // modification
    mv.extend_from_slice(&u32b(movie_timescale));
    mv.extend_from_slice(&u32b(longest as u32));
    mv.extend_from_slice(&u32b(0x0001_0000)); // rate 1.0
    mv.extend_from_slice(&u16b(0x0100)); // volume 1.0
    mv.extend_from_slice(&[0; 10]); // reserved
    for m in UNITY {
        mv.extend_from_slice(&u32b(m));
    }
    mv.extend_from_slice(&[0; 24]); // pre_defined
    mv.extend_from_slice(&u32b(tracks.len() as u32 + 1));
    let mvhd = bx(b"mvhd", &full(0, 0, &mv));

    let mut mo = Vec::new();
    mo.extend_from_slice(&mvhd);
    for (i, t) in tracks.iter().enumerate() {
        mo.extend_from_slice(&trak(t, i as u32 + 1, movie_timescale, offsets[i]));
    }
    let moov = bx(b"moov", &mo);

    let mut out = Vec::with_capacity(ftyp.len() + mdat.len() + moov.len());
    out.extend_from_slice(&ftyp);
    out.extend_from_slice(&mdat);
    out.extend_from_slice(&moov);
    out
}
