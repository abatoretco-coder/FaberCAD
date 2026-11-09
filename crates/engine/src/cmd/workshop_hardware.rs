//! Original furniture hardware envelopes with actual assembly joints.
//! User dimensions describe a design allowance, never a supplier drilling pattern.
use super::CommandSpec;
use crate::schema::{TypedContract, output_schema_for};
use crate::{Result, Session, params::bad};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct LibraryParams {}

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct InsertParams {
    pub name: String,
    pub template: String,
    pub length_mm: f64,
    pub width_mm: f64,
    pub thickness_mm: f64,
    #[serde(default)]
    pub travel: Option<f64>,
    #[serde(default)]
    pub clearance_mm: Option<f64>,
}

#[derive(Debug, Serialize, JsonSchema)]
pub struct HardwareCatalogue {
    pub templates: Vec<Value>,
    pub units: String,
    pub limitations: Vec<String>,
}

#[derive(Debug, Serialize, JsonSchema)]
pub struct InsertedHardware {
    pub template: String,
    pub components: Vec<String>,
    pub bodies: Vec<String>,
    pub joint: String,
    pub travel: f64,
    pub travel_unit: String,
    pub geometry_provenance: Value,
    pub manufacturer_reference: Option<String>,
    pub limitations: Vec<String>,
}

const LIBRARY: TypedContract<LibraryParams> = TypedContract::new();
const INSERT: TypedContract<InsertParams> = TypedContract::new();
const MATERIAL: &str = "Workshop Generic Steel";
const LIMITATIONS: &[&str] = &[
    "generic design envelope; not manufacturer CAD",
    "no mounting holes, countersinks, knuckles, bearings or supplier drilling pattern",
    "travel is a designer-selected nominal limit, not a physical hardware rating",
    "no load rating or manufacturing qualification; select actual hardware before drilling",
];

pub static COMMANDS: &[CommandSpec] = &[
    CommandSpec::new("furniture.library", "Furniture Hardware", crate::checked!("furniture.library", library))
        .icon("library").noundo().contract(&LIBRARY).output(output_schema_for::<HardwareCatalogue>)
        .params("Original generic butt-hinge and drawer-slide envelopes. Dimensions and travel are design assumptions, not supplier references or universal drill patterns."),
    CommandSpec::new("furniture.insert", "Insert Furniture Hardware", crate::checked!("furniture.insert", insert))
        .icon("joint").contract(&INSERT).output(output_schema_for::<InsertedHardware>)
        .params("name, template: butt_hinge|drawer_slide, length_mm, width_mm, thickness_mm; travel?: nominal hinge angle (deg) or slide travel (mm); clearance_mm?: 0.5. Creates two components and a real revolute/slider joint at the origin; fixed component is grounded. Original envelopes, no supplier mounting pattern."),
];

pub(super) fn library(_s: &mut Session, p: &Value) -> Result<Value> {
    let _: LibraryParams = serde_json::from_value(p.clone()).map_err(|e| bad("furniture.library", e.to_string()))?;
    Ok(json!(HardwareCatalogue {
        templates: vec![
            json!({"id":"butt_hinge","length_mm":60,"width_mm":40,"thickness_mm":2,"travel":110,"travel_unit":"deg",
                "length_axis":"z","width_axis":"x","joint":"revolute","clearance_mm":0.5}),
            json!({"id":"drawer_slide","length_mm":400,"width_mm":20,"thickness_mm":10,"travel":300,"travel_unit":"mm",
                "length_axis":"x","width_axis":"y","joint":"slider","clearance_mm":0.5})
        ],
        units: "mm".into(),
        limitations: LIMITATIONS.iter().map(|s| (*s).into()).collect()
    }))
}

fn valid_dimension(value: f64) -> bool {
    value.is_finite() && (0.5..=2000.0).contains(&value)
}

fn provenance() -> Value {
    json!({"kind":"envelope_proxy","source":"FABER original solid feature commands and user-selected dimensions",
        "units":"mm","generated_from_evidence":false,"license_or_usage_status":"original FABER geometry; no third-party CAD",
        "fidelity":"nominal exterior/kinematic design envelope only","limitations":LIMITATIONS})
}

fn component(s: &mut Session, name: &str, grounded: bool) -> Result<()> {
    s.execute("component.activate", &json!({"component":"root"}))?;
    s.execute("component.create", &json!({"name":name,"grounded":grounded}))?;
    Ok(())
}

pub(super) fn insert(s: &mut Session, p: &Value) -> Result<Value> {
    let p: InsertParams = serde_json::from_value(p.clone()).map_err(|e| bad("furniture.insert", e.to_string()))?;
    let hinge = match p.template.as_str() {
        "butt_hinge" => true,
        "drawer_slide" => false,
        _ => return Err(bad("furniture.insert", "choose butt_hinge or drawer_slide")),
    };
    let clearance = p.clearance_mm.unwrap_or(0.5);
    let travel = p.travel.unwrap_or(if hinge { 110.0 } else { p.length_mm * 0.75 });
    if p.name.trim().is_empty() || p.name.chars().count() > 60 || s.active_sketch.is_some() {
        return Err(bad("furniture.insert", "give a unique name of 1..60 characters and finish the active sketch"));
    }
    if ![p.length_mm, p.width_mm, p.thickness_mm].into_iter().all(valid_dimension)
        || !clearance.is_finite()
        || !(0.05..=10.0).contains(&clearance)
        || !travel.is_finite()
        || travel <= 0.0
        || travel > if hinge { 180.0 } else { p.length_mm }
        || (hinge && p.width_mm <= 3.0 * p.thickness_mm + 2.0 * clearance)
        || (!hinge && p.width_mm <= clearance + 1.0)
    {
        return Err(bad("furniture.insert", "invalid envelope dimensions, clearance or nominal travel"));
    }
    let components = vec![format!("{} fixed", p.name), format!("{} moving", p.name)];
    let bodies = vec![format!("{} fixed envelope", p.name), format!("{} moving envelope", p.name)];
    let joint = format!("{} motion", p.name);
    let world = s.world_state()?;
    if s.doc.components.iter().any(|c| components.contains(&c.name)) || bodies.iter().any(|name| world.body(name).is_some()) {
        return Err(bad("furniture.insert", "a hardware component or body already uses this name"));
    }
    let mut computed = s.scratch();
    if let Some(existing) = computed.doc.user_materials.iter().find(|m| m.name.eq_ignore_ascii_case(MATERIAL)) {
        if (existing.density - 7.85).abs() > 1e-9 {
            return Err(bad("furniture.insert", "generic steel name conflicts with an existing density"));
        }
    } else {
        computed.execute("material.create", &json!({"name":MATERIAL,"density_g_cm3":7.85,"color":"#9CA3AF"}))?;
    }
    component(&mut computed, &components[0], true)?;
    if hinge {
        computed.execute("solid.box", &json!({"corner":[-p.width_mm/2.0,-p.thickness_mm/2.0,0],"length":p.width_mm/2.0,"width":p.thickness_mm,"height":p.length_mm,"body_name":bodies[0]}))?;
        computed.execute(
            "solid.cylinder",
            &json!({"base":[0,0,0],"radius":1.5*p.thickness_mm,"height":p.length_mm,"operation":"join","targets":[bodies[0]]}),
        )?;
    } else {
        computed.execute(
            "solid.box",
            &json!({"corner":[0,0,0],"length":p.length_mm,"width":(p.width_mm-clearance)/2.0,"height":p.thickness_mm,"body_name":bodies[0]}),
        )?;
    }
    component(&mut computed, &components[1], false)?;
    if hinge {
        let start = 1.5 * p.thickness_mm + clearance;
        computed.execute("solid.box", &json!({"corner":[start,-p.thickness_mm/2.0,0],"length":p.width_mm/2.0-start,"width":p.thickness_mm,"height":p.length_mm,"body_name":bodies[1]}))?;
    } else {
        computed.execute("solid.box", &json!({"corner":[0,(p.width_mm+clearance)/2.0,0],"length":p.length_mm,"width":(p.width_mm-clearance)/2.0,"height":p.thickness_mm,"body_name":bodies[1]}))?;
    }
    for (index, name) in components.iter().enumerate() {
        computed.execute("material.assign", &json!({"bodies":[bodies[index]],"material":MATERIAL}))?;
        computed.execute("component.metadata.set", &json!({"component":name,"description":"FABER original furniture design envelope",
            "properties":{"geometry_provenance":"envelope_proxy","geometry_source":"FABER original primitives; user dimensions",
                "units":"mm","generated_from_evidence":"false","furniture_template":p.template,"furniture_assembly":p.name,
                "license_or_usage_status":"original FABER geometry; no third-party CAD","fidelity":"nominal design envelope only",
                "limitations":LIMITATIONS.join("; "),"nominal_clearance_mm":clearance.to_string(),"density_status":"nominal estimate, not product data"}}))?;
    }
    computed.execute(
        "joint.as_built",
        &json!({"name":joint,"type":if hinge {"revolute"} else {"slider"},"a":components[0],"b":components[1],
        "at":{"occurrence":components[0],"point":[0,0,0],"z":if hinge {[0,0,1]} else {[1,0,0]}},"limits":[[0,travel]],"quiet":true}),
    )?;
    computed.undo.clear();
    computed.active_component = s.active_component;
    computed.active_occurrence_path = s.active_occurrence_path.clone();
    computed.active_sketch = s.active_sketch;
    s.accept_computed(computed);
    Ok(json!(InsertedHardware {
        template: p.template,
        components,
        bodies,
        joint,
        travel,
        travel_unit: if hinge { "deg" } else { "mm" }.into(),
        geometry_provenance: provenance(),
        manufacturer_reference: None,
        limitations: LIMITATIONS.iter().map(|s| (*s).into()).collect()
    }))
}

#[cfg(test)]
#[path = "workshop_hardware_tests.rs"]
mod tests;
