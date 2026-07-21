//! hayate Tier 2 accelerator (DESIGN.md §14.2).
//!
//! Rules of the tier: behaviorally identical to the pure-Python path for
//! everything it accepts, and a `TypeError` for everything else so the
//! caller can fall back. Semantics live in Python; this is only speed.

use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

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
    if let Ok(b) = value.downcast::<PyBool>() {
        out.push_str(if b.is_true() { "true" } else { "false" });
        return Ok(());
    }
    if let Ok(s) = value.downcast::<PyString>() {
        write_json_string(out, s.to_str()?);
        return Ok(());
    }
    if value.downcast::<PyInt>().is_ok() {
        match value.extract::<i64>() {
            Ok(n) => {
                out.push_str(&n.to_string());
                return Ok(());
            }
            // Arbitrary-precision ints go through the stdlib fallback.
            Err(_) => return Err(PyTypeError::new_err("int out of accelerator range")),
        }
    }
    if value.downcast::<PyFloat>().is_ok() {
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
    if let Ok(list) = value.downcast::<PyList>() {
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
    if let Ok(tuple) = value.downcast::<PyTuple>() {
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
    if let Ok(dict) = value.downcast::<PyDict>() {
        out.push('{');
        let mut first = true;
        for (key, item) in dict.iter() {
            let key_str = key
                .downcast::<PyString>()
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

#[pymodule]
fn hayate_accel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(json_dumps, m)?)?;
    Ok(())
}
