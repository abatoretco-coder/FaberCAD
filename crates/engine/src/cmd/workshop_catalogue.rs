//! Embedded furniture catalogue; UI, CLI and MCP share one atomic insertion.
use std::collections::BTreeMap;

use super::CommandSpec;
use crate::schema::{TypedContract, output_schema_for};
use crate::{Result, Session, params::bad};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

const SOURCE: &str = include_str!("../../../../catalogue/furniture.json");
const COMMAND: &str = "workshop.insert";

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct InsertParams {
    pub id: String,
    pub name: String,
    /// Only numeric fields already present on this entry may be overridden.
    #[serde(default)]
    pub dimensions: BTreeMap<String, f64>,
}

#[derive(Debug, Serialize, JsonSchema)]
pub struct Inserted {
    pub catalogue_id: String,
    pub components: Vec<String>,
    pub parameters: Value,
    pub geometry_provenance: Value,
}

const INSERT: TypedContract<InsertParams> = TypedContract::new();
pub static COMMANDS: &[CommandSpec] = &[CommandSpec::new(COMMAND, "Insert Catalogue Part", crate::checked!("workshop.insert", insert))
    .icon("library").contract(&INSERT).output(output_schema_for::<Inserted>)
    .params("id: workshop.library furniture_catalogue entry id; name: unique name; dimensions?: numeric overrides from that entry. Inserts editable generic geometry atomically, with provenance, as one undo step. No manufacturer or drilling qualification.")];

pub(super) fn catalogue() -> Result<Value> {
    let data: Value = serde_json::from_str(SOURCE).map_err(|e| bad(COMMAND, e.to_string()))?;
    if data["schema_version"] != 1 || data["units"] != "mm" || !data["entries"].is_array() {
        return Err(bad(COMMAND, "unsupported furniture catalogue"));
    }
    Ok(data)
}

fn dimension(p: &Value, key: &str) -> Result<f64> {
    p[key].as_f64().filter(|v| v.is_finite() && *v > 0.0).ok_or_else(|| bad(COMMAND, format!("invalid {key}")))
}

fn box_(s: &mut Session, body: &str, length: f64, width: f64, height: f64, join: bool) -> Result<()> {
    let mut p = json!({"corner":[0,0,0],"length":length,"width":width,"height":height});
    if join {
        p["operation"] = json!("join");
        p["targets"] = json!([body]);
    } else {
        p["body_name"] = json!(body);
    }
    s.execute("solid.box", &p)?;
    Ok(())
}

pub(super) fn insert(s: &mut Session, input: &Value) -> Result<Value> {
    let input: InsertParams = serde_json::from_value(input.clone()).map_err(|e| bad(COMMAND, e.to_string()))?;
    if input.name.trim().is_empty()
        || input.name.chars().count() > 60
        || input.name.chars().any(char::is_control)
        || input.name == "root"
        || s.active_sketch.is_some()
    {
        return Err(bad(COMMAND, "choose a unique name of 1..60 printable characters and finish the active sketch"));
    }
    let data = catalogue()?;
    let entries = data["entries"].as_array().ok_or_else(|| bad(COMMAND, "missing furniture entries"))?;
    let entry = entries.iter().find(|e| e["id"] == input.id).ok_or_else(|| bad(COMMAND, "unknown catalogue id"))?;
    let kind = entry["type"].as_str().ok_or_else(|| bad(COMMAND, "missing catalogue type"))?;
    let mut parameters = entry["parameters"].clone();
    for (key, value) in &input.dimensions {
        let maximum = if kind == "board" { 10000.0 } else { 2000.0 };
        if !parameters.get(key).is_some_and(Value::is_number) || !value.is_finite() || *value <= 0.0 || *value > maximum {
            return Err(bad(COMMAND, format!("invalid or unsupported dimension {key}")));
        }
        parameters[key] = json!(value);
    }
    let name = &input.name;
    let components =
        if matches!(kind, "butt_hinge" | "drawer_slide") { vec![format!("{name} fixed"), format!("{name} moving")] } else { vec![name.clone()] };
    if s.doc.components.iter().any(|c| components.contains(&c.name)) {
        return Err(bad(COMMAND, "a component already uses this name"));
    }
    if s.world_state()?.body(&format!("{name} envelope")).is_some() {
        return Err(bad(COMMAND, "a body already uses this catalogue name"));
    }
    let mut computed = s.scratch();
    computed.execute("component.activate", &json!({"component":"root"}))?;
    match kind {
        "board" | "standard" => {
            let mut p = parameters.clone();
            p["name"] = json!(name);
            let command = if kind == "board" { "wood.board" } else { "parts.insert" };
            if kind == "standard" {
                p["point"] = json!([0, 0, 0]);
            }
            computed.execute(command, &p)?;
        }
        "butt_hinge" | "drawer_slide" => {
            let mut p = parameters.clone();
            p["name"] = json!(name);
            p["template"] = json!(kind);
            computed.execute("furniture.insert", &p)?;
        }
        "wood_dowel" | "shelf_pin" | "wood_screw" | "angle_bracket" | "foot_pad" => {
            let body = format!("{name} envelope");
            computed.execute("component.create", &json!({"name":name}))?;
            let length = dimension(&parameters, "length_mm")?;
            if matches!(kind, "wood_dowel" | "shelf_pin" | "wood_screw") {
                let d = dimension(&parameters, "diameter_mm")?;
                if kind == "wood_screw" && length <= 0.5 {
                    return Err(bad(COMMAND, "wood screw allowance must be longer than 0.5 mm"));
                }
                computed.execute("solid.cylinder", &json!({"base":[0,0,0],"radius":d/2.0,"height":length,"body_name":body}))?;
                if kind == "wood_screw" {
                    computed.execute(
                        "solid.cylinder",
                        &json!({"base":[0,0,length-0.5],"radius":d,"height":d*0.6+0.5,
                        "operation":"join","targets":[body]}),
                    )?;
                }
            } else {
                let width = dimension(&parameters, "width_mm")?;
                let thickness = dimension(&parameters, "thickness_mm")?;
                if kind == "angle_bracket" && (thickness >= length || thickness >= width) {
                    return Err(bad(COMMAND, "bracket thickness must be smaller than its length and width"));
                }
                box_(&mut computed, &body, length, width, thickness, false)?;
                if kind == "angle_bracket" {
                    box_(&mut computed, &body, thickness, width, length, true)?;
                }
            }
            let (density, colour) = match kind {
                "wood_dowel" => (0.71, "#C49A74"),
                "foot_pad" => (1.0, "#353535"),
                _ => (7.85, "#9CA3AF"),
            };
            let material = (1..=computed.doc.user_materials.len() + 1)
                .map(|n| format!("Catalogue material {n}"))
                .find(|name| !computed.doc.user_materials.iter().any(|m| m.name.eq_ignore_ascii_case(name)))
                .ok_or_else(|| bad(COMMAND, "could not reserve a catalogue material name"))?;
            computed.execute("material.create", &json!({"name":material,"density_g_cm3":density,"color":colour}))?;
            computed.execute("material.assign", &json!({"bodies":[body],"material":material}))?;
        }
        _ => return Err(bad(COMMAND, "unsupported catalogue geometry")),
    }
    let provenance = json!({"kind":entry["geometry_kind"],"source":data["provenance"]["source"],"units":"mm",
        "generated_from_evidence":false,"license_or_usage_status":data["provenance"]["license_or_usage_status"],
        "fidelity":"nominal editable geometry; not manufacturer CAD","limitations":data["provenance"]["limitations"]});
    // Hash the effective selection, including edits, rather than claim the original
    // entry hash still describes customised geometry. No new hashing dependency.
    let bytes = serde_json::to_vec(&json!({"id":input.id,"parameters":parameters})).map_err(|e| bad(COMMAND, e.to_string()))?;
    let digest = solidcraft_doc::DesignLink::file_digest(&bytes);
    let limits = data["provenance"]["limitations"]
        .as_array()
        .ok_or_else(|| bad(COMMAND, "missing limitations"))?
        .iter()
        .filter_map(Value::as_str)
        .collect::<Vec<_>>()
        .join("; ");
    for component in &components {
        computed.execute(
            "component.metadata.set",
            &json!({"component":component,"description":entry["name"],"properties":{
            "catalogue_id":input.id,"catalogue_source":"catalogue/furniture.json","geometry_provenance":entry["geometry_kind"],
            "geometry_source":data["provenance"]["source"],"units":"mm","generated_from_evidence":"false",
            "effective_recipe_sha256":digest,"catalogue_parameters":parameters.to_string(),
            "manufacturer_reference_status":"none; generic design template","license_or_usage_status":data["provenance"]["license_or_usage_status"],
            "fidelity":"nominal editable geometry; supplier details unverified","limitations":limits}}),
        )?;
    }
    computed.undo.clear();
    computed.active_component = s.active_component;
    computed.active_occurrence_path = s.active_occurrence_path.clone();
    computed.active_sketch = s.active_sketch;
    s.accept_computed(computed);
    Ok(json!(Inserted { catalogue_id: input.id, components, parameters, geometry_provenance: provenance }))
}
