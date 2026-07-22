//! hayate Tier 2 accelerator (DESIGN.md §14.2).
//!
//! Rules of the tier: behaviorally identical to the pure-Python path for
//! everything it accepts, and a `TypeError` for everything else so the
//! caller can fall back. Semantics live in Python; this is only speed.

use memchr::memmem;
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

fn write_json_string(out: &mut String, value: &str) {
    out.push('"');
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_value(out: &mut String, value: &Bound<'_, PyAny>) -> PyResult<()> {
    if value.is_none() {
        out.push_str("null");
        return Ok(());
    }
    // bool first: it is a subclass of int.
    if let Ok(b) = value.cast::<PyBool>() {
        out.push_str(if b.is_true() { "true" } else { "false" });
        return Ok(());
    }
    if let Ok(s) = value.cast::<PyString>() {
        write_json_string(out, s.to_str()?);
        return Ok(());
    }
    if value.cast::<PyInt>().is_ok() {
        match value.extract::<i64>() {
            Ok(n) => {
                out.push_str(&n.to_string());
                return Ok(());
            }
            // Arbitrary-precision ints go through the stdlib fallback.
            Err(_) => return Err(PyTypeError::new_err("int out of accelerator range")),
        }
    }
    if value.cast::<PyFloat>().is_ok() {
        let f: f64 = value.extract()?;
        // Rust's Display never uses exponent notation, so extreme
        // magnitudes (and NaN/Infinity) go through the stdlib fallback
        // to keep the emitted text identical to json.dumps.
        if !f.is_finite() || f.abs() >= 1e16 || (f != 0.0 && f.abs() < 1e-4) {
            return Err(PyTypeError::new_err("float outside accelerator range"));
        }
        if f.fract() == 0.0 {
            out.push_str(&format!("{:.1}", f));
        } else {
            out.push_str(&format!("{}", f));
        }
        return Ok(());
    }
    if let Ok(list) = value.cast::<PyList>() {
        out.push('[');
        for (index, item) in list.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            write_value(out, &item)?;
        }
        out.push(']');
        return Ok(());
    }
    if let Ok(tuple) = value.cast::<PyTuple>() {
        out.push('[');
        for (index, item) in tuple.iter().enumerate() {
            if index > 0 {
                out.push(',');
            }
            write_value(out, &item)?;
        }
        out.push(']');
        return Ok(());
    }
    if let Ok(dict) = value.cast::<PyDict>() {
        out.push('{');
        let mut first = true;
        for (key, item) in dict.iter() {
            let key_str = key
                .cast::<PyString>()
                .map_err(|_| PyTypeError::new_err("dict keys must be str for the accelerator"))?
                .to_str()?
                .to_owned();
            if !first {
                out.push(',');
            }
            first = false;
            write_json_string(out, &key_str);
            out.push(':');
            write_value(out, &item)?;
        }
        out.push('}');
        return Ok(());
    }
    Err(PyTypeError::new_err("unsupported type for the accelerator"))
}

/// Compact JSON matching `json.dumps(x, ensure_ascii=False, separators=(",", ":"))`
/// for None / bool / str / int(i64) / finite float / list / tuple / str-keyed dict.
#[pyfunction]
fn json_dumps(value: &Bound<'_, PyAny>) -> PyResult<String> {
    let mut out = String::with_capacity(64);
    write_value(&mut out, value)?;
    Ok(out)
}

/// Multipart section splitting matching `hayate.formdata._py_sections`
/// exactly: sections after each delimiter, stop at the closing `--`
/// marker, strip one leading CRLF, split head/payload at the first blank
/// line, strip one trailing CRLF from the payload. Semantic parsing
/// (dispositions, File construction) stays in Python — this only trades
/// `bytes.split`'s section copies for SIMD scanning (memchr) plus a
/// single copy per head/payload.
#[pyfunction]
fn multipart_sections<'py>(
    py: Python<'py>,
    body: &[u8],
    delimiter: &[u8],
) -> PyResult<Vec<(Bound<'py, PyBytes>, Bound<'py, PyBytes>)>> {
    let mut sections = Vec::new();
    if delimiter.is_empty() {
        // bytes.split would raise; the caller always passes b"--" + boundary.
        return Err(PyTypeError::new_err("empty multipart delimiter"));
    }
    let finder = memmem::Finder::new(delimiter);
    let starts: Vec<usize> = finder.find_iter(body).map(|pos| pos + delimiter.len()).collect();
    let blank = memmem::Finder::new(b"\r\n\r\n");
    for (index, &start) in starts.iter().enumerate() {
        let end = if index + 1 < starts.len() {
            starts[index + 1] - delimiter.len()
        } else {
            body.len()
        };
        let mut section = &body[start..end];
        if section.starts_with(b"--") {
            break; // closing delimiter
        }
        if section.starts_with(b"\r\n") {
            section = &section[2..];
        }
        let Some(sep) = blank.find(section) else {
            continue;
        };
        let head = &section[..sep];
        let mut payload = &section[sep + 4..];
        if payload.ends_with(b"\r\n") {
            payload = &payload[..payload.len() - 2];
        }
        sections.push((PyBytes::new(py, head), PyBytes::new(py, payload)));
    }
    Ok(sections)
}

#[pymodule]
fn hayate_accel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(json_dumps, m)?)?;
    m.add_function(wrap_pyfunction!(multipart_sections, m)?)?;
    Ok(())
}
